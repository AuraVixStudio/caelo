# PLAN_M19_TIER2.md — Pełny plan implementacyjny Tier-2

> Rozwinięcie §5 z [`PLAN_M19_PARYTET_GROK_CLI.md`](PLAN_M19_PARYTET_GROK_CLI.md) do poziomu
> implementacyjnego. Cztery elementy: **B5 interop ekosystemu · B6 skille-orkiestratory na M17 ·
> B7 sandbox OS-kernel · B8 pamięć hybrydowa**. Wszystkie **[P2]**.
>
> **Zakłada gotowe:** M13 (CAELO.md), M14 (MCP/skille/komendy/hooki), M17 (subagenci/role/`delegate`/
> `TeamManager`), M9 (`history_store` FTS5), oraz **Tier-1** (§0 AgentRunner, B1 headless, B2 ACP, B3 LSP,
> B4 reguły glob — wzorce: workspace-aware reload jak `get_lsp`, hartowanie podprocesów, selfchecki).
>
> Tagi: **[P2]** dobre. Wysiłek: **S** ≈ dni · **M** ≈ 1–2 tyg. · **L** ≈ 3–4 tyg.
>
> **STATUS (2026-06-06): ✅ TIER-2 ZAIMPLEMENTOWANE — B5 (interop §1.1–§1.3) + B6 (skille-orkiestratory)
> + B8 (pamięć hybrydowa) + B7 (sandbox OS) wszystkie DONE (na stubie/mocku, selfchecki zielone).**
> Pozostają tylko **weryfikacje LIVE u usera** (sandbox blokuje sieć/exec OS): (1) embeddings xAI
> `embeddings_check --live`, (2) realny sandbox `caelo run --sandbox strict` na Linux/macOS, (3) delegacja
> B6 / interop z realnym `~/.claude*`. Rozpisy: §1 (B5), §2 (B6), §3 (B7), §4 (B8).

---

## 0. Wynik weryfikacji repo (punkty styku, stan na 2026-06-06)

| Obszar | Stan / plik | Wniosek dla Tier-2 |
|---|---|---|
| Reguły projektu | [`agent/caelomd.py`](../caelo_core/agent/caelomd.py) — czyta `CAELO.md`/`GROK.md` z root+global | **B5**: dodać AGENTS.md/CLAUDE.md (alternatywne nazwy) |
| MCP config | [`mcp/manager.py`](../caelo_core/mcp/manager.py) `_load` ← `config.MCP_FILE` (`load_json_or_backup`) | **B5**: scalić `~/.claude.json` + `<ws>/.mcp.json` |
| Skille | [`skills/manager.py`](../caelo_core/skills/manager.py) `_scan(BUILTIN_DIR)`+`_scan(SKILLS_DIR)`; format SKILL.md (frontmatter name/description/triggers + body); `injected_text()` | **B5**: scan `~/.claude/skills`+`.claude/skills`; **B6**: nowe builtiny |
| Role subagentów | [`agent/roles.py`](../caelo_core/agent/roles.py) `BUILTIN_ROLES` (researcher/reviewer/implementer/tester) | **B6**: dodać design-doc-writer/reviewer, security-auditor, test-writer |
| Delegacja | `delegate` tool + `TeamManager` (M17) — orkiestrator w pętli `delegate` | **B6**: skille = prompty sterujące `delegate` |
| Podprocesy | `tools.run_command` (Popen: shell na Win / argv POSIX, `scrubbed_env`+`_tree_kill`+`start_new_session`); MCP/LSP analogicznie | **B7**: owinąć spawn sandboxem OS |
| Pamięć/historia | [`history_store.py`](../caelo_core/history_store.py): FTS5 `history_fts` (MATCH), `record_event`; `vector_store_id` = martwy relikt | **B8**: dodać embeddingi + KNN + 1. tura |
| Klient embeddings | **brak** (0 trafień w `responses_client`/`api_manager`) | **B8**: nowy klient xAI **lub** lokalny (spike) |
| Ścieżki | `config.py`: `DATA_DIR`, `MCP_FILE`, `SKILLS_DIR`, …; **brak** `~/.claude` | B5: dodać `CLAUDE_HOME`/`CLAUDE_JSON` (`Path.home()`) |

