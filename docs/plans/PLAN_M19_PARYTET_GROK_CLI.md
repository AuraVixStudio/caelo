# PLAN_M19_PARYTET_GROK_CLI.md — Parytet z oficjalnym Grok CLI (xAI)

> Rozpis milestone'u **M19** z `PLAN_ROZBUDOWY.md` — wnioski z analizy **dystrybucji oficjalnego
> Grok CLI od xAI** (pliki dostarczone przez usera: `README.md` + `docs/user-guide/` + `bundled/` +
> `marketplace-cache/`). Cel: **podkraść warstwę „platformy agentowej"** z CLI tam, gdzie ma ją
> rozwiązaną lepiej (ACP, headless, LSP, reguły uprawnień, interop ekosystemu), **bez zdradzania
> tożsamości produktu** — Caelo zostaje **hubem GUI all-in-one** (czat+image+video+voice+code),
> a CLI to wyłącznie narzędzie terminalowe/IDE bez multimodalności.
>
> **Zakłada gotowe:** M10 (`responses_client`), M13 (diffy/plan/checkpointy/CAELO.md), M14 (MCP/skille/
> komendy/hooki), M16 (marketplace `.caelopkg`), M17 (subagenci + role + worktree + `TeamManager`),
> M18 (dekompozycja `state.py`/`auth_tokens.py`, pytest, testy frontu).
>
> Tagi: **[P0]** krytyczne · **[P1]** wysoka wartość · **[P2]** dobre · **[P3]** nisza/quick-win.
> Wysiłek: **S** ≈ dni · **M** ≈ 1–2 tyg. · **L** ≈ 3–4 tyg.
>
> **STATUS (2026-06-07): ✅ Tier-1 + Tier-2 + Tier-3 KOMPLETNE** (na stubie/mocku, selfchecki zielone);
> pozostają **weryfikacje LIVE u usera** (sandbox blokuje sieć/xAI) i **spike B0** (`cli-chat-proxy`,
> §7 — nie zaczęty). Weryfikacja luk względem repo (§2). Rozpisy: §4 (Tier-1), §5 (Tier-2),
> [`§6/PLAN_M19_TIER3.md`](PLAN_M19_TIER3.md) (Tier-3), §7 (spike B0).

---

## 0. Źródło, metoda, kluczowy fakt

**Co przeanalizowano:** kompletna dystrybucja `grok` CLI (instalacja `curl -fsSL https://x.ai/cli/install.sh`,
dane w `~/.grok/`). 2580-liniowy `README.md`, 22 dokumenty `docs/user-guide/`, bundlowane role/persony/
agenci/skille (`bundled/manifest.json` z sumami SHA-256), cache marketplace (37 wtyczek oficjalnych +
15 zewnętrznych).

**Kluczowy fakt:** **Grok CLI to technicznie fork Claude Code.** Dowody: `marketplace.json` odwołuje się
do schematu `anthropic.com/claude-code/marketplace.schema.json` i nazywa się `claude-plugins-official`;
jest sekcja „Claude Code Compatibility" (czyta `.claude/`, `~/.claude.json`, `CLAUDE.md`, `.mcp.json`);
bundlowane skille to dosłownie skille Anthropica (`docx`/`pptx`/`xlsx`/`create-skill`/`best-of-n`/
`check-work`). **Konsekwencja strategiczna:** każda konwencja zaadaptowana z tych plików daje
**podwójną zgodność z ekosystemem** (Grok CLI *i* Claude Code) za jedną pracę.

**Czego CLI NIE ma (nasz moat — nie zgubić):** Image/Video (`GenJob`), Voice (TTS/STT/realtime/Talk),
GUI (wizualne diffy, galerie, liczniki kosztów, panel wiedzy projektu, motywy). To jest produkt;
warstwa agenta to tylko jeden z pięciu trybów.

---

## 1. Filozofia: co adoptujemy, czego świadomie nie

