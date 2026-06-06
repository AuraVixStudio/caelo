"""Pytest bootstrap dla self-checków (P3-13).

Self-checki w `caelo_core/tools/` były dotąd uruchamiane jako samodzielne skrypty
z korzenia repo (`python caelo_core/tools/api_smoke.py`). `pytest caelo_core/tests`
zbiera je przez adapter (`test_selfchecks.py`) — ten conftest zapewnia, że korzeń
repo jest na `sys.path`, tak by importowalne były i pakiet `caelo_core`, i legacy
moduły z korzenia (`config`/`api_manager`/… — `caelo_core/__init__.py` i tak dokłada
korzeń, ale bootstrap musi go najpierw znaleźć przy starcie pytest).
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
