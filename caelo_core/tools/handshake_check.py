"""Self-check handshake'u sidecara — odwzorowuje to, co robi proces główny Electron.

Uruchamia ``python -m caelo_core`` z ustawionym CAELO_CORE_TOKEN, czeka na linię
handshake na stdout, a następnie weryfikuje:
  1. /health         -> 200 (bez autoryzacji),
  2. /whoami z tokenem  -> 200,
  3. /whoami bez tokenu -> 401,
  4. /whoami zły token  -> 403.

Użycie:  <python> caelo_core/tools/handshake_check.py
Kod wyjścia 0 = wszystkie asercje OK.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.dirname(THIS_DIR)          # .../caelo_core
REPO_DIR = os.path.dirname(PKG_DIR)          # repo root
PREFIX = "__CAELO_CORE_READY__"


def _read_handshake(proc: subprocess.Popen, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                raise RuntimeError("sidecar exited before handshake")
            continue
        line = line.strip()
        if line.startswith(PREFIX):
            return json.loads(line[len(PREFIX):].strip())
    raise RuntimeError("timed out waiting for handshake line")


def _get(base: str, path: str, token: str | None = None):
    req = urllib.request.Request(base + path)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None


def main() -> int:
    token = secrets.token_urlsafe(16)
    env = dict(os.environ, CAELO_CORE_TOKEN=token)
    proc = subprocess.Popen(
        [sys.executable, "-m", "caelo_core"],
        cwd=REPO_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        info = _read_handshake(proc)
        port = info["port"]
        base = f"http://127.0.0.1:{port}"
        print(f"[handshake] port={port} version={info.get('version')} token-match={info.get('token') == token}")

        checks = []
        s, body = _get(base, "/health")
        checks.append(("/health == 200", s == 200 and body and body.get("status") == "ok"))
        s, body = _get(base, "/whoami", token)
        checks.append(("/whoami (token) == 200", s == 200 and body and body.get("authenticated") is True))
        s, _ = _get(base, "/whoami")
        checks.append(("/whoami (no token) == 401", s == 401))
        s, _ = _get(base, "/whoami", "wrong-token")
        checks.append(("/whoami (bad token) == 403", s == 403))

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


if __name__ == "__main__":
    raise SystemExit(main())
