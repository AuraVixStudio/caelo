"""grok-core — backend-sidecar (FastAPI) dla Grok Desktop.

Pakiet serwisowy uruchamiany przez proces główny Electron jako podproces
(sidecar). Reużywa dojrzałych managerów legacy z korzenia repo
(`api_manager`, `oauth_manager`, `chats_manager`, `history_manager`, `config`)
i wystawia je przez HTTP/WebSocket. Logiki xAI nie przepisujemy od zera.
"""

import sys
from pathlib import Path

# Korzeń repo (rodzic katalogu pakietu) musi być na sys.path PRZED importem
# server/state, bo tamte importują legacy moduły z korzenia (config, api_manager…).
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from grok_core.server import APP_VERSION, create_app  # noqa: E402

__all__ = ["APP_VERSION", "create_app"]
