"""Smoke-test SPAKOWANEGO sidecara (dist\\caelo-core\\caelo-core.exe).

Uruchamia zbudowany przez PyInstallera .exe dokładnie tak, jak robi to Electron
(env CAELO_CORE_TOKEN + odczyt handshake'u na stdout) i sprawdza, że frozen bundle
realnie wstaje: handshake, /health, /whoami(token) oraz brak/zły token -> 401/403.

To weryfikuje, że PyInstaller dociągnął wszystkie ukryte importy (uvicorn/fastapi/
legacy config…). Uruchom PO `build_sidecar.ps1`. Kod wyjścia 0 = OK.

Użycie:
    python caelo_core/tools/sidecar_smoke.py [ścieżka\\do\\caelo-core.exe]
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(os.path.dirname(THIS_DIR))
PREFIX = "__CAELO_CORE_READY__"
DEFAULT_EXE = os.path.join(REPO_DIR, "dist", "caelo-core", "caelo-core.exe")


def _read_handshake(proc: subprocess.Popen, timeout: float = 40.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                err = proc.stderr.read() if proc.stderr else ""
                raise RuntimeError(f"sidecar exited before handshake:\n{err}")
            continue
        line = line.strip()
        if line.startswith(PREFIX):
            return json.loads(line[len(PREFIX):].strip())
    raise RuntimeError("timed out waiting for handshake")


def _get(base: str, path: str, token: str | None = None):
    req = urllib.request.Request(base + path)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None


def main() -> int:
    exe = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EXE
    if not os.path.exists(exe):
        print(f"NOT FOUND: {exe}\nBuild it first: pwsh -File build_sidecar.ps1")
        return 2

    token = secrets.token_urlsafe(16)
    # P1-E: izolowany DATA_DIR — chroni realne %LOCALAPPDATA%\Caelo przy smoke spakowanego .exe
    # (override honorowany też dla frozen — przed gałęzią IS_FROZEN w config.py).
    tmp_data = tempfile.mkdtemp(prefix="caelo-sidecar-")
    env = dict(os.environ, CAELO_CORE_TOKEN=token, CAELO_CORE_DATA_DIR=tmp_data)
    proc = subprocess.Popen(
        [exe], cwd=os.path.dirname(exe), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        info = _read_handshake(proc)
        port = info["port"]
        base = f"http://127.0.0.1:{port}"
        print(f"[handshake] port={port} version={info.get('version')} token_ok={info.get('token') == token}")

        checks = []
        s, body = _get(base, "/health")
        checks.append(("/health == 200", s == 200 and bool(body)))
        s, body = _get(base, "/whoami", token)
        checks.append(("/whoami(token) == 200 + backend_ready", s == 200 and body and body.get("backend_ready") is True))
        s, _ = _get(base, "/whoami")
        checks.append(("/whoami (no token) == 401", s == 401))
        s, _ = _get(base, "/whoami", "wrong")
        checks.append(("/whoami (bad token) == 403", s == 403))
        checks.append(("handshake token matches env", info.get("token") == token))

        ok = True
        for name, passed in checks:
            print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
            ok = ok and passed
        print("RESULT:", "OK" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        shutil.rmtree(tmp_data, ignore_errors=True)  # P1-E: sprzątanie temp DATA_DIR


if __name__ == "__main__":
    raise SystemExit(main())
