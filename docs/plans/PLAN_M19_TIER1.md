# PLAN_M19_TIER1.md — Pełny plan implementacyjny Tier-1

> Rozwinięcie §4 z [`PLAN_M19_PARYTET_GROK_CLI.md`](PLAN_M19_PARYTET_GROK_CLI.md) do poziomu
> implementacyjnego (konkretne pliki, sygnatury, ramki, kroki, selfchecki, akceptacja). Cztery
> elementy: **B1 headless/CLI · B2 ACP stdio · B3 LSP · B4 reguły uprawnień jako globy**, poprzedzone
> **§0 wspólnym fundamentem** (refaktor bez zmiany zachowania).
>
> **Zakłada gotowe:** M13 (tryby/checkpointy/CAELO.md), M14 (MCP/hooki/skille), M17 (subagenci/`TeamManager`),
> M18 (`auth_tokens.py`, pytest). **Punkt zaczepienia:** `AgentSession` (caelo_core/agent/session.py)
> przyjmuje wstrzykiwane `emit`/`request_approval` — `routes/agent.py` to wzorcowe okablowanie.
>
> **STATUS (2026-06-06): ✅ TIER-1 KOMPLETNY — §0 ✅ + B4 ✅ + B1 ✅ + B2 ✅ + B3 ✅ ZROBIONE.**
> (B3: editor squiggles odłożone — diagnostyka w panelu agenta; szczegóły w §3.) Tagi [P0]/[P1]/[P2].

---

## 0. ✅ Wspólny fundament — `AgentRunner` (ZROBIONE 2026-06-06) — **[P0] S–M**

**Problem:** logika budowy `AgentSession` (z checkpoints/mcp/hooks/skills/delegate + `TeamManager`) żyje
dziś **wyłącznie w handlerze WS** [`routes/agent.py:127-171`](../caelo_core/routes/agent.py). Headless (B1)
i ACP (B2) potrzebują dokładnie tego samego okablowania, ale z innym `emit`/`request_approval`. Kopiowanie
= dryf (dokładnie ten błąd, którego unika `WsStream`, M5–M6).

**Rozwiązanie:** wydziel **transport-neutralny runner**.

**Nowy plik `caelo_core/agent/runner.py`:**
```python
class AgentRunner:
    """Buduje i prowadzi AgentSession dla DOWOLNEGO transportu (WS/headless/ACP).
    Transport dostarcza: emit(dict), request_approval(id,name,detail)->str, stop()->bool.
    Reużywa Backend (checkpoints/mcp/hooks/skills/subagenci) — jedno źródło okablowania."""
    def __init__(self, backend, *, emit, request_approval, stop):
        self.backend = backend
        self.emit = emit; self.request_approval = request_approval; self.stop = stop
        self._session = None; self._team = None
        self._model = ""; self._mode = "ask"

    def _delegate_fn(self, tasks: list) -> str: ...   # przenieś z routes/agent.py:119-125
    def _get_team(self): ...                           # przenieś z routes/agent.py:102-117
    def run_turn(self, text, model, *, images=None, mode="ask", max_iters=None) -> str:
        # przenieś ciało run_turn z routes/agent.py:127-171 (bez warstwy WS):
        #   leniwe AgentSession(...), zapamiętaj model/mode (delegate), session.run_turn(...),
        #   record_event(mode="code", ...). Zwróć last_assistant.
```

**Refaktor `routes/agent.py`:** handler WS tworzy `AgentRunner(backend, emit=emit,
request_approval=request_approval, stop=stop_event.is_set)` i woła `runner.run_turn(...)` zamiast
lokalnych `run_turn`/`delegate_fn`/`get_team`. **Zachowanie identyczne** — `state["busy"]`, `pending`,
ramki, `done` zostają w handlerze WS (to warstwa transportu). `emit`/`request_approval`/`stop_event`
bez zmian.

**Kryterium:** `api_smoke` + `agent_selfcheck` (166) **zielone bez zmian w asercjach** — to refaktor
zachowawczy. Dopiero potem B1/B2 dokładają nowe transporty.

> **Decyzja (otwarte pytanie §9 z M19):** TAK, wspólny producent zdarzeń. `AgentRunner` jest tym
> producentem; trzy transporty (`WsStream.emit` / stdout-JSON / ACP-notify) różnią się tylko `emit`.

**✅ Realizacja (2026-06-06):**
- Nowy [`caelo_core/agent/runner.py`](../caelo_core/agent/runner.py) `AgentRunner` — przeniesione z handlera
  WS: leniwa `AgentSession`, leniwy `TeamManager`, `_delegate_fn`, zapis tury (M9-B2). `emit` runnera
  opakowuje `emit` transportu i łapie `assistant_done` najwyższego poziomu (`last_assistant`).
- [`routes/agent.py`](../caelo_core/routes/agent.py) przepięte: handler zostawia tylko transport
  (`emit`=`stream.emit`+stop, `request_approval`+`pending`, flaga `busy`, `stop_event.clear()`, ramka
  `done`) i woła `runner.run_turn(...)`. Usunięte z trasy: `import config`, `AgentSession`,
  `stream_chat_with_tools`, `get_team`/`delegate_fn`/klucze `state` (session/team/model/mode/last_assistant).