**Wzorzec do reużycia (z Tier-1 B3):** workspace-aware lazy rebuild — `backend.get_lsp()` przebudowuje
menedżera przy zmianie korzenia + `reload_lsp()`. **B5** stosuje go do `backend.skills`/`backend.mcp`
(by złapać `<ws>/.claude/...` / `<ws>/.mcp.json`).

---

## 1. B5 — Interop ekosystemu (Claude Code / Grok CLI) — **M**

**Cel:** istniejące projekty „po prostu działają" + dostęp do ekosystemu (format = schema Anthropica).
Trzy niezależne rozszerzenia discovery; każde osobno wartościowe.

### 1.1 Reguły projektu: AGENTS.md / CLAUDE.md (S) — ✅ DONE (2026-06-06)
- [x] [`agent/caelomd.py`](../caelo_core/agent/caelomd.py): rozszerzono `_read_dir_md` o alternatywne nazwy
  (kolejność pierwszeństwa): natywny `CAELO.md` (a gdy brak — legacy `GROK.md`) → `AGENTS.md`/`AGENT.md`/
  `Agents.md` → `CLAUDE.md`/`Claude.md` (`INTEROP_MD_NAMES`). Czyta **wszystkie istniejące** i skleja
  (cap per plik = `MAX_CAELO_MD_BYTES`), z adnotacją źródła `### From <name>`. Dedup po `os.path.normcase`
  (kolizje wielkości liter na Windows; case-sensitive na Linux traktowane jako osobne pliki). Legacy
  `GROK.md` pozostaje **czystym fallbackiem** (czytany tylko gdy brak `CAELO.md` — bez podwójnego natywnego).
  Workspace nadpisuje global (bez zmian w `load_caelo_md`). Nagłówek wstrzyknięcia uściślony na
  „CAELO.md / AGENTS.md / CLAUDE.md".
- [x] Workspace-aware **za darmo**: `session._build_system_prompt()` woła `build_system_prompt` per tura z
  `self.ws.root` — czyta świeżo. Brak zmian w session.py. Zapis REST `/caelo-md` dalej idzie do `CAELO.md`.
- **Hierarchia root→cwd (opcjonalnie, NIE robione):** CLI czyta od korzenia repo do cwd. Nasz agent = jeden
  root, więc pomijamy walk; gdyby trzeba — dodać skan podkatalogów (odłożone).
- [x] Selfcheck: rozszerzono `test_caelo_md` w `agent_selfcheck.py` (+7 asercji B5: `AGENTS.md`+`CLAUDE.md`
  oba w prompcie z adnotacją źródła, kolejność pierwszeństwa, `CAELO.md` ma pierwszeństwo nad interop,
  `GROK.md` czytany tylko bez `CAELO.md`). Cała suita zielona (`RESULT: OK`).

### 1.2 MCP z `~/.claude.json` + `<ws>/.mcp.json` (M) — ✅ DONE (2026-06-06)
- [x] `config.py`: dodano `CLAUDE_JSON = Path.home() / ".claude.json"` (M19-B5 §1.2).
- [x] [`mcp/manager.py`](../caelo_core/mcp/manager.py): konstruktor dostał jawne źródła interop
  (`workspace_root`/`claude_json`, domyślnie `None` = brak discovery — czyste zachowanie testów; Backend
  wstrzykuje realne ścieżki). `_load` po natywnym `caelo_mcp.json` **scala** `mcpServers` z `<ws>/.mcp.json`
  (projekt) i `~/.claude.json` (global). Mapper `_claude_server_to_cfg`: stdio (`command`+`args`→argv, `env`/
  `cwd`) i remote (`url`/`type` sse/http → transport remote). **Pierwszeństwo: natywny > projekt > global**
  (kolizje id pomijane). **Sekrety nie wyciekają** (`env`/`authorization` maskowane w `public_config`).