| Adoptujemy (CLI ma lepiej) | Świadomie NIE adoptujemy |
|---|---|
| ACP/headless (wejście dla IDE i skryptów) | **Multi-provider / Ollama / OpenAI-compat** — zasada „tylko Grok" (CLAUDE.md), jedyna abstrakcja to cienka warstwa endpoint/auth |
| LSP (diagnostyka + tool) | Telemetria/Mixpanel/trace-upload — OSS desktop, prywatność > analityka |
| Reguły uprawnień jako globy | OIDC/SSO korporacyjne — nie nasz odbiorca (BYO-key power-user) |
| Interop `AGENTS.md`/`.claude`/`.mcp.json` | TUI terminalowe — mamy GUI |
| Skille-orkiestratory na subagentach | SSH passthrough / leader mode / computer hub — nisza |
| Pamięć hybrydowa (FTS5 + wektory) | |

---

## 2. Wynik weryfikacji repo (stan na 2026-06-06)

Każda luka potwierdzona w kodzie — punkty styku gotowe do rozpisu:

| Funkcja | Stan w Caelo | Dowód / punkt styku |
|---|---|---|
| Tryb headless / CLI | **brak** — `__main__.py` to wyłącznie launcher uvicorn | [`__main__.py:41`](../caelo_core/__main__.py) |
| ACP (stdio JSON-RPC) | **brak** — „stdio" tylko w kliencie MCP | `caelo_core/mcp/client.py` |
| LSP | **brak** — tylko wzmianki w komentarzach | `caelo_core/agent/caelomd.py:1` |
| Reguły uprawnień (globy) | **brak** — allowlista per znormalizowana **pełna komenda** (`cmd:<...>` / `tool:<name>:<path>` / `mcp:<qname>`) | `agent/permissions.py` `_key`/`allow`/`allow_key`/`needs_approval` |
| `--effort` / reasoning_effort | **brak** | `responses_client.py`, `agent/llm.py`, `session.py` — 0 trafień |
| web tools w agencie | **brak** (czat ma `web_search`/`x_search` przez Responses; agent — nie) | `caelo_core/agent/` — 0 trafień |
| Interop `AGENTS.md`/`.claude`/`.mcp.json` | **brak** — tylko własny `CAELO.md`/`caelo_*.json` | `agent/caelomd.py` |
| Pamięć wektorowa | **brak** — tylko FTS5; `vector_store_id` to martwy relikt (xAI `/v1/vector_stores` → 404) | [`history_store.py:105`](../caelo_core/history_store.py) |
| Eksport sesji do markdown | **brak** | 0 trafień |
| Skille-orkiestratory (`implement`/`design`/`review`/`best-of-n`) | **brak** — jest silnik `TeamManager`, brak gotowych pętli | `agent/team.py`, `agent/roles.py` |
| Persony (instrukcje + I/O schema) | **częściowo** — role łączą capability+tools, brak warstwy persony + schematu I/O | `agent/roles.py` `RoleRegistry` |
| Config projektowy hierarchiczny | **częściowo** — głównie `DATA_DIR` centralny | `config.py` |
| Realne `git worktree` | **brak** — kopie plików (M17) | `agent/worktree.py` |

**Już mamy parytet (nie ruszać):** MCP stdio (M14), skille/komendy/hooki (M14), subagenci+role+worktree
(M17), marketplace (M16), checkpointy/undo + tryby `ask`/`accept-edits`/`plan`/`bypass` (M13),
`web_search`/`x_search`/wizja/`input_file` w czacie (M10), bezpieczeństwo fail-closed + `WsStream` +
scrubbed env + tree-kill + atomic writes + CSP + `sandbox:true`.

---

## 3. Roadmap priorytetowy

**Tier 1 — ✅ KOMPLETNY (2026-06-06; rozpis + status: [`PLAN_M19_TIER1.md`](PLAN_M19_TIER1.md)):**
1. **B1 [P1] Headless/CLI sidecara** — M. Fundament pod CI/skrypty i pod ACP.
2. **B2 [P1] ACP stdio** — M–L. Wejście do Zed/Neovim/Emacs/JetBrains.
3. **B3 [P1] LSP w trybie Code** — L. Największy „table-stake" jakości agenta + edytora.
4. **B4 [P1] Reguły uprawnień jako globy** — S–M. Bezpieczniej i zgodnie z ekosystemem.