- **Drobna, nieistotna różnica:** `stop_event.clear()` jest teraz przed sprawdzeniem workspace (gdy brak
  workspace flaga się czyści) — bez efektu obserwowalnego (nie biegnie żadna tura; kolejna i tak czyści).
- **Weryfikacja:** `agent_selfcheck` **166 → OK (bez zmian asercji)**; `api_smoke` **OK** (w tym
  fail-closed `/agent/stream`); import + `create_app` OK; bezpośredni test runnera (mock LLM + atrapa
  backendu): `text`/`assistant_done` emitowane, `last_assistant` złapany, tura zapisana `mode=code`,
  brak-workspace → ramka `error` bez wyjątku.

---

## 1. ✅ B1 — Tryb headless / CLI — ZROBIONE 2026-06-06 — **[P1] M**

**Cel:** `python -m caelo_core run -p "..." [opcje]` → agent bez GUI, wyjście plain/json/streaming-json.
Fundament pod CI/skrypty i pod B2.

### 1.1 Subkomendy w `__main__.py`
[`__main__.py`](../caelo_core/__main__.py) dziś = tylko launcher uvicorn. Dodaj rozgałęzienie **na
początku `main()`** (`sys.argv[1]`):
- **brak argumentów** (lub `serve`) → obecne zachowanie (handshake + uvicorn). **Krytyczne:** Electron
  uruchamia `python -m caelo_core` bez argów → ścieżka `serve` MUSI zostać nietknięta (stdout = DOKŁADNIE
  jedna linia handshake).
- `run` → `from caelo_core.headless import main as run_headless; run_headless(argv[2:])`.
- `acp` → B2.

### 1.2 Nowy `caelo_core/headless.py`
- **Parsowanie flag** (`argparse`): `-p/--prompt` (wymagane), `-m/--model`, `--cwd`, `--output-format`
  (`plain`|`json`|`streaming-json`, default `plain`), `--max-turns` (→ `AgentSession.max_iters`),
  `--tools` (allowlista, CSV), `--disallowed-tools` (denylista, CSV; w tym `Agent`/`Agent(role)` →
  blokada delegacji), `--permission-mode` (`ask`→headless mapuje na reject, `accept-edits`, `bypass`,
  `plan`), `--always-approve` (= `bypass`), `--allow`/`--deny` (reguły glob z B4, powtarzalne),
  `-s/--session-id`, `-c/--continue`.
- **Backend + workspace:** `backend = Backend()`; `backend.set_workspace(cwd or os.getcwd())`.
- **Sink wyjścia `emit_headless(ev)`** — mapuje ramki agenta (§ z `routes/agent.py` docstring) na format
  **lustrzany do CLI** (zgodność z ich przykładami integracji):
  - `text` (niesie skumulowany `full`!) → w `streaming-json` policz **deltę** względem poprzedniego
    `full` i wyemituj `{"type":"text","data":<delta>}`; w `json`/`plain` zapamiętaj ostatni `full`.
  - `tool_call` → `{"type":"tool_call","name":...,"args":...}` (tylko streaming-json).
  - `assistant_done`/`done` → finalizacja.
  - na końcu: `{"type":"end","stopReason":"EndTurn","sessionId":<id>}` (streaming-json) /
    `{"text":...,"stopReason":...,"sessionId":...}` (json) / sam tekst (plain).
  - **Uwaga:** brak strumienia „thought" (llm.py go nie produkuje) — nie emituj `thought`.
- **`request_approval_headless(id,name,detail)`** — brak człowieka:
  - `--always-approve`/`--permission-mode bypass` → tryb sesji `bypass` (mutacje bez pytania).
  - reguły `--allow/--deny` (B4) → ewaluuj; deny→`"reject"`, allow→`"accept"`.
  - **domyślnie fail-closed:** mutacja bez reguły/zgody → `"reject"` (NIE auto-accept).
- **Filtrowanie narzędzi:** `--tools` → `tool_names` do `AgentSession` (już wspierane, M17-B1!); 
  `--disallowed-tools` → odejmij; `Agent`/`Agent(role)` → nie wstrzykuj `delegate_fn`/odfiltruj role.
- **Pętla:** `runner = AgentRunner(backend, emit=emit_headless, request_approval=..., stop=...);
  runner.run_turn(prompt, model, mode=..., max_iters=max_turns)`. Po zakończeniu wypisz finał wg formatu.
- **stdout/stderr:** w `run` logi na stderr (`basicConfig` jak w `main()`), zdarzenia na stdout. **Brak
  linii handshake** w tym trybie.

### 1.3 Sesje (opcjonalny pod-krok — można odłożyć)
`-s`/`-c` → minimalna trwałość historii pod `DATA_DIR/sessions/<id>.json` (sam `AgentSession.history`),
`load_json_or_backup` + `atomic_write_text`. Pełny layout sesji CLI (`updates.jsonl` itd.) — odłożone
(decyzja §9).