- [x] **Niedestrukcyjny odczyt** (`_read_interop_servers`): w przeciwieństwie do `load_json_or_backup`
  NIGDY nie przenosi/nie modyfikuje cudzego pliku (`~/.claude.json` należy do Claude Code) — brak/uszkodzenie/
  zły kształt → `{}`. (Naprawiona pułapka: backup `.corrupt` zniszczyłby konfigurację innego narzędzia.)
- [x] **Workspace-aware** (wzorzec `get_lsp`/`reload_lsp`): property `backend.mcp` przebudowuje się przy
  zmianie korzenia (tree-kill starych podprocesów + reset zależnego `_packages`); dodano `backend.reload_mcp()`
  wołane w `set_workspace` (deterministyczny teardown przy przełączeniu). `~/.claude.json` doczytywany przy
  każdym buildzie (global).
- [x] **Bezpieczeństwo (jak M16):** importowane serwery wchodzą **`enabled=False`** (autostart `start_enabled`
  je pomija — `import niczego nie odpala`); start = osobna gejtowana akcja. `_save` **nie persistuje**
  importowanych do `caelo_mcp.json` (odkrywane dynamicznie); `source` (`native`/`claude-*`) w `public_config`.
- [x] Selfcheck: `mcp_check.py` `test_interop` (+12 asercji: widoczność native+global+project, disabled,
  pierwszeństwo native/projekt, mapowanie command+args/remote, maskowanie env/auth, brak wycieku do
  `caelo_mcp.json`, niedestrukcyjność przy korupcji). `ALL PASSED (36/36)`; `api_smoke`/`packages_check`/
  `handshake_check` bez regresji.

### 1.3 Skille z `~/.claude/skills` + `<ws>/.claude/skills` (S–M) — ✅ DONE (2026-06-06)
- [x] `config.py`: dodano `CLAUDE_HOME = Path.home() / ".claude"` (M19-B5 §1.3).
- [x] [`skills/manager.py`](../caelo_core/skills/manager.py): `SkillManager` dostał jawne `workspace_root`/
  `claude_home` (domyślnie `None` = brak interopu — czyste testy; Backend wstrzykuje realne). `_all` skanuje w
  rosnącej kolejności pierwszeństwa: **builtin < user(`SKILLS_DIR`) < `~/.claude/skills` < `<ws>/.claude/skills`
  < `<ws>/.grok/skills`** (każdy `update` nadpisuje po id). `_read_skill`/`_scan`/`_public` dostały pole
  `source` (`builtin`/`user`/`claude-global`/`claude-project`/`grok-project`). Format SKILL.md identyczny.
- [x] **Tylko READ z cudzych katalogów:** stan „enabled" trzymany centralnie w `SKILLS_DIR/_state.json` (po id);
  `delete_skill` usuwa **wyłącznie** skille `source=="user"` (interop/builtin nieusuwalne — nie ruszamy cudzych
  plików); `create_skill` pisze tylko do `SKILLS_DIR`. (Discovery `_all` czyta dysk świeżo, więc nie ma
  destrukcyjnego backupu jak w §1.2 — czysty `read_text`.)
- [x] **Workspace-aware** (wzorzec `get_lsp`): property `backend.skills` przebudowuje się przy zmianie korzenia
  (brak podprocesów → tylko nowe ścieżki skanu); `workspace_root` na menedżerze do porównania.
- [x] **Frontend (ponad plan, opcjonalne):** `SkillInfo.source` w `api.ts`; `SkillsLibrary` pokazuje badge
  źródła (`~/.claude`/`.claude`/`.grok`) i ukrywa Delete dla skilli nie-`user`. Typecheck ✅ (node+web).