**Tier 2 — mocne, średni nakład:**
5. **B5 [P2] Interop ekosystemu** (`AGENTS.md`/`CLAUDE.md`/`.mcp.json`/`.claude/skills`) — M.
6. **B6 [P2] Skille-orkiestratory na M17** (`implement`/`design`/`review`/`best-of-n`/`check-work`) — M.
7. **B7 [P2] Sandbox OS-kernel** (Landlock/Seatbelt, profile) — L.
8. **B8 [P2] Pamięć hybrydowa** (FTS5 + embeddingi + wstrzyknięcie na 1. turze) — M.

**Tier 3 — ✅ KOMPLETNY (2026-06-07; rozpis + status: [`PLAN_M19_TIER3.md`](PLAN_M19_TIER3.md)):**
9. **B9 [P3]** poziomy `--effort` per tryb/agent — S. ✅
10. **B10 [P3]** eksport sesji do markdown + auto-compact progu kontekstu — S. ✅ (`web_search`-analog
    import md odłożony; eksport hub+czat+headless gotowy)
11. **B11 [P3]** persony + I/O schema dla subagentów — S–M. ✅
12. **B12 [P3]** opcja realnych `git worktree` — S. ✅
13. **B13 [P3]** `web_fetch` w agencie (allowlista domen) — S. ✅ (`web_search` świadomie odłożony)
14. **B14 [P3]** config projektowy hierarchiczny `.grok/`/`.caelo/` (cwd→root) — M. ✅

**Spike (osobno, wysokie ryzyko/wysoki zwrot):** **B0 [P1] `cli-chat-proxy.grok.com`** (§7).

---

## 4. Tier-1 — rozpisy szczegółowe

> **Pełny plan implementacyjny Tier-1** (konkretne pliki, sygnatury, ramki, kroki, selfchecki, sekwencja)
> żyje w osobnym dokumencie: [`PLAN_M19_TIER1.md`](PLAN_M19_TIER1.md). Poniżej skrót; szczegóły tam.

### B0/B1 [P1] Tryb headless / CLI sidecara — **M**

**Cel:** uruchamianie agenta bez GUI: `python -m caelo_core run -p "..." --output-format json|streaming-json`,
nazwane sesje (`-s/--session-id`, `-c/--continue`), allow/deny narzędzi, limity (`--max-turns`).
Odblokowuje CI, pre-commit hooki, skrypty — i jest wymaganym fundamentem pod ACP (B2).

**Punkty styku:**
- [`caelo_core/__main__.py`](../caelo_core/__main__.py) — dziś tylko `main()` → uvicorn. Dodać **subkomendy**
  (np. `argparse`/`sys.argv[1]`): brak argumentów = serwer (zachowanie domyślne, NIE regresować handshake),
  `run` = headless. Logi nadal na **stderr**; stdout zarezerwowany — w headless stdout = strumień
  zdarzeń, nie handshake.
- `caelo_core/agent/session.py` — reużyj pętli z opcjami `tool_names`/`delegate_fn`/`extra_system`/`on_turn`
  (dodane w M17). Headless = ta sama pętla, inny „transport" zamiast `WsStream`.
- Nowy `caelo_core/headless.py` — adapter: `on_turn`/callbacki → linie JSON na stdout
  (`{"type":"text","data":...}` / `thought` / `tool_call` / `{"type":"end","stopReason":...,"sessionId":...}`).
  **Mirror formatu CLI** (streaming-json) → darmowa zgodność z ich przykładami integracji.
- Uprawnienia: w headless brak interaktywnej karty → tryb `--permission-mode` (`ask` niemożliwy bez UI;
  mapuj na `bypass`/`accept-edits`/`plan` z M13) + reguły allow/deny (zob. B4). Domyślnie **fail-closed**:
  bez `--always-approve`/reguł mutacje są blokowane, nie auto-akceptowane.

**Kroki:**
1. Subkomendy w `__main__.py` (`serve` domyślne, `run` headless) — guard: brak args = stary handshake.
2. `headless.py`: parsowanie flag (`-p`, `-m`, `-s`, `-c`, `--output-format`, `--max-turns`,
   `--tools`/`--disallowed-tools`, `--permission-mode`, `--cwd`), spięcie z `session.py`.
