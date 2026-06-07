"""Self-check sandboxa OS (M19-B7) — bez realnej egzekucji.

Sprawdza LOGIKĘ (mockowalne per-platforma, niezależne od OS testera):
1) Model profili: off/workspace/read-only/strict + nieznana→off; ścieżki wrażliwe
   zawsze na deny-liście.
2) `resolve_profile`: env `config.SANDBOX_PROFILE` + `<ws>/.caelo/sandbox.json`
   (projekt nadpisuje, listy scalane).
3) `wrap()` buduje poprawne argv: Linux→`bwrap` (+`--unshare-net` w strict, bind korzenia,
   maska ścieżek wrażliwych), macOS→`sandbox-exec` + profil Seatbelt; brak launchera/
   Windows→**no-op**; `off`→no-op.
4) Regresja: profil `off` (domyślny) NIE zmienia `run_command`.

**Realna egzekucja** (Landlock/Seatbelt/bwrap faktycznie blokuje zapis) = weryfikacja na
Linux/macOS użytkownika. Kod wyjścia 0 = OK.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import config  # noqa: E402
from caelo_core import sandbox  # noqa: E402

checks: list[tuple[str, bool]] = []


def check(name: str, passed: bool) -> None:
    checks.append((name, bool(passed)))


def test_profiles() -> None:
    off = sandbox.build_profile("off", root="/ws")
    check("profile: off has no read-all / write roots",
          off.name == "off" and not off.read_all and not off.write_paths)
    check("profile: off still carries sensitive deny", any(".ssh" in p for p in off.deny_paths))

    wsp = sandbox.build_profile("workspace", root="/ws")
    check("profile: workspace reads-all + writes root/tmp",
          wsp.read_all and "/ws" in wsp.write_paths and "/tmp" in wsp.write_paths
          and not wsp.restrict_network)

    ro = sandbox.build_profile("read-only", root="/ws")
    check("profile: read-only reads-all, no workspace write",
          ro.read_all and "/ws" not in ro.write_paths)

    st = sandbox.build_profile("strict", root="/ws")
    check("profile: strict root-only + no network",
          (not st.read_all) and "/ws" in st.read_paths and "/ws" in st.write_paths
          and st.restrict_network)

    check("profile: unknown name -> off (fail-safe)",
          sandbox.build_profile("bogus", root="/ws").name == "off")

    sp = sandbox.sensitive_paths()
    check("profile: sensitive paths include ssh/aws/gnupg",
          any(".ssh" in p for p in sp) and any(".aws" in p for p in sp)
          and any(".gnupg" in p for p in sp))


def test_resolve_config() -> None:
    prev_prof = getattr(config, "SANDBOX_PROFILE", "off")
    prev_data = config.DATA_DIR
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "data").mkdir()
        config.DATA_DIR = d / "data"
        try:
            ws = d / "ws"
            (ws / ".caelo").mkdir(parents=True)
            config.SANDBOX_PROFILE = "workspace"
            check("resolve: env/global profile used",
                  sandbox.resolve_profile(root=str(ws)).name == "workspace")

            (ws / ".caelo" / "sandbox.json").write_text(
                json.dumps({"default_profile": "strict", "read_write": ["/extra"]}),
                encoding="utf-8")
            prof = sandbox.resolve_profile(root=str(ws))
            check("resolve: project sandbox.json overrides profile", prof.name == "strict")
            check("resolve: project read_write merged into write_paths",
                  "/extra" in prof.write_paths)

            config.SANDBOX_PROFILE = "off"
            ws2 = d / "ws2"
            ws2.mkdir()
            check("resolve: default off when nothing set",
                  sandbox.resolve_profile(root=str(ws2)).name == "off")
        finally:
            config.SANDBOX_PROFILE = prev_prof
            config.DATA_DIR = prev_data


def test_wrap_linux() -> None:
    bwrap_which = lambda name: "/usr/bin/bwrap" if name == "bwrap" else None  # noqa: E731
    st = sandbox.build_profile("strict", root="/ws")
    argv = sandbox.wrap(["echo", "hi"], st, root="/ws", platform="linux", which=bwrap_which)
    check("wrap(linux): bwrap launcher prefix", argv[0] == "/usr/bin/bwrap")
    check("wrap(linux): strict cuts network (--unshare-net)", "--unshare-net" in argv)
    check("wrap(linux): original command after --",
          "--" in argv and argv[-2:] == ["echo", "hi"])
    # Bind korzenia zależy od istnienia ścieżki — testuj builderem z exists=True
    # (deterministycznie na każdym OS; tester bywa na Windows, gdzie /ws nie istnieje).
    st_bw = sandbox.linux_bwrap_argv(["echo", "hi"], st, root="/ws", bwrap="bwrap",
                                     exists=lambda p: True)
    check("wrap(linux): binds the root rw", "--bind" in st_bw and "/ws" in st_bw)

    no = sandbox.wrap(["echo", "hi"], st, root="/ws", platform="linux",
                      which=lambda n: None)
    check("wrap(linux): no bwrap on PATH -> no-op", no == ["echo", "hi"])

    wsp = sandbox.build_profile("workspace", root="/ws")
    bw = sandbox.linux_bwrap_argv(["ls"], wsp, root="/ws", bwrap="bwrap",
                                  exists=lambda p: True)
    check("wrap(linux): workspace ro-binds / (read-all)",
          "--ro-bind" in bw and "/" in bw)
    ssh = str(Path.home() / ".ssh")
    check("wrap(linux): sensitive path masked in bwrap argv", ssh in bw)
    check("wrap(linux): workspace keeps network (no --unshare-net)",
          "--unshare-net" not in bw)


def test_wrap_macos() -> None:
    st = sandbox.build_profile("strict", root="/ws")
    argv = sandbox.wrap(["echo", "hi"], st, root="/ws", platform="darwin")
    check("wrap(macos): sandbox-exec -p prefix",
          argv[0] == "sandbox-exec" and argv[1] == "-p")
    check("wrap(macos): original command preserved", argv[-2:] == ["echo", "hi"])

    sb = sandbox.seatbelt_profile(st)
    check("wrap(macos): seatbelt denies network (strict)", "(deny network*)" in sb)
    check("wrap(macos): seatbelt allows write to root",
          '(allow file-write* (subpath "/ws"))' in sb)
    check("wrap(macos): seatbelt denies sensitive paths",
          ".ssh" in sb and "(deny file*" in sb)
    check("wrap(macos): workspace allows read-all",
          "(allow file-read*)" in sandbox.seatbelt_profile(
              sandbox.build_profile("workspace", root="/ws")))


def test_wrap_noop() -> None:
    st = sandbox.build_profile("strict", root="/ws")
    check("wrap(windows): no-op (no FS sandbox)",
          sandbox.wrap(["echo", "hi"], st, root="/ws", platform="win32") == ["echo", "hi"])
    off = sandbox.build_profile("off", root="/ws")
    check("wrap(off): no-op even with launcher present",
          sandbox.wrap(["echo", "hi"], off, root="/ws", platform="linux",
                       which=lambda n: "/usr/bin/bwrap") == ["echo", "hi"])
    check("wrap: empty argv -> empty", sandbox.wrap([], st, root="/ws", platform="linux") == [])


def test_run_command_off_noop() -> None:
    """Profil off (domyślny) NIE zmienia run_command — komenda działa jak dotąd."""
    from caelo_core.agent.tools import run_command
    from caelo_core.agent.workspace import Workspace

    prev = getattr(config, "SANDBOX_PROFILE", "off")
    config.SANDBOX_PROFILE = "off"
    try:
        with tempfile.TemporaryDirectory() as d:
            ws = Workspace(d)
            out = run_command(ws, "echo sandbox_off_marker")
            check("run_command: off profile runs command normally",
                  "sandbox_off_marker" in out)
    finally:
        config.SANDBOX_PROFILE = prev


def main() -> int:
    test_profiles()
    test_resolve_config()
    test_wrap_linux()
    test_wrap_macos()
    test_wrap_noop()
    test_run_command_off_noop()

    print("\n=== sandbox OS self-check (M19-B7, no real exec) ===")
    ok = True
    for name, passed in checks:
        print(f"  [{'OK' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print(f"\n{'ALL PASSED' if ok else 'SOME FAILED'} ({sum(p for _, p in checks)}/{len(checks)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