- [x] Selfcheck: `api_smoke` `_unit_commands_skills` (+9 asercji B5: odkrycie z global/projektu, tagi `source`,
  pierwszeństwo projekt>global>user, wstrzyknięcie włączonego interop-skilla, stan tylko w `SKILLS_DIR`,
  nieusuwalność interop + plik nietknięty, brak interopu domyślnie). `RESULT: OK`; `packages_check` 48/48,
  `agent_selfcheck` OK bez regresji. **Panel źródeł NIEWERYFIKOWANY w preview** (devMock nie serwuje `/skills`
  — bogaty mock jest w E2E) → wizualnie na żywo u usera.

> **Opcjonalnie (odłożone): `inspect`** — odpowiednik `grok inspect` (REST `/inspect`): co odkryto
> (reguły/skille/MCP/role/hooki + źródło `[claude]`/`[builtin]`). Dobre do debugowania interopu; nie blokuje B5.

**Ryzyka:** workspace-aware rebuild dla skills/mcp (stan współdzielony WS↔REST — trzymać wzorzec `get_lsp`);
mapowanie kształtu Claude→nasz (tolerancyjny parser). **Akceptacja:** AGENTS.md/CLAUDE.md w prompcie;
`.mcp.json`/`~/.claude.json` serwery widoczne (disabled); `~/.claude/skills` odkryte; selfchecki zielone.

---

## 2. B6 — Skille-orkiestratory na silniku M17 — **M** — ✅ DONE (2026-06-06)

**Cel:** „killer feature" subagentów — wbudowane pętle wieloagentowe jako pakiety SKILL.md (jak bundluje
CLI). Skill = prompt wstrzykiwany w system prompt orkiestratora, który steruje narzędziem `delegate`
(M17) i rolami. Działa w JEDNEJ sesji orkiestratora wołającej `delegate` wielokrotnie.

### 2.1 Nowe role ([`agent/roles.py`](../caelo_core/agent/roles.py) `BUILTIN_ROLES`) — ✅
- [x] Dodano 4 role do `BUILTIN_ROLES` (`effective_tools` = rola ∩ rodzic — bez eskalacji, niezmienione):
  `design-doc-writer` (mutujące-w-worktree: write_file/edit_file), `design-doc-reviewer` (READONLY: krytyka,
  `VERDICT: APPROVE/REVISE`), `security-auditor` (READONLY: audyt podatności), `test-writer`
  (mutujące-w-worktree: write+run_command). Persony wzorowane na `bundled/personas/*.toml` z Grok CLI.

### 2.2 Wbudowane skille ([`skills/builtin/<id>/SKILL.md`](../caelo_core/skills/builtin/)) — ✅
- [x] Dodano 6 builtinów (spec **już** pakuje `skills/builtin/**/*.md` — bez zmian pakowania). Każdy =
  frontmatter (`name`/`description`/`triggers`) + body-orkiestracja sterujące `delegate`:
  **`implement`** (pętla implement->review->fix, rundy = „effort"), **`review`** (reviewerzy na lokalny
  diff — orkiestrator zbiera diff bo reviewer jest READONLY), **`design`** (pętla writer/reviewer aż do
  `VERDICT: APPROVE`), **`best-of-n`** (N równoległych prób, wybór najlepszej), **`check-work`** (reviewer +
  tester vs kryteria akceptacji), **`pr-babysit`** (zależność **GitHub MCP/`gh`** oznaczona w `description`).

### 2.3 Integracja — ✅
- [x] Bez zmian w silniku: skille już wstrzykiwane (`SkillManager.injected_text()` w `_build_system_prompt`),
  `delegate`+role+`TeamManager` gotowe (M17). B6 = **treść** (prompty/role), nie nowy kod silnika.