### 1.4 Selfcheck `caelo_core/tools/headless_check.py`
Mock LLM (monkeypatch `caelo_core.agent.llm.stream_chat_with_tools` na funkcję zwracającą zaplanowane
tury). Asercje: (a) plain/json/streaming-json dają poprawny kształt; (b) `--tools "read_file"` zawęża
advertised tools; (c) `--disallowed-tools "run_command"` usuwa; (d) bez `--always-approve` mutacja →
reject (fail-closed); (e) `--always-approve` → mutacja wykonana; (f) delta `text` w streaming-json.
Wpiąć w `caelo_core/tests/` (adapter pytest).

**Akceptacja B1:** `python -m caelo_core run -p "..." --output-format json` zwraca poprawny JSON;
`echo` handshake nietknięty dla `python -m caelo_core`; `headless_check` zielony w pytest.

**✅ Realizacja (2026-06-06):**
- [`__main__.py`](../caelo_core/__main__.py): `_dispatch(sys.argv[1:])` — brak argów/`serve` → serwer
  (handshake nietknięty), `run` → headless. (`acp` dojdzie w B2.)
- Nowy [`caelo_core/headless.py`](../caelo_core/headless.py): argparse (`-p`/`-m`/`--cwd`/
  `--output-format`/`--max-turns`/`--tools`/`--disallowed-tools`/`--permission-mode`/`--always-approve`/
  `--allow`/`--deny`/`-s`/`-r`/`-c`), `_Sink` (plain/json buforuje, streaming-json emituje delty z `full`),
  fail-closed `request_approval=lambda: "reject"` (mutacje tylko przez tryb bypass/accept-edits lub regułę
  allow B4), `_resolve_tools` (`--tools`/`--disallowed-tools` → `tool_names`; `Agent`/`Agent(...)` →
  blokada delegacji), minimalna persystencja sesji (`DATA_DIR/sessions/<id>.json`, `-s`/`-r`/`-c`). UTF-8
  na stdout. `_run(opts, backend)` rozdzielone od `main()` (backend wstrzykiwany → testowalne bez I/O).
- [`AgentRunner`](../caelo_core/agent/runner.py) rozszerzony **additywnie** (WS bez zmian): `tool_names`,
  `max_iters`, `allow_delegate`, `initial_history` + property `history`.
- [`.gitignore`](../.gitignore): `/sessions/` (dev DATA_DIR = repo). Adapter pytest: `headless_check`
  dodany do `SUITES`.
- **Weryfikacja:** nowy `headless_check` **19/19 OK** (formaty + delty streaming-json; `--tools`/
  `--disallowed-tools` blokują; fail-closed ask vs bypass; `--allow` auto-accept; sesje `-s`/`-c`/`-r`);
  `run -h` exit 0; **handshake `python -m caelo_core` nietknięty** (sprawdzone — drukuje
  `__CAELO_CORE_READY__`); regresja: `agent_selfcheck` **OK**, `api_smoke` **OK** (AgentRunner additywny).
- **Odłożone (decyzja §9):** pełny layout sesji CLI (`updates.jsonl`); `--tools` zawęża narzędzia
  PLIKOWE + delegację (MCP sterowany osobno — włącz/wyłącz serwera).

---

## 2. ✅ B2 — Tryb ACP (Agent Client Protocol) stdio — ZROBIONE 2026-06-06 — **[P1] M–L**

**Cel:** `python -m caelo_core acp` → serwer ACP po stdio (JSON-RPC 2.0) dla Zed/Neovim/Emacs/marimo.

### 2.1 Subkomenda + pakiet `caelo_core/acp/`
- `__main__.py`: gałąź `acp` → `from caelo_core.acp.server import serve; serve()`.
- **`acp/server.py`** — pętla JSON-RPC po stdin/stdout, **newline-delimited, UTF-8** (jak ACP w README
  CLI; **inaczej niż LSP** — patrz B3). Wzorzec czytnika i `write_lock` **z `mcp/client.py`
  `StdioTransport`** (reader thread; logi na stderr; serializacja pod lockiem). Różnica: tu jesteśmy
  **stroną serwera** (czytamy żądania, piszemy odpowiedzi+notyfikacje).
  - Metody:
    - `initialize` → `{protocolVersion:"1", agentCapabilities:{...}}` (deklaruj wsparcie fs/terminal wg
      tego, co realnie robimy; tolerancyjny parser jak w MCP).
    - `session/new` `{cwd, mcpServers}` → `backend.set_workspace(cwd)`; utwórz `AgentRunner` per sesja;
      `sessionId` = `secrets.token_urlsafe`. Trzymaj `dict[sessionId → runner]`.
    - `session/prompt` `{sessionId, prompt:[{type:"text",text}]}` → uruchom `runner.run_turn(text, ...)`
      **w wątku-workerze** (blokujące LLM, jak WS); strumień `session/update` (§2.2); na końcu odpowiedz
      `result {stopReason}`.
    - `session/load` `{sessionId, cwd, mcpServers}` → (po 1.3) wczytaj historię.
    - `session/cancel` → ustaw stop danej sesji.
