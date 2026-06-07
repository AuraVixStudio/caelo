"""Sandbox OS-kernel (M19-B7) — dodatkowa warstwa izolacji procesów potomnych.

DODATEK do istniejącej fosy (`Workspace.resolve` + `tools.scrubbed_env` + tree-kill),
NIE zamiennik. Off-by-default (`config.SANDBOX_PROFILE`); `off` nie zmienia zachowania.
Wpięte w `tools.run_command` oraz spawn MCP/LSP przez wspólny `wrap_command`.
"""

from __future__ import annotations

from caelo_core.sandbox.profiles import (
    VALID_PROFILES,
    Profile,
    build_profile,
    resolve_profile,
    sensitive_paths,
)
from caelo_core.sandbox.wrap import (
    linux_bwrap_argv,
    log_event,
    seatbelt_profile,
    wrap,
    wrap_command,
)

__all__ = [
    "VALID_PROFILES", "Profile", "build_profile", "resolve_profile", "sensitive_paths",
    "wrap", "wrap_command", "linux_bwrap_argv", "seatbelt_profile", "log_event",
]