- ⚠️ **KOREKTA założenia planu:** „skille dostępne jako `/implement` w composerze (już działa)" jest
  NIEŚCISŁE — `hub.slashCommands` ładuje wyłącznie rejestr **komend** (`/commands`), a skille są
  wstrzykiwane do promptu **AGENTA** (nie czatu, który nie ma `delegate`). `/implement` w composerze czatu
  byłby semantycznie błędny. Skille-orkiestratory włącza się w **Extensions → Skills**; wpływają na agenta.
  Świadomie NIE dodano mylącego slash-surfacingu.
- [x] Selfcheck: `api_smoke` `_unit_commands_skills` (6 builtinów odkrytych + `injected_text` zawiera
  sterowanie `delegate` po włączeniu); `agent_selfcheck` `test_orchestration_roles` (+8: role zarejestrowane,
  READONLY vs worktree, `effective_tools` nie eskaluje ponad rodzica). Oba `RESULT: OK`; `packages_check`
  48/48. **Pętle delegacji end-to-end weryfikowane na żywo** (xAI) na maszynie usera.

**Ryzyka:** jakość promptów (iteracja na żywo); `pr-babysit` zależy od zewnętrznego MCP. **Akceptacja:**
builtiny odkryte/parsują/wstrzykują ✅; nowe role zarejestrowane bez eskalacji ✅; live: pętla `delegate`
(maszyna usera).

---

## 3. B7 — Sandbox OS-kernel — **L** — ✅ DONE (2026-06-06); realna egzekucja = live na Linux/macOS usera

**Cel:** wzmocnić istniejącą fosę (`Workspace.resolve` + `scrubbed_env` + `sandbox:true` Electron) o
izolację **procesów potomnych** `run_command`/MCP/LSP na poziomie jądra. **Off domyślnie** → `off` nie
zmienia zachowania. Wybrano **per-komenda** (§3.3 rekomendacja), nie in-process.

### 3.1 Model profili + config — ✅
- [x] [`sandbox/profiles.py`](../caelo_core/sandbox/profiles.py): `Profile` + `build_profile` dla
  `off`/`workspace` (read-all, write root+/tmp+DATA_DIR)/`read-only` (write tylko DATA_DIR)/`strict`
  (read/write tylko root + `restrict_network`); nieznana nazwa → `off` (fail-safe). `sensitive_paths()`
  (`~/.ssh`/`~/.aws`/`~/.gnupg`/`DATA_DIR/caelo_auth.json`) ZAWSZE na deny-liście.
- [x] **DECYZJA: config = JSON, NIE TOML.** `DATA_DIR/sandbox.json` (globalny) + `<ws>/.caelo/sandbox.json`
  (projekt, nadpisuje) via `config.load_json_or_backup` — spójne z całym state repo (`lsp.json`/
  `permissions.json`), bez ryzyka wersji `tomllib`. Klucze: `default_profile`/`read_only`/`read_write`/
  `deny`/`restrict_network`. Nazwa profilu: projekt > globalny plik > env `config.SANDBOX_PROFILE`.

### 3.2 Egzekucja per-komenda ([`caelo_core/sandbox/`](../caelo_core/sandbox/)) — ✅
- [x] `wrap(argv, profile, root, platform=, which=)` (PURE, testowalne): **macOS** → `sandbox-exec -p
  <seatbelt>` (`seatbelt_profile()` generuje politykę .sb: deny network/write + allow root, deny sekretów na
  końcu); **Linux** → `bwrap` jeśli na PATH (`linux_bwrap_argv`: ro-bind `/` lub minimalny system w strict,
  bind zapisywalnych korzeni, maska sekretów tmpfs/`/dev/null`, `--unshare-net` w strict) — inaczej **no-op +
  ostrzeżenie**; **Windows/inne** → no-op (Job/tree-kill już są). `wrap_command(argv, root)` = wejście +
  `resolve_profile` + log; `off`→no-op.