3. Reużycie sesji: zapisuj/wczytuj historię (na razie z istniejącego magazynu; pełne sesje → B w Tier-3).
4. Selfcheck `caelo_core/tools/headless_check.py` (mock LLM): plain/json/streaming-json, `--tools` zawęża,
   `--disallowed-tools` usuwa, fail-closed bez approve. Wpiąć w pytest (`caelo_core/tests/`).

**Ryzyka:** kolizja stdout (handshake vs strumień) — rozwiązane przez rozłączne subkomendy.
**Weryfikacja:** `headless_check` + ręcznie `python -m caelo_core run -p "..." --output-format json`.

---

### B2 [P1] Tryb ACP (Agent Client Protocol) stdio — **M–L**

**Cel:** wystawić agenta jako serwer **ACP** (`agentclientprotocol.com`) po stdio (JSON-RPC 2.0) →
natychmiastowa integracja z Zed, Neovim (CodeCompanion/avante), Emacs, marimo, wkrótce JetBrains.
To zamienia silnik Caelo w **backend dla dowolnego edytora ACP**, nie tylko własnego GUI.

**Dlaczego tani(o):** `session.py` jest już event-driven; ramki, które emitujesz na `WsStream`
(`text`/`thought`/`tool_call`/`citations`/`usage`/`checkpoint`/`subagent`…), mapują się ~1:1 na
notyfikacje ACP `session/update` (`agent_message_chunk`/`agent_thought_chunk`/`tool_call`/`plan`).

**Protokół (z README CLI):** `initialize` (`protocolVersion`, `clientCapabilities.fs`/`terminal`) →
`session/new` (`cwd`, `mcpServers`) → `session/prompt` (`{sessionId, prompt:[{type:text,text}]}`) →
strumień notyfikacji → finalny `result` (`text`, `stopReason`). Dodatkowo `session/load`.

**Punkty styku:**
- `__main__.py` — subkomenda `acp` (po B1: `serve`/`run`/`acp`).
- Nowy `caelo_core/acp/` — `server.py` (pętla JSON-RPC po stdin/stdout, newline-delimited — wzór:
  istniejący `mcp/client.py`, ale **strona serwera**), `bridge.py` (ramki silnika → `session/update`).
- `routes/_ws.py` `WsStream` — **nie używać** dla ACP (to transport po stdio, nie WS); ale **wspólny
  producent zdarzeń** z `session.py` powinien być reużyty (jedna funkcja emitująca, dwa transporty).
  Rozważyć ekstrakcję „event emitter" wspólnego dla WS i ACP, by poprawki nie dryfowały (zasada M5–M6).
- Uprawnienia ACP: klient ACP może obsłużyć karty zgody (request/response) — zmapować `approval_request`
  na ACP permission flow; gdy klient nie wspiera → `--permission-mode` jak w headless.

**Kroki:**
1. Szkielet JSON-RPC server (stdio, UTF-8, logi na stderr).
2. `initialize`/`session/new`/`session/prompt`/`session/load` → spięcie z `session.py`.
3. `bridge.py`: ramki → `session/update` (agent_message/thought/tool_call/plan).
4. Mapowanie zgody (interaktywna karta ↔ ACP permissions).
5. Selfcheck `acp_check.py` (mock klient ACP po potoku): handshake protokołu, prompt→strumień→result,
   tool_call notyfikacje, zła wersja protokołu odrzucona. Pytest.