- **`acp/bridge.py`** — mapowanie ramek agenta → ACP `session/update`:
  | ramka agenta | ACP `sessionUpdate` |
  |---|---|
  | `text` (full) | `agent_message_chunk` (delta z poprzedniego `full`) |
  | `tool_call` | `tool_call` (`toolCallId`, `title`, `status:"pending"`) |
  | `output` | `tool_call_update` (treść/postęp) |
  | `tool_result` | `tool_call_update` (`status:"completed"|"failed"`) |
  | `checkpoint`/`subagent` | opcjonalnie `plan`/custom (faza 2) |
  | `assistant_done`/`done` | finalizacja `result` |

### 2.2 Zgoda (permission flow)
ACP ma `session/request_permission`. `request_approval(id,name,detail)`:
- jeśli klient zadeklarował capability zgody → wyślij `session/request_permission` i **zablokuj wątek
  tury na `threading.Event`** aż przyjdzie odpowiedź (dokładnie wzorzec `routes/agent.py:92-100` z
  `APPROVAL_TIMEOUT_S`).
- jeśli nie → `--permission-mode` (jak headless): bypass/accept-edits/plan, domyślnie reject.

### 2.3 Współbieżność / stdout
Wiele sesji w jednym procesie (dict). Notyfikacje pisane pod **wspólnym `write_lock`** (jeden stdout).
Logi zawsze na stderr.

### 2.4 Selfcheck `caelo_core/tools/acp_check.py`
Mock klient ACP po `subprocess`/potoku + mock LLM: `initialize`→ok; `session/new`→`sessionId`;
`session/prompt`→ ciąg `agent_message_chunk` + `tool_call` + finalny `result`; zła wersja protokołu
obsłużona. Pytest.

**Akceptacja B2:** handshake+prompt po stdio działa na mocku; **weryfikacja na żywo** w Zed/Neovim na
maszynie usera (sandbox blokuje xAI).

**✅ Realizacja (2026-06-06):**
- Nowy pakiet [`caelo_core/acp/`](../caelo_core/acp/): `bridge.py` (`frame_to_acp`: ramki agenta →
  `session/update` — `agent_message_chunk` z deltą, `tool_call`, `tool_call_update`; `stop_reason`) +
  `server.py` `AcpServer` (JSON-RPC 2.0 newline-delimited, UTF-8, `_write_lock`).
- Metody: `initialize` (echo `protocolVersion`, `agentCapabilities`), `session/new`→`sessionId`,
  `session/load`, `session/prompt` (w **wątku-workerze**, blokujące LLM; finalny `result {stopReason}`),
  `session/cancel` (notyfikacja → `stop`). Serwer JEST też klientem: `session/request_permission`
  (agent→klient) z odpowiedzią korelowaną po `id` (`_request_client`, jak `McpClient`); brak
  odpowiedzi/anulowanie → `reject` (fail-closed). Tury serializowane `_turn_lock` (współdzielony
  workspace Backendu); `set_workspace(sess.cwd)` per tura.
- Reużywa [`AgentRunner`](../caelo_core/agent/runner.py) (per sesja, emit/approval związane z serwerem) —
  to samo okablowanie co WS/headless. [`__main__.py`](../caelo_core/__main__.py): gałąź `acp`.
- **Weryfikacja:** nowy `acp_check` **14/14 OK** (initialize+tolerancja protokołu, unknown method→error,
  session/new, prompt→`agent_message_chunk`+`result(end_turn)`, unknown session→error, tool→
  `request_permission`: allow wykonuje + `tool_call`/`tool_call_update`, reject blokuje); **realny
  subprocess** `python -m caelo_core acp`: `initialize`→`result` po stdio, **brak handshake**; regresja
  `agent_selfcheck`/`api_smoke`/`headless_check` **OK**. Adapter pytest: `acp_check` w `SUITES`.
- **Odłożone (decyzja §9):** `thought` (`agent_thought_chunk` — `llm.py` nie strumieniuje myśli);
  wznawianie historii w `session/load` (czeka na pełny layout sesji); `plan`/`subagent` jako
  `session/update` (faza 2). Współdzielony workspace → tury serializowane (1 naraz) — OK dla typowego
  pojedynczego klienta ACP.

---

## 3. ✅ B3 — LSP w trybie Code — ZROBIONE 2026-06-06 — **[P2] L**

**Cel:** pasywna diagnostyka po edycie + narzędzie `lsp` (definition/references/hover/symbols).

### 3.1 Konfiguracja `lsp.json`
Discovery: `<ws>/.caelo/lsp.json` (projekt) + `DATA_DIR/lsp.json` (global; projekt wygrywa). Czytaj
przez `config.load_json_or_backup`. Schema jak CLI: `command`/`args`/`extensionToLanguage`/`transport`/
`env`/`startupTimeout`/`restartOnCrash`/`maxRestarts`.

