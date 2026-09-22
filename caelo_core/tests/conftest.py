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


def pytest_configure(config) -> None:
    """Obejdź zatruty `%TEMP%/pytest-of-<user>`.

    `tmp_path` buduje bazę `pytest-of-<user>` w katalogu tymczasowym systemu. Jeśli ten
    katalog zostanie z zepsutym ACL-em (na maszynie użytkownika `Get-Acl`, `takeown`
    i zwykłe listowanie zwracają „odmowa dostępu"), KAŻDY test korzystający z `tmp_path`
    wywala się na `PermissionError` jeszcze przed swoim kodem — mimo że sam kod jest
    zdrowy. Naprawa katalogu wymaga podniesionych uprawnień, więc gdy baza jest
    nieczytelna, kierujemy pytest na własną, świeżą bazę obok niej.

    Jawne `--basetemp` z linii poleceń ma pierwszeństwo i nie jest ruszane.
    """
    import getpass
    import tempfile
    from pathlib import Path

    if getattr(config.option, "basetemp", None):
        return
    temp_root = Path(tempfile.gettempdir())
    try:
        user = getpass.getuser()
    except Exception:
        return
    default_base = temp_root / f"pytest-of-{user}"
    if not default_base.exists():
        return
    try:
        with os.scandir(default_base):
            pass
    except OSError:
        # Stabilna nazwa: pytest czyści własne `--basetemp` na starcie, więc katalog
        # nie rośnie z każdym uruchomieniem.
        config.option.basetemp = str(temp_root / f"caelo-pytest-of-{user}")