**Ryzyka:** poprawna kolejność/format ACP (wersja „1"); double-source zdarzeń (WS vs ACP) — mitigacja:
wspólny emitter. **Weryfikacja na żywo:** podpięcie do Zed/Neovim na maszynie usera (sandbox blokuje xAI).

---

### B3 [P1] LSP w trybie Code (diagnostyka + narzędzie `lsp`) — **L**

**Cel:** świadomość języka dla agenta i edytora. Dwa tryby (jak CLI): **pasywna diagnostyka po edycie**
(po `write_file`/`edit_file` pokaż błędy/ostrzeżenia z language servera) + **narzędzie `lsp`**
(`goToDefinition`/`findReferences`/`hover`/`goToImplementation`/`documentSymbol`/`workspaceSymbol`).

**Punkty styku:**
- Konfiguracja: nowy `lsp.json` (per workspace `<ws>/.caelo/lsp.json` + globalny `DATA_DIR`), schema jak
  CLI (`command`/`args`/`extensionToLanguage`/`transport`/`env`/`startupTimeout`/`restartOnCrash`/
  `maxRestarts`). Czytać przez `config.load_json_or_backup` (P1-11).
- Nowy `caelo_core/lsp/` — `client.py` (JSON-RPC LSP po stdio, długożyjący proces serwera, **scrubbed
  env** + **tree-kill** na shutdown jak MCP w M14), `manager.py` (rejestr per rozszerzenie, restart-on-crash).
- `agent/tools.py` — narzędzie `lsp` (READONLY → bez bramki; dodać do `READONLY` w `permissions.py`).
- `agent/session.py` — po mutującej edycji odpal pasywną diagnostykę → nowa ramka WS `diagnostics`.
- Frontend: CodeEditor (`components/code/CodeEditor.tsx`, CodeMirror 6) — podświetlanie diagnostyki inline
  (CM6 `lintGutter`/`diagnostics`), opcjonalnie go-to-definition.
- Subagenci (M17): współdziel runtime LSP rodzica dla tego samego workspace (jak robi CLI — nie startuj
  duplikatu puli serwerów per subagent).

**Kroki:**
1. `lsp/client.py` — minimalny LSP klient (`initialize`/`textDocument/didOpen`/`didChange`/
   `publishDiagnostics`/`definition`/`references`/`hover`/`documentSymbol`).
2. `lsp/manager.py` — discovery z `lsp.json`, lifecycle, restart-on-crash, tree-kill w `backend.shutdown()`.
3. Pasywna diagnostyka po edycie → ramka `diagnostics`.
4. Narzędzie `lsp` dla agenta (gated wyłączeniem, jak CLI: ukryte gdy brak konfiguracji, by model nie
   planował wokół niedostępnej zdolności).
5. UI: diagnostyka w CodeEditor; toggle w ustawieniach (`lsp_enabled`).
6. Selfcheck `lsp_check.py` (mock LSP server po potoku, wzór `_mcp_mock_server.py`).

**Ryzyka:** Caelo NIE bundluje binarek serwerów (jak CLI — user instaluje `pyright`/`typescript-language-server`
sam; dokumentować). Wydajność/stabilność długożyjących procesów. **Wysiłek L** — największy z Tier-1.

---

### B4 [P1] Reguły uprawnień jako globy (`ToolPrefix(glob)`) — **S–M**

**Cel:** czytelniejszy, bezpieczniejszy i **zgodny z ekosystemem** model zgody. Składnia CLI/Claude Code:
`Bash(npm*)`, `Edit(src/**)`, `Write(...)`, `Read(...)`, `Grep(...)`, `WebFetch(domain:docs.rs)`,
`MCPTool(...)`; `*`=jeden poziom, `**`=rekursywnie; **deny > allow**; goły prefiks = wszystkie wywołania.

**Punkty styku:**
- [`agent/permissions.py`](../caelo_core/agent/permissions.py) — `PermissionGate`. Dziś: allowlista per
  znormalizowana pełna komenda (`_key`). **Dodać warstwę reguł** (allow/deny listy wzorców) **obok**
  istniejącej allowlisty „Always allow" (kompatybilność wstecz: stare klucze nadal działają).
  - Mapowanie narzędzie→prefiks: `run_command`→`Bash`, `write_file`→`Write`+`Edit`, `read_file`→`Read`,
    `grep`→`Grep`, MCP→`MCPTool`.
  - `needs_approval`: najpierw **deny** (jeśli pasuje → odmowa twarda), potem **allow** (auto), potem
    istniejąca allowlista, na końcu → pytaj. **Zachować P0-1**: reguła `Bash(...)` NIE może obejść
    `command_metachars` (komenda z metaznakami nadal niekluczowalna/zawsze-pytaj, nawet jeśli pasuje do globu —
    albo jawnie: deny ma pierwszeństwo, ale allow nie autoryzuje łańcuchowania).
  - `fnmatch`/własny matcher dla `*` vs `**` (uwaga: `fnmatch` traktuje `*` rekursywnie — potrzebny
    matcher rozróżniający, jak w CLI).
- Wejścia reguł: flagi headless `--allow`/`--deny` (B1), pole w `caelo_settings.json` (globalne),
  `<ws>/.caelo/permissions.toml` (projektowe), panel **Permissions** w UI (M14) — dodać edytor reguł.
- `routes/permissions.py` + `state` — reguły obok allowlisty; **fail-closed** bez zmian.

**Kroki:**
1. Parser reguł `ToolPrefix(glob)` + matcher `*`/`**` (+ `domain:` dla WebFetch).
2. Integracja w `needs_approval`/`needs_approval_key` (deny>allow>allowlista>pytaj), z zachowaniem P0-1.
3. Wejścia: flagi (B1), settings, plik projektowy, UI panel.
4. Selfcheck w `agent_selfcheck.py`: deny>allow, `**` vs `*`, metaznaki nie przechodzą przez `Bash(...)`,
   `MCPTool(...)`, `WebFetch(domain:...)`. (Dorzucić do ~166 asercji M17.)

**Ryzyka:** subtelność glob (`*` vs `**`), kolizja z istniejącą allowlistą — mitigacja: reguły to
**dodatkowa warstwa**, nie zamiennik; testy regresji P0-1.

---

## 5. Tier-2 — rozpisy skrócone

> **Pełny plan implementacyjny Tier-2** (punkty styku w kodzie, kroki, selfchecki, sekwencja, spike'i)
> żyje w osobnym dokumencie: [`PLAN_M19_TIER2.md`](PLAN_M19_TIER2.md). Poniżej skrót; szczegóły tam.

### B5 [P2] Interop ekosystemu (Claude Code / Grok CLI) — **M**
**Cel:** istniejące projekty „po prostu działają" + dostęp do ekosystemu wtyczek (format = schema Anthropica).
- **Reguły projektu hierarchicznie:** obok `CAELO.md` (M13) wykrywaj `AGENTS.md`/`AGENT.md`/`CLAUDE.md`/
  `Agents.md` od korzenia repo → cwd (deeper wins), cap ~10k znaków/plik (jak CLI). Punkt: `agent/caelomd.py`
  (rozszerzyć discovery), spięcie w system prompcie `session.py`.
- **MCP z `.mcp.json` / `~/.claude.json`:** czytaj obok `caelo_mcp.json`. Punkt: `caelo_core/mcp/manager.py`.
- **Skille z `~/.claude/skills/` / `.claude/skills/`:** dołącz do discovery. Punkt: `caelo_core/skills/`.
- **Uwaga UI-language (CLAUDE.md):** discovery to logika, nie tekst UI — OK.

### B6 [P2] Skille-orkiestratory na silniku M17 — **M**
**Cel:** „killer feature" subagentów — wbudowane pętle wieloagentowe (CLI bundluje je jako skille).
Zbuduj na `agent/team.py` (`TeamManager`) + `roles.py`:
- `implement` — pętla implement→review→fix, multi-reviewer, „effort" 1–5 (liczba rund/recenzentów).
- `design` — write→review loop design-doca aż do 0 uwag.
- `review` — pojedynczy recenzent lokalnych zmian/brancha/PR.
- `best-of-n` — uruchom zadanie N-krotnie równolegle, wybierz najlepsze (Twój semafor `max_parallel`).
- `check-work` — weryfikacja implementacji względem kryteriów akceptacji.
- `pr-babysit` — pilnowanie PR przez cykl recenzji (wymaga GitHub MCP/`gh`).
Format: pakiety `SKILL.md` (jak M14), ale treść = orkiestracja delegacji. Punkt: `caelo_core/skills/builtin/`.
Selfcheck: rozszerz `agent_selfcheck.py` (mock delegacji).

### B7 [P2] Sandbox OS-kernel — **L**
**Cel:** wzmocnić istniejącą fosę (dziś: `Workspace.resolve` + scrubbed env + `sandbox:true` Electron).
Dodać izolację **procesów potomnych** `run_command`/MCP/LSP kernelowo: **Landlock** (Linux ≥5.13),
**Seatbelt** (macOS); na Windows — best-effort/dokumentacja braku. Profile jak CLI: `workspace`/`read-only`/
`strict` + `sandbox.toml` (`extends`/`read_only`/`read_write`/`deny`/`restrict_network`). Ścieżki wrażliwe
(`~/.ssh`, `~/.aws`, `auth.json`) zawsze chronione. Zgodne z kierunkiem **M15 cross-platform**. Log zdarzeń
do `sandbox-events.jsonl`. **Uwaga:** sieci in-process (LLM API) nie da się zablokować — tylko procesy potomne.

### B8 [P2] Pamięć hybrydowa (FTS5 + wektory) — **M**
**Cel:** semantyczny recall ponad obecny `history_store` (FTS5). Dodać embeddingi + KNN, wstrzyknięcie na
1. turze sesji (jak CLI). Punkt: `history_store.py`. **Otwarte:** xAI nie ma serwerowych vector stores
(potwierdzone, `/v1/vector_stores`→404) — embeddingi przez endpoint embeddings xAI **jeśli istnieje**,
inaczej lokalnie (np. `sqlite-vec`/lokalny model) — **zbadać dostępność `embedding-*` u xAI** (CLI używa
`embedding-beta-3-small`, 1024 wymiarów — sugeruje, że istnieje). Bez nowych ciężkich zależności (CLAUDE.md).

---

## 6. Tier-3 — quick-winy

> **Pełny plan implementacyjny Tier-3** (punkty styku w kodzie, sygnatury, kroki, selfchecki,
> sekwencja, decyzje) żyje w osobnym dokumencie: [`PLAN_M19_TIER3.md`](PLAN_M19_TIER3.md). Poniżej
> skrót; szczegóły tam. Numeracja B9–B14 (kontynuacja serii B z Tier-1/Tier-2).

- **[P3] Poziomy effort (S):** `reasoning_effort` (low/medium/high) → param w `responses_client.stream_response`
  i per-rola w `roles.py`; UI: selektor w trybach. xAI Responses wspiera `reasoning.effort` — zweryfikować pole.
- **[P3] Eksport/import sesji do markdown (S):** `grok export`-odpowiednik; serializacja historii czatu/agenta
  do `.md`. Punkt: `routes/history.py` + przycisk UI.
- **[P3] Persony + I/O schema (S–M):** warstwa nad rolami M17 — `instructions` + `[[inputs]]`/`[[outputs]]`
  (jak `bundled/personas/*.toml`). Punkt: `roles.py` (`RoleRegistry`).
- **[P3] Realne `git worktree` (S):** opcja obok kopii plików M17 (wydajniejsze, wymaga repo). Punkt:
  `agent/worktree.py`. (Już zapisane jako otwarte pytanie w PLAN_M17 §5.)
- **[P3] Web tools w agencie (S):** `web_fetch`/`web_search` dla agenta (czat już ma w Responses) z allowlistą
  domen + bramka. Punkt: `agent/tools.py` + `permissions.py` (`WebFetch(...)`).
- **[P3] Config projektowy hierarchiczny (M):** `.caelo/config.*` walked cwd→root (MCP/LSP/skille per projekt).

---

## 7. Spike B0 [P1] — `cli-chat-proxy.grok.com` (osobno, wysokie ryzyko/wysoki zwrot)

**Hipoteza (potencjalnie największa wartość dla OSS BYO-key):** CLI po `grok login` (przeglądarka,
**subskrypcja grok.com / SuperGrok**) uderza w `https://cli-chat-proxy.grok.com/v1/chat/completions`
z nagłówkami:
```
Authorization: Bearer <token z ~/.grok/auth.json>
X-XAI-Token-Auth: xai-grok-cli
x-grok-model-override: grok-build
```
To **nie jest** metered billing z `api.x.ai` — to inferencja w ramach **subskrypcji**. Dla aplikacji
BYO-key oznaczałoby to korzystanie **bez klucza API i bez kosztów per-token** dla userów z SuperGrok.

**Stan Caelo:** `config.py` już ma scope OAuth `grok-cli:access` i model `grok-build-0.1`, ale celuje w
`API_BASE = https://api.x.ai/v1`. Jesteś w połowie drogi.

**Spike (na maszynie usera — sandbox blokuje xAI):**
1. Sprawdź, czy token z Twojego OAuth `auth.x.ai` jest akceptowany przez `cli-chat-proxy.grok.com` z tymi
   nagłówkami (różne audience? token z `auth.x.ai` vs `accounts.x.ai` z CLI — zweryfikować).
2. Sprawdź modele dostępne tą ścieżką (`grok-build` i in.) i ograniczenia (tylko streaming?).
3. Zmierz, czy narzędzia serwerowe (`web_search`/`x_search`) działają na tej ścieżce, czy tylko czysty czat.

**Jeśli działa:** dodaj **drugą ścieżkę inferencji** za cienką warstwą endpoint/auth (NIE restrukturyzując
root `api_manager.py` — zasada CLAUDE.md): „Login with grok.com" jako alternatywa dla klucza API.
**Ryzyko:** niedokumentowane, ToS, może paść server-side bez ostrzeżenia (jak cały OAuth) — trzymać za
feature-flagą i jako opcję, nie domyślną ścieżkę. **To research, nie commitment.**

---

## 8. Ograniczenia projektowe do uszanowania (z CLAUDE.md)

- **NIE ruszać root-modułów** (`config.py`, `api_manager.py`, `oauth_manager.py`, …) — nowy kod w `caelo_core/`.
  Ścieżki inferencji (B0) i nowe klienty (ACP/LSP) to cienkie warstwy, nie restrukturyzacja rdzenia.
- **Tylko Grok** — brak warstwy multi-provider (B7/B8 nie wprowadzają OpenAI/Ollama; embeddingi z xAI lub lokalne).
- **Fail-closed** REST+WS; nowe transporty (headless/ACP) domyślnie blokują mutacje bez jawnej zgody.
- **stdout święty** — handshake (serwer) i strumień ACP/headless to rozłączne subkomendy; logi zawsze na stderr.
- **UTF-8** w każdym streamingu (ACP/LSP po stdio: jawne UTF-8, jak `responses_client`/MCP).
- **Tekst UI po angielsku**; komentarze/docstringi mogą zostać po polsku.
- **Bez nowych ciężkich zależności** — ACP/LSP jako własne cienkie warstwy JSON-RPC (jak klient MCP w M14).
- **Reużyj wspólnych helperów** — `config.load_json_or_backup`, `atomic_write_text`, `scrubbed_env`,
  `_tree_kill`, wspólny producent zdarzeń silnika (WS↔ACP).

---

## 9. Otwarte pytania techniczne

- **Wspólny emitter zdarzeń WS↔ACP↔headless:** wyodrębnić jeden producent w `session.py`, by 3 transporty
  nie dryfowały (zasada „jeden szkielet" z M5–M6)? Rekomendacja: **tak**, przed B2.
- **Sesje headless:** reużyć magazyn historii czy zaprojektować layout sesji jak CLI
  (`sessions/<encoded-cwd>/<id>/{summary.json,updates.jsonl,...}`)? Layout CLI = darmowa zgodność, ale więcej pracy.
- **Embeddingi (B8):** czy xAI wystawia endpoint embeddings (`embedding-beta-3-small`)? Jeśli nie — lokalny
  model bez nowej ciężkiej zależności?
- **LSP a subagenci:** współdzielenie runtime rodzica (jak CLI) vs osobne pule — rekomendacja: współdzielić.
- **B0 audience tokenu:** `auth.x.ai` (Caelo) vs `accounts.x.ai` (CLI) — czy ten sam token przejdzie na proxy?
- **Reguły glob vs allowlista komend:** docelowo zastąpić allowlistę regułami, czy trzymać obie warstwy?
  Rekomendacja: **obie** (wstecz-kompatybilność), reguły jako nadrzędna warstwa.

---

*Dokument utrzymywany w `docs/PLAN_M19_PARYTET_GROK_CLI.md`. Aktualizować przy realizacji (status w §0).
Źródło analizy: dystrybucja oficjalnego Grok CLI (xAI) — folder „PLIKI Z GROK BUILD", maj 2026.*