### 3.2 Pakiet `caelo_core/lsp/`
- **`client.py`** — LSP JSON-RPC po stdio. **⚠ RÓŻNICA OD MCP:** LSP ramkuje wiadomości nagłówkiem
  `Content-Length: N\r\n\r\n<body>` (NIE newline-delimited). Reader musi parsować nagłówki i czytać
  dokładnie N bajtów. **Reużyj z `tools`/`mcp`:** `scrubbed_env()`, `_tree_kill`, `_prepare_argv`
  (Windows `.cmd`/`.bat` → `cmd /c`). Metody: `initialize`/`initialized`, `textDocument/didOpen`/
  `didChange`/`didClose`, `textDocument/{definition,references,hover,documentSymbol,implementation}`;
  odbiór notyfikacji `textDocument/publishDiagnostics` (server→client → bufor per plik).
- **`manager.py`** `LspManager` — rejestr per rozszerzenie pliku, lifecycle (start na żądanie,
  restart-on-crash do `maxRestarts`), `diagnostics_for(path)`, `query(method, path, line, character)`.
  Współdzielenie runtime z subagentami (jeden pool per workspace — jak CLI; decyzja §9).

### 3.3 Wiring w Backend
Leniwy `backend.lsp` (jak `backend.mcp`/`.hooks`/`.skills`). W `server.py` lifespan `backend.shutdown()`
**dodaj tree-kill serwerów LSP** (obok MCP, [`server.py:124-130`](../caelo_core/server.py)).

### 3.4 Integracja z agentem (`session.py`)
- **Narzędzie `lsp`** w `TOOLS` ([`tools.py:59`](../caelo_core/agent/tools.py)); dodaj `"lsp"` do
  `READONLY` w `permissions.py` (bez bramki). Schema: `{action, path, line, character, query}`.
  **Ukryj gdy brak konfiguracji** (jak CLI): w `AgentSession._all_tools()` odfiltruj `lsp`, gdy
  `backend.lsp` puste — model nie planuje wokół niedostępnej zdolności.
- **Pasywna diagnostyka:** po udanym `write_file`/`edit_file` w `_handle_tool_call`
  ([`session.py:374-389`](../caelo_core/agent/session.py)) wyślij do LSP `didChange` i wyemituj **nową
  ramkę** `{"type":"diagnostics","path":...,"items":[{severity,line,character,message,source}]}`.
  Wpiąć tuż po `tool_result` dla narzędzi plikowych (gdy `backend.lsp` aktywne).

### 3.5 REST `routes/lsp.py`
`GET /lsp` (lista + status), `POST /lsp` (dodaj wpis), `DELETE /lsp/{id}`, `POST /lsp/{id}/restart`.
Guarded (`Depends(require_token)`); mount w `server.py` przy reszcie routerów.

### 3.6 Frontend
- `lib/agentClient.ts` — dodaj `diagnostics` do unii `AgentEvent` + `parseAgentEvent`.
- `components/code/AgentPanel.tsx` `handleEvent` — dispatch `diagnostics` do stanu (mapa per ścieżka) +
  licznik „Problems".
- `components/code/CodeEditor.tsx` — props `diagnostics?`; CM6 `lintGutter` + `setDiagnostics`
  (`@codemirror/lint` — nowa, lekka zależność; **instalacja npm po stronie usera**, konwencja CLAUDE.md).
- `components/Extensions.tsx` — dodaj zakładkę `{id:'lsp', label:'Language Servers'}` (tablica `TABS`) +
  nowy `components/extensions/LspServers.tsx` wg wzorca `McpServers.tsx` (lista/dodaj/usuń/restart).

### 3.7 Selfcheck `caelo_core/tools/lsp_check.py`
Mock serwer LSP po potoku (**ramkowanie Content-Length!**) wzorem `_mcp_mock_server.py`: `initialize`,
`didOpen`→`publishDiagnostics` odebrane, `definition` zwraca lokalizację. Pytest.

**Akceptacja B3:** typecheck/lint/vitest zielone; `lsp_check` zielony; **na żywo** (user instaluje
`pyright`/`typescript-language-server`) diagnostyka po edycie + go-to-definition.

**✅ Realizacja (2026-06-06):**
- Nowy pakiet [`caelo_core/lsp/`](../caelo_core/lsp/): `client.py` `LspClient` (JSON-RPC po stdio z
  **ramkowaniem Content-Length** — proces binarny, własny czytnik; korelacja odpowiedzi po `id` + bufor
  `publishDiagnostics` per URI; `scrubbed_env`+`_tree_kill`+`_prepare_argv`; `path_to_uri`/`uri_to_path`;
  initialize/didOpen/didChange/definition/references/hover/documentSymbol/`wait_diagnostics`) +
  `manager.py` `LspManager` (routing per rozszerzenie, leniwe klienty, restart-on-crash, `list_servers`/
  `restart`/`shutdown`).