- [x] Wpięcie wspólnym helperem: [`tools.run_command`](../caelo_core/agent/tools.py) (gałąź POSIX-argv,
  **fail-open**), [`mcp/client.py`](../caelo_core/mcp/client.py) i [`lsp/client.py`](../caelo_core/lsp/client.py)
  spawn. Off-by-default → wszędzie czysty no-op (zero regresji).
- [x] Opt-in: flaga headless **`--sandbox <profile>`** (B1) + env `CAELO_SANDBOX` + `sandbox.json`
  `default_profile`. Log zdarzeń: `DATA_DIR/sandbox-events.jsonl` (gitignored).

### 3.3 Alternatywa in-process — odrzucona (jak rekomendacja)
Per-komenda (granularne, nie psuje sidecara, który potrzebuje sieci do xAI + zapisu DATA_DIR).

- [x] Selfcheck: nowy [`sandbox_check.py`](../caelo_core/tools/sandbox_check.py) (**29/29**, mockowalne
  per-platforma: profile, `resolve_profile` z `sandbox.json`, `wrap()` bwrap/seatbelt/no-op, sekrety na
  deny-liście, `run_command` off=bez zmian); w pytze (`tests/test_selfchecks.py`). Bateria bez regresji
  (agent/mcp/lsp/headless/api_smoke…). **Realna egzekucja** (bwrap/Seatbelt faktycznie blokuje zapis) = live
  na Linux/macOS usera: `caelo run -p "…" --sandbox strict`.

**Akceptacja:** profile parsują ✅; `wrap()` buduje poprawne argv ✅; off nie zmienia zachowania ✅;
**live: zapis poza CWD blokowany w `strict` na Linux/macOS = u usera.**

---

## 4. B8 — Pamięć hybrydowa (FTS5 + embeddingi) — **M** — ✅ DONE na stubie (2026-06-06); live embeddings = spike u usera

**Cel:** semantyczny recall ponad obecny FTS5 + wstrzyknięcie najtrafniejszych wspomnień na 1. turze
(jak CLI). Zasada „tylko Grok" + „bez ciężkich zależności". **Cały mechanizm zbudowany i sprawdzony na
STUB-embedderze (bez sieci); jedyny element zależny od spike'u to potwierdzenie żywego endpointu xAI.**

### 4.1 Źródło embeddingów — ✅ klient gotowy (live = spike §9)
- [x] Nowy [`caelo_core/embeddings.py`](../caelo_core/embeddings.py) — cienki klient (jak `responses_client`:
  endpoint/auth `api_key_provider`, **JAWNE UTF-8**, format OpenAI `{model,input}`→`data[].embedding`,
  parser tolerancyjny). `embed_texts`/`embed_text` (rzucają `EmbeddingError`, wołający połyka) + `probe()`
  (spike: `{ok,model,dim}`, nie rzuca). Domyślny model `config.EMBED_MODEL="embedding-beta-3-small"`.
- ⏳ **Live (maszyna usera):** `python caelo_core/tools/embeddings_check.py --live` — potwierdza czy
  `POST /v1/embeddings` działa + wymiar/koszt. Jeśli 404/400 → B8 zostaje na stubie/odłożone (bez torch).

### 4.2 Magazyn + KNN ([`history_store.py`](../caelo_core/history_store.py)) — ✅
- [x] Tabela `event_embeddings(event_id PK, dim, vec BLOB float32, created_at)` (idempotentny
  `CREATE TABLE IF NOT EXISTS`). `set_event_embedding`/`count_event_embeddings`/`knn_events`/`hybrid_search`.
- [x] KNN = brute-force cosine w Pythonie (`array` ze stdlib, bez `sqlite-vec`/numpy); wektory o niezgodnym
  wymiarze pomijane; `min_score`. Hybryda: KNN (rerank, pierwszeństwo) ∪ FTS5 (`history_fts` MATCH), dedup po id.

### 4.3 Wstrzyknięcie na 1. turze + orkiestracja — ✅
- [x] Orkiestrator [`caelo_core/memory.py`](../caelo_core/memory.py) `MemoryIndex` (embedder **wstrzykiwany**
  — jak egzekutor genjobs; magazyn bez sieci): `index_event`/`recall`/`injected_text`. **Opt-in** (`enabled`),
  błędy połykane.
