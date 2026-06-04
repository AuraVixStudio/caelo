"""WebSocket terminala (pty po stronie Pythona, pywinpty na Windows): /terminal.

Protokół (JSON):
  klient -> serwer: {"type":"input","data":"..."} / {"type":"resize","cols","rows"}
  serwer -> klient: {"type":"output","data":"..."} / {"type":"exit"} / {"type":"error","error"}

pywinpty jest OPCJONALNE — gdy brak, WS zwraca błąd z instrukcją instalacji
(agentowy run_command działa bez pty). Autoryzacja: token w query.

Bezpieczeństwo (P0-11): pty startuje ze ŚRODOWISKIEM POZBAWIONYM SEKRETÓW
(`scrubbed_env`) — tym samym scrubem co `run_command` (P0-6). Inaczej `set`/`env`
w shellu ujawniłyby GROK_CORE_TOKEN / XAI_API_KEY przez ten sam WS.
"""

from __future__ import annotations

import json
import os
import threading

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from grok_core.agent.tools import scrubbed_env
from grok_core.routes._ws import WsStream
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

    alive = threading.Event()
    alive.set()

    try:
        # P0-11: env bez sekretów (jak run_command) — `set`/`env` nie ujawnią tokenu/klucza.
        proc = PtyProcess.spawn(shell, cwd=cwd, env=scrubbed_env())
    except Exception as exc:  # noqa: BLE001
        await ws.send_json({"type": "error", "error": f"Cannot start shell: {exc}"})
        await ws.close()
        return

    async with WsStream(ws) as stream:

        def reader() -> None:
            try:
                while alive.is_set() and proc.isalive():
                    data = proc.read(1024)
                    if data:
                        # backpressure (P0-9): blokuje, gdy klient nie nadąża — bez OOM.
                        if not stream.emit({"type": "output", "data": data}):
                            return
            except Exception:
                pass
            finally:
                stream.emit({"type": "exit"})

        rt = threading.Thread(target=reader, daemon=True)
        stream.track(rt)   # P0-9: dołączony przy zamykaniu
        rt.start()

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
                proc.terminate(force=True)  # zakończ pty → reader wyjdzie → aclose dołączy
            except Exception:
                pass