- Agent ([`session.py`](../caelo_core/agent/session.py)): narzędzie `lsp` (READONLY → dopisane do
  `READONLY` w `permissions.py`, bez bramki; **ukryte gdy brak serwera** — `_all_tools` filtruje przez
  `_lsp().enabled()`), `_handle_lsp` (ścieżka sandboxowana `Workspace.resolve`), **pasywna diagnostyka**
  po udanej edycji → nowa ramka WS `{"type":"diagnostics","path","items"}`. `AgentSession` dostał
  `lsp_provider`; [`AgentRunner`](../caelo_core/agent/runner.py) przekazuje `getattr(backend,"get_lsp")`.
- Backend ([`state.py`](../caelo_core/state.py)): `get_lsp()` (leniwy per workspace, rebuild przy zmianie
  korzenia) + `_discover_lsp_configs` (global `DATA_DIR/lsp.json` + projekt `<ws>/.caelo/lsp.json`) +
  `reload_lsp()`; tree-kill serwerów LSP w `shutdown()`. REST [`routes/lsp.py`](../caelo_core/routes/lsp.py)
  (`GET`/`POST`/`DELETE /lsp/{name}`/`POST /lsp/{name}/restart`) zamontowane w `server.py`.
- Frontend: ramka `diagnostics` w [`agentClient.ts`](../desktop/src/renderer/src/lib/agentClient.ts)
  (typ `LspDiagnostic` + parser); `AgentPanel.tsx` pokazuje diagnostykę w transkrypcie (info/warn);
  panel **Extensions → Language Servers** ([`LspServers.tsx`](../desktop/src/renderer/src/components/extensions/LspServers.tsx)
  + `api.ts` + zakładka w `Extensions.tsx`). `.gitignore`: `/lsp.json`.
- **Weryfikacja:** nowy `lsp_check` **19/19 OK** (mock serwer LSP z ramkowaniem Content-Length: handshake/
  diagnostyka/definition/hover/documentSymbol; menedżer routuje per rozszerzenie; URI round-trip;
  integracja w agencie: `lsp` advertowane/READONLY/ukryte + pasywna diagnostyka); `api_smoke` **+4** (`/lsp`);
  regresja `agent_selfcheck`/`headless_check`/`acp_check` **OK**; frontend typecheck+lint czyste,
  vitest **155**, podgląd (świeży serwer): zakładka+panel renderują się, **0 błędów konsoli**. Adapter
  pytest: `lsp_check` w `SUITES`. **Na żywo** (realny `pyright`/`tsserver`) — na maszynie usera.
- **Odłożone (świadomie):** **inline squiggles w CodeEditor** (CM6 `@codemirror/lint`) — wymaga nowej
  zależności + przeniesienia stanu diagnostyki z AgentPanel do CodeView/edytora; diagnostyka jest dziś
  widoczna w panelu agenta (wartość dla agenta dostarczona). `workspace/symbol` (bez ścieżki) — później.

---

## 4. ✅ B4 — Reguły uprawnień jako globy (`ToolPrefix(glob)`) — ZROBIONE 2026-06-06 — **[P1] S–M**

**Cel:** `Bash(npm*)`, `Edit(src/**)`, `Write(...)`, `Read(...)`, `Grep(...)`, `WebFetch(domain:host)`,
`MCPTool(...)`; `*`=jeden segment, `**`=rekursywnie; **deny > allow**; goły prefiks=wszystko.

### 4.1 Nowy `caelo_core/agent/permission_rules.py`
- **Parser** `parse_rule(s) -> (prefix, pattern)`; prefiksy: `Bash`/`Edit`/`Write`/`Read`/`Grep`/
  `WebFetch`/`MCPTool`.
- **Matcher** `*` vs `**`: **NIE `fnmatch`** (traktuje `*` zachłannie przez `/`). Własny matcher
  segmentowy (split po `/`, `**` pochłania ≥0 segmentów). Dla `Bash` dopasowanie do **stringa komendy**;
  dla `Edit/Write/Read/Grep` do **znormalizowanej ścieżki** (`_norm_path`); dla `WebFetch` `domain:host`
  lub glob URL; dla `MCPTool` do qualified name.
- **`RuleSet`**: listy `allow`/`deny`; `evaluate(prefix, target) -> "deny"|"allow"|None` (deny wygrywa).

### 4.2 Mapowanie narzędzie → (prefix, target)
| narzędzie | prefiksy sprawdzane |
|---|---|
| `run_command` | `Bash` (target=komenda) |
| `write_file` | `Write` **i** `Edit` (target=ścieżka) |
| `edit_file` | `Edit` |
| `read_file` | `Read` · `list_dir` | `Read` |
| `grep` | `Grep` · `glob` | `Read` |
| MCP (`mcp__...`) | `MCPTool` (target=qualified name) |

### 4.3 Integracja w `AgentSession._gate_mutation` ([`session.py:422`](../caelo_core/agent/session.py))
**Przed** istniejącą allowlistą (i dodatkowo wczesny check deny dla READONLY Read/Grep):
1. `deny` match → **twarda odmowa** (`"reject"`; dla readonly: zablokuj odczyt z notatką).
2. `allow` match → `"accept"` — **ALE zachowaj P0-1:** gdy `name=="run_command"` i
   `command_metachars(cmd)` → **ignoruj allow** (przejdź dalej; `execute_tool` odrzuci jednym
   autorytatywnym komunikatem). Deny nadal obowiązuje.