- [x] [`agent/session.py`](../caelo_core/agent/session.py): na 1. turze embed promptu usera → `injected_text`
  → blok po CAELO.md/skillach (raz na sesję, cache). Wstrzyknięte przez `AgentRunner` (`backend.memory`).
- [x] [`state.py`](../caelo_core/state.py): leniwe `backend.memory` (embedder = `embeddings.embed_texts` +
  `get_api_key`); `record_event` indeksuje w **wątku w tle** (opt-in, nie blokuje gorącej ścieżki).
- [x] Config `[memory]`: `MEMORY_ENABLED` (env `CAELO_MEMORY=1`, **domyślnie OFF** — koszt+prywatność),
  `MEMORY_MAX_RESULTS`, `MEMORY_MIN_SCORE`, `EMBED_MODEL`. Narzędzie `memory_search` — odłożone (jak plan).
- [x] Selfcheck: `history_check.test_memory_knn_hybrid` (+12, stub embedder: store/KNN/min_score/dim-skip/
  hybryda/MemoryIndex opt-in), `agent_selfcheck.test_memory_injection` (+4: 1. tura wstrzykuje, raz/sesję,
  cache, brak przy `memory=None`), nowy `embeddings_check` (11, parser + błędy + mock transport; `--live` spike).

**Ryzyka:** dostępność/koszt endpointu embeddings (spike), jakość hybrydy, latencja 1. tury (mała). 
**Akceptacja:** embeddingi zapisywane ✅, KNN+hybryda na stubie ✅, 1. tura wstrzykuje ✅; **xAI embeddings
potwierdzone live = u usera (`--live`).**

---

## 5. Sekwencja, zależności, zrównoleglenie

```
B5 interop ── niezależne (M)         ┐
B6 skille  ── niezależne (M, na M17) ┼─ równoległe; B5/B6 najpierw (wartość, niskie ryzyko)
B8 pamięć  ── M (po spike embeddings)┘
B7 sandbox ── L, research (osobno; najmniej pilne, najwięcej niepewności)
```
**Rekomendacja:** **B5 → B6 → (spike embeddings) → B8 → B7.**
- B5/B6 dają natychmiastową wartość ekosystemową, niskie ryzyko, brak nowych zależności.
- B8 po potwierdzeniu endpointu embeddings (spike §9); inaczej odłożyć.
- B7 ostatnie — najwięcej researchu platformowego; off-by-default, więc nie blokuje reszty.
Wspólny wątek B5: **workspace-aware reload** `backend.skills`/`backend.mcp` (wzorzec `get_lsp` z B3) —
zrobić raz, użyć w 1.2 i 1.3.

---

## 6. Wspólne zasady (z CLAUDE.md — nie regresować)

- **Bez zmian root-modułów** (`config.py`/`api_manager.py`/…); nowy kod w `caelo_core/`. Klient embeddings
  (B8) = cienka warstwa endpoint/auth, nie restrukturyzacja `api_manager`.
- **Tylko Grok** — B8 embeddingi z xAI lub lokalne; **bez nowych ciężkich zależności** (B8 brute-force KNN,
  nie `sqlite-vec`/torch; B7 sandbox = launchery systemowe `bwrap`/`sandbox-exec`, nie biblioteki).
- **Import niczego nie odpala** (B5): serwery MCP z `~/.claude.json`/`.mcp.json` instalują się **disabled**
  (reżim M16); start = osobna gejtowana akcja.
