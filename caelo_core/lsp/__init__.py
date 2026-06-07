"""Integracja LSP (Language Server Protocol) — M19-B3.

Pasywna diagnostyka po edycie + narzędzie `lsp` (definition/references/hover/symbols)
dla agenta kodowania. Klient mówi po stdio z **ramkowaniem Content-Length** (NIE
newline-delimited jak MCP). Serwery są twardo-hartowane jak `run_command`/MCP
(scrubbed env + tree-kill). Caelo NIE bundluje binarek serwerów — user instaluje je sam.
"""