3. brak dopasowania → **istniejąca logika** (`gate.needs_approval` + `request_approval`) — bez zmian.

Reguły to **dodatkowa warstwa**, allowlista `cmd:`/`tool:`/`mcp:` zostaje (wstecz-kompatybilność).

### 4.4 Źródła reguł
- headless `--allow`/`--deny` (B1) → `RuleSet` na przebieg.
- trwałe globalne w `caelo_settings.json` (`permission_rules: {allow:[], deny:[]}`).
- projektowe `<ws>/.caelo/permissions.json` (`load_json_or_backup`).
- UI: rozszerz panel **Permissions** + `routes/permissions.py` o listę/dodawanie/usuwanie reguł obok
  allowlisty. `RuleSet` budowany w `Backend` i podawany `PermissionGate`/`AgentRunner`.

### 4.5 Selfcheck (rozszerz `agent_selfcheck.py`)
deny>allow; `**` vs `*` (np. `Edit(src/*)` NIE łapie `src/a/b.py`, `Edit(src/**)` łapie);
`Bash(git*)` nie przepuszcza `git && rm` (metaznaki); `WebFetch(domain:docs.rs)`; `MCPTool(...)`.
**Zachowaj 166 dotychczasowych asercji zielonych.**

**Akceptacja B4:** nowe asercje w `agent_selfcheck`; UI pokazuje/edytuje reguły; P0-1 nieregresowane.

**✅ Realizacja (2026-06-06):**
- Nowy [`caelo_core/agent/permission_rules.py`](../caelo_core/agent/permission_rules.py): `parse_rule`,
  matcher segmentowy (`*` w obrębie segmentu, `**` rekursywnie — NIE `fnmatch` dla ścieżek), `RuleSet`
  (`evaluate_tool`, deny>allow), `targets_for_tool` (mapowanie narzędzie→prefiks), `_match_webfetch`
  (domain:+subdomeny). Bez importu z `permissions.py` (uniknięty cykl).
- [`permissions.py`](../caelo_core/agent/permissions.py): `PermissionGate` dostał `ruleset` +
  `set_rules`/`evaluate_rules`/`rule_strings` (pusty zbiór → `None`, zero wpływu sprzed B4).
- [`session.py`](../caelo_core/agent/session.py): **deny** w `_handle_tool_call` PO hookach (obejmuje też
  READONLY i tryb **bypass** — twardy zakaz); **allow** na początku `_gate_mutation` z zachowaniem **P0-1**
  (metaznaki `run_command` nie są obchodzone regułą — spadają do odrzucenia przez `execute_tool`).
- [`state.py`](../caelo_core/state.py): `reload_permission_rules()` (globalne z `caelo_settings.json` +
  projektowe z `<ws>/.caelo/permissions.json`) wołane przy starcie i `set_workspace`. Subagenci (M17)
  dziedziczą reguły (ta sama bramka) — brak eskalacji.
- [`routes/permissions.py`](../caelo_core/routes/permissions.py): `GET`/`PUT /permissions/rules`
  (walidacja `parse_rule`→400 fail-closed, limit 200, persystencja + przebudowa bramki).
- Frontend: `lib/api.ts` (`getPermissionRules`/`setPermissionRules`) + edytor Allow/Deny w
  `CodeView.tsx` `PermissionsMenuContent` (textarea per linia, Save + komunikat błędu).
- **Weryfikacja:** `agent_selfcheck` **+18 asercji** (parser, `*`/`**`, deny>allow, Write+Edit, MCPTool,
  WebFetch, deny-blokuje-READONLY/bypass, allow-auto-accept, P0-1) → **RESULT: OK**; `api_smoke`
  **+4** (`_unit_permissions_routes`: GET/PUT, 400, fail-closed) → **OK**; frontend typecheck+lint
  czyste; podgląd: edytor renderuje się, błąd zapisu obsłużony (brak crasha), 0 błędów konsoli.
- **Uwaga (drobna, świadoma):** deny dla READONLY blokuje **po** hookach (audit-all zdąży zalogować
  próbę) — zgodne z §4.3 ("wczesny check deny dla READONLY").

---

## 5. Sekwencja, zależności, zrównoleglenie

```
§0 AgentRunner  ──►  B1 headless  ──►  B2 ACP
   (odblokowuje B1/B2)        ▲
B4 reguły glob ───────────────┘ (B1 --allow/--deny używa B4)
B3 LSP  ── niezależne (poza nową ramką WS) — można robić równolegle/kiedykolwiek
```
**Rekomendowana kolejność:** **§0 → B4 → B1 → B2 → B3.**
- §0 pierwsze (refaktor zachowawczy, odblokowuje resztę).
- B4 wcześnie: małe, samodzielne, natychmiast użyteczne w UI **i** wymagane przez `--allow/--deny` w B1.
- B1 przed B2 (ACP reużywa runnera + wzorca zgody headless).
- B3 najobszerniejsze i najbardziej niezależne — równolegle przez drugą osobę/agenta, jedyny styk z
  resztą to nowa ramka `diagnostics` (frontend) i `READONLY += {"lsp"}`.

