"""Punkt wejścia sidecara: ``python -m caelo_core``.

Przepływ handshake (uzgodniony z procesem głównym Electron):
- token sesji: z env ``CAELO_CORE_TOKEN`` (ustawiany przez Electron) lub — przy
  uruchomieniu samodzielnym — generowany losowo,
- port: z env ``CAELO_CORE_PORT`` lub pierwszy wolny port na 127.0.0.1,
- po starcie serwera na stdout wypisywana jest DOKŁADNIE JEDNA linia handshake::

      __CAELO_CORE_READY__ {"port": <int>, "token": "<str>", "version": "<str>"}

  którą Electron parsuje, by poznać adres backendu i token. Linia jest
  flushowana; logi uvicorna idą na stderr, więc stdout pozostaje czysty.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import sys

import uvicorn

from caelo_core.server import APP_VERSION, create_app

HANDSHAKE_PREFIX = "__CAELO_CORE_READY__"


def _free_port() -> int:
    """Zwraca wolny port TCP na pętli zwrotnej (best-effort)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def main() -> None:
    # Logi na stderr (stdout zarezerwowany na DOKŁADNIE JEDNĄ linię handshake).
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    token = os.environ.get("CAELO_CORE_TOKEN") or secrets.token_urlsafe(32)
    port = int(os.environ.get("CAELO_CORE_PORT") or _free_port())

    def announce() -> None:
        line = HANDSHAKE_PREFIX + " " + json.dumps(
            {"port": port, "token": token, "version": APP_VERSION}
        )
        print(line, flush=True)

    app = create_app(token=token, port=port, on_startup=announce)

    # host wymuszony na 127.0.0.1 — backend nie może być osiągalny z sieci.
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