- **Hartowanie podprocesów** (B7) zachowuje `scrubbed_env`+`_tree_kill`; sandbox to DODATKOWA warstwa.
- **Stan przez** `config.load_json_or_backup` + `atomic_write_text`; współdzielenie WS↔REST jak checkpointy/LSP.
- **Tekst UI po angielsku**; komentarze/docstringi mogą być po polsku. **UTF-8** w embeddings/SSE.
- **„Selfcheck albo się nie stało":** każdy element ma asercje (rozszerzone istniejące suity lub nowe).
- **Brak eskalacji** (B6): role `effective_tools` = rola ∩ rodzic; subagenci bez `delegate` (głębia 1).

---

## 7. Akceptacja zbiorcza Tier-2

| Element | Backend selfcheck | Frontend | Na żywo (maszyna usera) |
|---|---|---|---|
| B5 interop | `agent_selfcheck` (caelo_md) + `mcp_check` + `api_smoke` (skille) | (opcjonalnie panel źródeł) | projekt z `CLAUDE.md`/`.mcp.json` działa |
| B6 skille | `api_smoke` (builtiny) + `agent_selfcheck` (role) | komendy `/implement` w composerze | pętla delegacji end-to-end |
| B7 sandbox | nowy `sandbox_check` (profile + `wrap()`) | (panel profilu, opcj.) | Landlock/Seatbelt blokuje zapis |
| B8 pamięć | `history_check` (KNN+hybryda, stub embedder) | (opcjonalnie UI pamięci) | xAI embeddings + recall |

---

## 8. Ryzyka i szacunki

| Element | Wysiłek | Główne ryzyko | Mitigacja |
|---|---|---|---|
| B5 | M | workspace-aware rebuild skills/mcp; mapowanie kształtu Claude | wzorzec `get_lsp`; tolerancyjny parser |
| B6 | M | jakość promptów; zależność `pr-babysit` od GitHub MCP | iteracja live; oznaczyć zależność |
| B7 | L | platformowość sandboxa; regresja `run_command` | per-komenda + off-by-default; graceful no-op |
| B8 | M | dostępność endpointu embeddings xAI | spike PRZED implementacją; gate B8 na wynik |

---

## 9. Otwarte pytania / spike'i

- **[SPIKE] xAI embeddings:** czy `POST /v1/embeddings` (`embedding-beta-3-small`/inny) działa na naszym
  auth? Model/wymiary/koszt? **Klient + cały mechanizm B8 GOTOWE (stub); pozostaje potwierdzenie live na
  maszynie usera:** `python caelo_core/tools/embeddings_check.py --live` → `probe()` raportuje `{ok,model,dim}`.
  Jeśli endpoint nie istnieje (404) — B8 zostaje na stubie/odłożone (NIE wprowadzać torch/transformers).
- **[SPIKE] Sandbox platformowy:** `bwrap` (zależność systemowa, prosty) vs Landlock-ctypes (zero zależności,
  trudny) na Linux; `sandbox-exec` na macOS (deprecated, ale działa). Per-komenda vs in-process. Rozstrzygnąć
  w spike przed B7.
- **Workspace-aware skills/mcp (B5):** rebuild na `set_workspace` (jak LSP) vs skanowanie per-zapytanie.
  Rekomendacja: rebuild (spójne z `get_lsp`).
- **B8 domyślność:** pamięć semantyczna włączona domyślnie czy opt-in (`--experimental-memory` jak CLI)?
  Rekomendacja: opt-in na start (koszt embeddingów + prywatność).
- **`pr-babysit` (B6):** zależy od GitHub MCP/`gh` — dostarczyć jako skill z jawną zależnością czy odłożyć?
- **`inspect` (B5):** dodać `/inspect` (co odkryto + źródło) teraz czy później? Rekomendacja: po B5 (debug interopu).

---

*Dokument towarzyszy [`PLAN_M19_PARYTET_GROK_CLI.md`](PLAN_M19_PARYTET_GROK_CLI.md) (§5) i [`PLAN_M19_TIER1.md`](PLAN_M19_TIER1.md).
Aktualizować status w nagłówku przy realizacji. Punkty styku zweryfikowane w kodzie 2026-06-06.*