---

## 6. Wspólne zasady (z CLAUDE.md — nie regresować)

- **stdout święty:** `serve` = handshake; `run`/`acp` = strumień zdarzeń; oba przez rozłączne subkomendy;
  logi ZAWSZE na stderr (`basicConfig` jak w `__main__.main`).
- **UTF-8** w każdym JSON-RPC po stdio (ACP/LSP) — jawne `encoding="utf-8"` jak `StdioTransport`/
  `responses_client`.
- **Podprocesy potomne** (LSP): `scrubbed_env()` + `_tree_kill` + `_prepare_argv` z `tools`/`mcp`;
  tree-kill w `backend.shutdown()`.
- **Fail-closed:** headless/ACP domyślnie odrzucają mutacje bez jawnej zgody/reguły.
- **Bez zmian root-modułów** (`config.py`/`api_manager.py`/…); nowy kod w `caelo_core/`.
- **Bez nowych ciężkich zależności** backend: ACP/LSP = własne cienkie warstwy JSON-RPC (jak klient MCP).
  Frontend: `@codemirror/lint` (lekkie) — instaluje user (TLS-interception).
- **Tekst UI po angielsku**; komentarze/docstringi mogą być po polsku.
- **„Selfcheck albo się nie stało":** każdy element ma suite w `caelo_core/tests/` (pytest).

---

## 7. Akceptacja zbiorcza Tier-1

| Element | Backend selfcheck | Frontend | Na żywo (maszyna usera) |
|---|---|---|---|
| §0 runner ✅ | `agent_selfcheck` 166 ✅ + `api_smoke` ✅ (bez zmian) + direct runner-check ✅ | — | — |
| B1 headless ✅ | `headless_check` 19/19 ✅ + regresja `agent_selfcheck`/`api_smoke` ✅ | — | `run -p` z realnym xAI |
| B2 ACP ✅ | `acp_check` 14/14 ✅ + realny subprocess stdio ✅ | — | Zed/Neovim end-to-end |
| B3 LSP ✅ | `lsp_check` 19/19 ✅ + `api_smoke` +4 ✅ | typecheck/lint/vitest 155 ✅ + podgląd ✅ | `pyright`/`tsserver` + edycja |
| B4 reguły ✅ | `agent_selfcheck` +18 ✅, `api_smoke` +4 ✅ | panel Permissions ✅ (typecheck/lint/podgląd) | — |

---

## 8. Ryzyka i szacunki

| Element | Wysiłek | Główne ryzyko | Mitigacja |
|---|---|---|---|
| §0 runner | S–M | regresja okablowania WS | refaktor zachowawczy + selfchecki zielone przed B1/B2 |
| B1 | M | kolizja stdout handshake↔strumień | rozłączne subkomendy; test handshake |
| B2 | M–L | poprawność/kolejność ACP, double-source zdarzeń | wspólny runner; `acp_check`; weryfikacja w Zed |
| B3 | L | ramkowanie Content-Length ≠ MCP; stabilność długożyjących procesów | osobny reader (nie kopiuj MCP wprost); restart-on-crash |
| B4 | S–M | subtelność `*`/`**`; obejście P0-1 | własny matcher segmentowy; twardy test metaznaków |

---

## 9. Otwarte decyzje (rozstrzygnąć w trakcie)

- **Layout sesji headless/ACP:** minimalny `history.json` (szybko) vs pełny layout CLI
  (`sessions/<enc-cwd>/<id>/{summary.json,updates.jsonl,...}` — zgodność, ale więcej pracy).
  Rekomendacja: minimalny teraz, pełny gdy pojawi się potrzeba interop.
- **ACP capability zgody:** negocjować w `initialize` i degradować do `--permission-mode`, gdy klient nie
  wspiera. Rekomendacja: tak.
- **LSP a subagenci:** współdzielić runtime rodzica (jak CLI) — rekomendacja: tak (jeden pool/workspace).
- **Reguły vs allowlista (B4):** docelowo zastąpić allowlistę regułami, czy trzymać obie? Rekomendacja:
  **obie** (wstecz-kompatybilność), reguły jako warstwa nadrzędna (deny>allow>allowlista>pytaj).
- **`thought`/reasoning w ACP:** `llm.py` nie strumieniuje myśli. Dodać kanał reasoning (z `responses_client`)
  później → wtedy ACP `agent_thought_chunk`. Teraz: tylko `agent_message_chunk` + `tool_call`.

---

*Dokument towarzyszy [`PLAN_M19_PARYTET_GROK_CLI.md`](PLAN_M19_PARYTET_GROK_CLI.md) (§4). Aktualizować status
w nagłówku przy realizacji. Punkty styku zweryfikowane w kodzie 2026-06-06.*
