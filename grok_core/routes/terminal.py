"""WebSocket terminala (pty po stronie Pythona, pywinpty na Windows): /terminal.

Protokół (JSON):
  klient -> serwer: {"type":"input","data":"..."} / {"type":"resize","cols","rows"}
  serwer -> klient: {"type":"output","data":"..."} / {"type":"exit"} / {"type":"error","error"}

pywinpty jest OPCJONALNE — gdy brak, WS zwraca błąd z instrukcją instalacji
(agentowy run_command działa bez pty). Autoryzacja: token w query.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from grok_core.state import ws_authorized

router = APIRouter()


@router.websocket("/terminal")
async def terminal(ws: WebSocket) -> None:
    if not ws_authorized(ws):  # P0-8: fail-closed token + Origin
        await ws.close(code=1008)
        return
    await ws.accept()

    try:
        from winpty import PtyProcess  # type: ignore
    except Exception:
        await ws.send_json({
            "type": "error",
            "error": "Terminal unavailable: install 'pywinpty' in the backend venv.",
        })
        await ws.close()
        return

    backend = getattr(ws.app.state, "backend", None)
    ws_obj = backend.get_workspace() if backend else None
    cwd = str(ws_obj.root) if ws_obj else os.getcwd()
    shell = os.environ.get("COMSPEC", "cmd.exe") if os.name == "nt" else os.environ.get("SHELL", "/bin/bash")

    loop = asyncio.get_running_loop()
    out_q: asyncio.Queue = asyncio.Queue()
    alive = threading.Event()
    alive.set()

    try:
        proc = PtyProcess.spawn(shell, cwd=cwd)
    except Exception as exc:  # noqa: BLE001
        await ws.send_json({"type": "error", "error": f"Cannot start shell: {exc}"})
        await ws.close()
        return

    def reader() -> None:
        try:
            while alive.is_set() and proc.isalive():
                data = proc.read(1024)
                if data:
                    loop.call_soon_threadsafe(out_q.put_nowait, {"type": "output", "data": data})
        except Exception:
            pass
        finally:
            loop.call_soon_threadsafe(out_q.put_nowait, {"type": "exit"})
            loop.call_soon_threadsafe(out_q.put_nowait, None)

    threading.Thread(target=reader, daemon=True).start()

    async def sender() -> None:
        while True:
            item = await out_q.get()
            if item is None:
                return
            try:
                await ws.send_json(item)
            except Exception:
                return

    sender_task = asyncio.create_task(sender())

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get("type") == "input":
                proc.write(msg.get("data", ""))
            elif msg.get("type") == "resize":
                try:
                    proc.setwinsize(int(msg.get("rows", 24)), int(msg.get("cols", 80)))
                except Exception:
                    pass
    except WebSocketDisconnect:
        pass
    finally:
        alive.clear()
        try:
            proc.terminate(force=True)
        except Exception:
            pass
        out_q.put_nowait(None)
        try:
            await sender_task
        except Exception:
            pass
