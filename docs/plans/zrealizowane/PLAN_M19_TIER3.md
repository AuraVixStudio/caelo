# PLAN_M19_TIER3.md — Pełny plan implementacyjny Tier-3 (quick-winy)

> Rozwinięcie §6 z [`PLAN_M19_PARYTET_GROK_CLI.md`](PLAN_M19_PARYTET_GROK_CLI.md) do poziomu
> implementacyjnego (konkretne pliki, sygnatury, ramki, kroki, selfchecki, akceptacja). Sześć
> elementów **[P3]** (quick-winy / nisza), domykających parytet z oficjalnym Grok CLI:
> **B9 effort · B10 eksport/import sesji + auto-compact · B11 persony + I/O schema · B12 realne
> git worktree · B13 web tools w agencie · B14 config projektowy hierarchiczny**.
>
> **Zakłada gotowe:** M10 (`responses_client`), M13 (tryby/checkpointy/CAELO.md), M14 (MCP/skille/
> komendy/hooki), M17 (subagenci/role/`TeamManager`/worktree), oraz **Tier-1** (§0 `AgentRunner`,
> B1 headless, B2 ACP, B3 LSP, B4 reguły glob `RuleSet`) i **Tier-2** (B5 interop, B6 skille-
> orkiestratory, B7 sandbox OS, B8 pamięć hybrydowa). Wzorce do reużycia: workspace-aware lazy
> rebuild (`get_lsp`/`reload_lsp`), `AgentRunner` jako jedyny producent okablowania, `RuleSet`
> z B4 (już ma matcher `WebFetch(domain:…)`), `config.load_json_or_backup`+`atomic_write_text`.
>
> Tagi: **[P3]** quick-win / nisza. Wysiłek: **S** ≈ dni · **M** ≈ 1–2 tyg. · **L** ≈ 3–4 tyg.
>
> **STATUS (2026-06-07): ✅ TIER-3 KOMPLETNY — B9 + B10 + B11 + B12 + B13 + B14 ZROBIONE** (na
> stubie/mocku, selfchecki zielone). Świadomie odłożone (decyzje §11): `web_search` (B13 — został sam
> `web_fetch`), walidacja `outputs` w streszczeniu subagenta (B11), LLM-summary auto-compact (B10).
> Pozostają **weryfikacje LIVE u usera** (sandbox blokuje sieć/xAI): effort na realnym xAI, jakość
> delegacji z kontraktem I/O, realne `git worktree`/`web_fetch`, monorepo discovery. Rozpisy: §1–§6.

---

## 0. Wynik weryfikacji repo (punkty styku, stan na 2026-06-07)

Każda luka potwierdzona w kodzie — punkty styku gotowe do rozpisu:

| Element | Stan / plik | Wniosek dla Tier-3 |
|---|---|---|
| **B9** effort | **brak** — 0 trafień `reasoning_effort` w [`responses_client.py`](../../../caelo_core/responses_client.py:249)/[`agent/llm.py`](../../../caelo_core/agent/llm.py:15)/[`session.py`](../../../caelo_core/agent/session.py:271) | dodać param `reasoning_effort` w obu klientach + przeprowadzić przez `AgentSession`/`AgentRunner`/role; pole xAI = live-verify |
| **B10** eksport sesji | **brak** — [`routes/history.py`](../../../caelo_core/routes/history.py) ma tylko list/get/content; headless sesje = `DATA_DIR/sessions/<id>.json` ([`headless.py:55`](../../../caelo_core/headless.py:55)); czaty w `localStorage` (`useConversations`) | `GET /history/export` (md) + serializer renderera + (osobno) auto-compact w `session.py` |
| **B11** persony + I/O schema | **częściowo** — [`roles.py`](../../../caelo_core/agent/roles.py:37) łączy capability+tools+`prompt`; brak `instructions`/`inputs`/`outputs` (jak `bundled/personas/*.toml`: `instructions`+`reasoning_effort`) | rozszerzyć `_clean_role` o `instructions`/`inputs`/`outputs`; `team.py` wstrzykuje kontrakt I/O |
| **B12** realne git worktree | **brak** — [`worktree.py`](../../../caelo_core/agent/worktree.py:41) = `copy_worktree` (kopia katalogu, bez gita); CLI ma `--worktree [NAME]` | wariant `git worktree add`/`remove` obok kopii, gdy workspace = repo (opcja, nie zamiennik) |
| **B13** web tools w agencie | **brak** — [`tools.py:62`](../../../caelo_core/agent/tools.py:62) `TOOLS` nie ma web; czat ma `web_search`/`x_search` przez Responses (M10). `RuleSet` z B4 **już** ma matcher `WebFetch(domain:…)` | `web_fetch` (https-only + allowlista domen + cap) + opcjonalnie `web_search`; mapowanie `web_fetch`→`WebFetch` w `targets_for_tool` |
| **B14** config hierarchiczny | **częściowo** — [`caelomd.py`](../../../caelo_core/agent/caelomd.py) czyta root+global (B5: +AGENTS/CLAUDE), `state.py` czyta `<ws>/.caelo/{lsp,permissions,sandbox}.json`; **brak walk cwd→root** + odkrycia korzenia repo (`.git`) | walk root↔cwd (deeper-wins) dla CAELO.md i `.caelo/*.json` + `find_project_root` dla headless `--cwd` |

**Już mamy (nie ruszać):** B4 `RuleSet` (deny>allow, matcher `*`/`**`, `WebFetch`/`MCPTool`), B5
interop discovery + workspace-aware rebuild, M17 worktree-jako-kopia + `MergeStore` + `delegate`,
M10 `responses_client.stream_response` (pętla narzędzi, UTF-8 SSE), headless `_resolve_tools`/
`_resolve_session`/`_apply_rules`, bezpieczeństwo fail-closed + scrubbed env + tree-kill.

---

## 1. ✅ B9 — Poziomy effort (`reasoning_effort`) per tryb/agent — ZROBIONE 2026-06-07 — **[P3] S**

**Cel:** sterowanie `reasoning_effort` (`low`/`medium`/`high`) dla modeli rozumujących — globalnie
(czat + agent), per rola subagenta (CLI persony mają `reasoning_effort = "high"`) i z CLI
(`--effort`). Tani, samodzielny; jedyna niepewność = nazwa pola na drucie xAI (live-verify).

### 1.1 Klienci (dwie ścieżki inferencji)
- [`responses_client.py`](../../../caelo_core/responses_client.py:249) `stream_response`: dodaj param
  `reasoning_effort: Optional[str] = None`. W `_run_turn` (budowa `payload`, [linia 309](../../../caelo_core/responses_client.py:309)):
  `if reasoning_effort: payload["reasoning"] = {"effort": reasoning_effort}`. **Tylko gdy podane**
  — modele nie-rozumujące mogłyby dać 422 (zasada „minimalny payload", jak `build_search_tools`).
- [`agent/llm.py`](../../../caelo_core/agent/llm.py:15) `stream_chat_with_tools`: dodaj
  `reasoning_effort: Optional[str] = None`; gdy podane → `payload["reasoning_effort"] = ...`
  (format chat/completions; **wariant pola = live-verify** — czat/Responses mogą różnić się
  kształtem, jak komentarz o `include_usage` w [llm.py:33](../../../caelo_core/agent/llm.py:33)).

### 1.2 Przeprowadzenie przez agenta
- [`session.py`](../../../caelo_core/agent/session.py): `AgentSession.__init__` dostaje
  `reasoning_effort: Optional[str] = None` (pole `self._reasoning_effort`). `run_turn` przekazuje
  je do `self.llm_fn(...)` ([linia 324](../../../caelo_core/agent/session.py:324)) jako kwarg
  `reasoning_effort=self._reasoning_effort`. **Additywne** — mock LLM w selfcheckach łyka `**_`.
- [`runner.py`](../../../caelo_core/agent/runner.py): `AgentRunner.__init__` dostaje `reasoning_effort`
  (jak `max_iters`); `_ensure_session` ([linia 102](../../../caelo_core/agent/runner.py:102)) przekazuje do `AgentSession`.
- **Per rola (B11-spójne):** [`roles.py`](../../../caelo_core/agent/roles.py): `_clean_role`
  ([linia 203](../../../caelo_core/agent/roles.py:203)) waliduje pole `reasoning_effort` (∈
  `{"low","medium","high",""}`, inne → `""`); `BUILTIN_ROLES` dostają rozsądne wartości
  (researcher/security-auditor = `high`, tester = `low`). [`team.py`](../../../caelo_core/agent/team.py:153)
  `SubAgent.run`: przekaż `reasoning_effort=self.role.get("reasoning_effort") or None` do
  `AgentSession` (rola nadpisuje globalny; brak → globalny/None).

### 1.3 Czat + wejścia + UI
- [`routes/chat.py:142`](../../../caelo_core/routes/chat.py:142): dodaj `reasoning_effort=` do wywołania
  `stream_response` — z pola żądania (`chat.reasoning_effort`) z fallbackiem na `caelo_settings.json`.
- [`headless.py`](../../../caelo_core/headless.py): `_build_parser` — flagi `--effort`/`--reasoning-effort`
  (`choices=["low","medium","high"]`); `_run` przekazuje do `AgentRunner(reasoning_effort=…)`.
- [`config.py`](../../../config.py): domyślne w settings (`chat_effort`/`code_effort`); **nie nowy
  root-moduł** — tylko klucz w `caelo_settings.json` (czytany jak `code_model`).
- **Frontend:** selektor Low/Med/High w `CodeView.tsx` (agent) i composerze czatu; `lib/api.ts`
  (`reasoning_effort` w typie żądania); panel **Subagents** (per-rola). **Tekst UI = EN.**

### 1.4 Selfcheck + akceptacja
- `agent_selfcheck.py`: effort dochodzi do `llm_fn` (mock sprawdza kwarg); rola z
  `reasoning_effort` nadpisuje globalny; brak pola → kwarg `None` (zero regresji).
- `api_smoke.py`: czat z `reasoning_effort` buduje `payload["reasoning"]` (mock transport).
- `headless_check.py`: `--effort high` dociera do runnera.
- **Akceptacja:** selfchecki zielone; **live (maszyna usera):** czy realny xAI akceptuje
  `reasoning.effort` (Responses) / `reasoning_effort` (chat) — potwierdzić pole, inaczej zostać przy
  jednej ścieżce.

### ✅ Realizacja (2026-06-07)
- **Wspólny walidator:** [`validation.py`](../../../caelo_core/validation.py) — `REASONING_EFFORTS` +
  `normalize_effort(v)` (→ `low`/`medium`/`high` albo `None`; leaf, bez cykli). Reużywany przez obie
  ścieżki inferencji, role i trasy — **pole dokładane TYLKO gdy poprawne** (modele nie-rozumujące →
  brak 4xx).
- **Klienci:** [`responses_client.stream_response`](../../../caelo_core/responses_client.py) — param
  `reasoning_effort` → `payload["reasoning"]={"effort":…}`; [`agent/llm.stream_chat_with_tools`](../../../caelo_core/agent/llm.py)
  — param `reasoning_effort` → `payload["reasoning_effort"]` (wariant pola czat vs Responses = live-verify).
- **Agent:** [`session.py`](../../../caelo_core/agent/session.py) `AgentSession` — `reasoning_effort` w
  `__init__` (domyślny sesji) **+ override per-tura** w `run_turn`; kwarg do `llm_fn` przekazywany
  **warunkowo** (mock bez parametru → zero regresji). [`runner.py`](../../../caelo_core/agent/runner.py)
  `AgentRunner` — domyślny w `__init__` + per-tura w `run_turn`, przepuszczany do sesji i delegacji.
- **Role/subagenci:** [`roles.py`](../../../caelo_core/agent/roles.py) — `_clean_role` waliduje
  `reasoning_effort`; `BUILTIN_ROLES` mają wartości (researcher/reviewer/implementer/design-*/
  security-auditor = `high`, test-writer = `medium`, tester = `low`). [`team.py`](../../../caelo_core/agent/team.py)
  — `TeamManager.run(reasoning_effort=…)`; `SubAgent` używa **effortu roli > globalnego przebiegu**.
- **Czat + headless + ustawienia:** [`routes/chat.py`](../../../caelo_core/routes/chat.py) czyta
  `reasoning_effort` z ramki + fallback `chat_effort`; [`routes/agent.py`](../../../caelo_core/routes/agent.py)
  — pole `effort` w ramce `message` + fallback `code_effort`; [`headless.py`](../../../caelo_core/headless.py)
  — flaga `--effort`/`--reasoning-effort`; [`routes/settings.py`](../../../caelo_core/routes/settings.py) —
  `chat_effort`/`code_effort` w `SettingsPatch`+`GET /settings` (walidowane przy zapisie, śmieć → `""`).
- **Frontend:** nowy [`ui/EffortSelect.tsx`](../../../desktop/src/renderer/src/components/ui/EffortSelect.tsx)
  (Auto/Low/Medium/High, wzór `ModeSelector`) — w composerze **czatu** ([`ChatView.tsx`](../../../desktop/src/renderer/src/components/ChatView.tsx),
  utrwala `chat_effort`) i **agenta** ([`AgentPanel.tsx`](../../../desktop/src/renderer/src/components/code/AgentPanel.tsx),
  per-tura); per-rola w **Extensions → Subagents** ([`SubagentsPanel.tsx`](../../../desktop/src/renderer/src/components/extensions/SubagentsPanel.tsx)).
  Typy `ReasoningEffort`/`SettingsResp`/`SettingsPatch`/`ChatStreamPayload`/`TeamRole` w
  [`lib/api.ts`](../../../desktop/src/renderer/src/lib/api.ts); `effort` w `AgentConnection.sendMessage`.
- **Selfchecki:** `agent_selfcheck` `test_reasoning_effort` (+10: normalize, domyślny/override/None,
  brak kwargu bez effortu, role+walidacja, payload llm) — mocki team dostały `**_` (tolerują nowy kwarg,
  jak realny klient); `api_smoke` smoke_chat (+2: `reasoning.effort` w payloadzie Responses, effort z
  ramki czatu → `stream_response`); `headless_check` `test_effort` (+2: `--effort` dociera / brak = brak
  kwargu). **Cała bateria zielona** (agent/headless/acp/api_smoke/mcp/lsp/sandbox/packages/genjobs/
  history/embeddings/crossplatform/handshake). Frontend: **typecheck (node+web) ✓, lint 0 błędów,
  vitest 155/155 ✓**, podgląd (`preview:web`+devMock): selektor renderuje się w czacie i agencie,
  wybór „High" aktualizuje etykietę, **0 błędów konsoli**.
- **Odłożone do live (maszyna usera):** potwierdzenie pola na realnym xAI — `reasoning.effort`
  (Responses) vs `reasoning_effort` (chat/completions); do tego czasu pole jest opcjonalne i dokładane
  tylko gdy poprawne (brak ryzyka 4xx na modelach nie-rozumujących).

---

## 2. ✅ B10 — Eksport sesji do markdown + auto-compact — ZROBIONE 2026-06-07 — **[P3] S**

Dwie niezależne pod-funkcje; (a) tania i samodzielna, (b) nieco głębsza.

### 2.1 (a) Eksport historii/sesji do markdown
- **Hub (agent + czat zapisane jako zdarzenia M9):** [`routes/history.py`](../../../caelo_core/routes/history.py):
  nowy `GET /history/export` (te same filtry co `/history`: `q`/`mode`/`project_id`/`from`/`to`)
  → `text/markdown` (FastAPI `PlainTextResponse`/`Response(media_type="text/markdown")`). Buduje md
  z `b.history_store.list_events(...)` (nagłówek + per zdarzenie: data, tryb, prompt z `meta`, tekst).
  Czysta funkcja `events_to_markdown(events) -> str` (testowalna bez HTTP).
- **Sesje headless (`DATA_DIR/sessions/<id>.json`):** [`headless.py`](../../../caelo_core/headless.py):
  subkomenda-flaga `--export-md <path>` (lub osobne `caelo run --export <id>`), serializująca
  `history` sesji do md (reużyj `events_to_markdown`-stylowy serializer wiadomości role→md). Import:
  `--import-md` odłożony (md→historia jest stratne; rekomendacja: tylko eksport, import przez `-r`/`-c`).
- **Czat (renderer `localStorage`/`useConversations`):** eksport po stronie renderera — nowy
  `lib/exportMarkdown.ts` (`conversationToMarkdown(conv) -> string`) + przycisk „Export .md" w UI
  czatu (Blob download). **Bez backendu** (czaty nie są w sidecarze — P2-8). Selfcheck: Vitest
  (czysta funkcja).
- **Selfcheck:** `api_smoke` `_unit_history_export` (md zawiera prompty + odpowiedzi, filtry działają);
  Vitest dla `conversationToMarkdown`.

### 2.2 (b) Auto-compact progu kontekstu
- **Problem:** [`session.py`](../../../caelo_core/agent/session.py:160) `self.history` rośnie bez ograniczeń
  — długie sesje (headless `-c`, ACP, wielotura) puchną i drożeją.
- **Rozwiązanie:** w `run_turn`, PRZED budową `messages` ([linia 323](../../../caelo_core/agent/session.py:323)),
  gdy szacowany rozmiar historii > próg → **compaction**: zwiń najstarsze pary user/assistant/tool
  w jeden blok `system`/`user` „[Summary of earlier conversation] …" (jedno tanie wywołanie LLM
  *albo* deterministyczne obcięcie+nota, by nie zależeć od sieci w selfchecku). Zachowaj balans
  historii (kontrakt xAI: każda `assistant` z `tool_calls` ma `tool` — kompaktuj tylko KOMPLETNE,
  zamknięte segmenty, nigdy nie rozcinaj pary tool_call↔tool).
- **Opt-in / próg:** `config.py` `AGENT_AUTOCOMPACT` (env `CAELO_AUTOCOMPACT`, domyślnie OFF) +
  `AGENT_COMPACT_THRESHOLD_CHARS`. Mały, izolowany helper `_maybe_compact()`; błąd połknięty
  (nigdy nie wywraca tury — jak `_maybe_inject_memory`).
- **Selfcheck:** `agent_selfcheck.test_autocompact` (mock LLM: historia > próg → zwinięta, balans
  tool zachowany, off = brak zmian).
- **Akceptacja:** eksport md działa (hub + czat); auto-compact zwija przy progu, zachowując balans;
  off = zero zmian. **Live:** jakość streszczenia (maszyna usera).

### ✅ Realizacja (2026-06-07)
**(a) Eksport do Markdown** — trzy cele, wszystkie zrobione:
- **Hub:** [`routes/history.py`](../../../caelo_core/routes/history.py) — czysta funkcja `events_to_markdown`
  (+`_iso`) i trasa `GET /history/export` (te same filtry co `/history`, `text/markdown` jako
  załącznik). Prompt/model dołączane z `meta` przez nową metodę
  [`history_store.event_metas`](../../../caelo_core/history_store.py) (meta żyje w `history_fts`, nie w
  `HistoryEvent`; jeden przebieg kursora z wczesnym zakończeniem). [`api.ts`](../../../desktop/src/renderer/src/lib/api.ts)
  `exportHistoryMarkdown` (surowy fetch tekstu z Bearer) + przycisk **Export .md** w
  [`History.tsx`](../../../desktop/src/renderer/src/components/History.tsx) (eksportuje bieżący filtr).
- **Sesje headless:** [`headless.py`](../../../caelo_core/headless.py) — flaga `--export-md <path>` (osobna,
  czysta ścieżka bez Backendu/sieci; `-p` stał się opcjonalny — wymagany tylko dla biegu); czysty
  serializer `history_to_markdown` (user/assistant/tool + tool-calls); `_export_session` (wybór sesji
  `-s`/`-r`/`-c`).
- **Czat (renderer):** nowy [`lib/exportMarkdown.ts`](../../../desktop/src/renderer/src/lib/exportMarkdown.ts)
  — `conversationToMarkdown` (czysta, z cytowaniami), `safeFilename`, `downloadText` (Blob → pobranie);
  przycisk **Export chat as Markdown** w [`ChatView.tsx`](../../../desktop/src/renderer/src/components/ChatView.tsx)
  (wyłączony gdy brak wiadomości). Import md → **świadomie odłożony** (md→historia stratne; wznawianie
  przez `-r`/`-c`/`session/load`, decyzja §11).

**(b) Auto-compact** — [`config.py`](../../../config.py) `AGENT_AUTOCOMPACT` (env `CAELO_AUTOCOMPACT`,
**domyślnie OFF**) + `AGENT_COMPACT_THRESHOLD_CHARS`. [`session.py`](../../../caelo_core/agent/session.py):
czyste helpery + `compact_history` (zwija najstarsze tury, **cięcie NA GRANICY `user`** → balans
tool_call↔tool zachowany; digest deterministyczny, bez sieci, capowany) + metoda `_maybe_compact`
wołana w `run_turn` przed budową `messages` (bieżąca tura zawsze zachowana; błąd połknięty). Off =
zwraca historię bez zmian (zero regresji). Wariant LLM-summary za flagą = odłożony (decyzja §11).

**Selfchecki:** `api_smoke`/smoke_routes (+4: `/history/export` → markdown, tekst+prompt+model z meta,
filtr trybu); `headless_check` `test_export` (+4: `--export-md` zapisuje user+assistant, brak sesji →
rc 2, `history_to_markdown` z tool-calls); `agent_selfcheck` `test_autocompact` (+9: shrink, blok-
summary, balans, rozmiar, ostatnia tura nietknięta, off, pod-progiem, integracja AgentSession on/off);
Vitest `exportMarkdown.test.ts` (+7: tytuł/tury/cytowania/puste/fallback + `safeFilename`). **Cała
bateria zielona** (agent/headless/api_smoke/history/acp/mcp/lsp/sandbox/genjobs/embeddings/packages).
Frontend: **typecheck (node+web) ✓, lint 0 błędów, vitest 162/162 ✓**, podgląd (`preview:web`):
eksport czatu **end-to-end** (pobranie `…-export-test.md`, `text/markdown`, 93 B), przyciski w czacie
i History renderują się, **0 błędów konsoli**.

**Odłożone do live (maszyna usera):** jakość deterministycznego streszczenia auto-compact w długiej,
realnej sesji (opt-in) — ewentualnie podłączyć LLM-summary za flagą, jeśli digest okaże się za ubogi.

---

## 3. ✅ B11 — Persony + I/O schema dla subagentów — ZROBIONE 2026-06-07 — **[P3] S–M**

**Cel:** warstwa persony nad rolami M17 (jak `bundled/personas/*.toml`: `instructions` +
`reasoning_effort`) oraz **kontrakt I/O** (`inputs`/`outputs`), by delegacja była przewidywalna —
orkiestrator wie, co podać i co dostanie z powrotem.

### 3.1 Model danych ([`roles.py`](../../../caelo_core/agent/roles.py))
- `_clean_role` ([linia 203](../../../caelo_core/agent/roles.py:203)) — dodaj pola:
  - `instructions: str` — wielolinijkowa persona (rozszerzenie obecnego `prompt`; gdy brak, `prompt`
    pozostaje). Cap rozmiaru jak CAELO.md.
  - `inputs: list[{name, description, required:bool}]` — czego subagent oczekuje od orkiestratora.
  - `outputs: list[{name, description}]` — co subagent ma zwrócić (struktura streszczenia).
  - `reasoning_effort` — wspólne z B9.
  - Walidacja tolerancyjna (zła pozycja → pominięta), limit liczby pól (np. ≤16).
- `BUILTIN_ROLES` — uzupełnij istniejące role o `outputs` (np. reviewer → `[{name:"findings"},
  {name:"verdict"}]`); persony wzorowane na `bundled/personas/*.toml`.
- `RoleRegistry.upsert_role`/`_save` już persistują dowolne oczyszczone pola (atomowo) — bez zmian.

### 3.2 Wstrzyknięcie kontraktu ([`team.py`](../../../caelo_core/agent/team.py:153))
- `SubAgent.run`: zbuduj `extra_system` = `role.instructions or role.prompt` + sekcja kontraktu I/O,
  gdy zdefiniowano (`"Inputs you were given: …\nProduce these outputs in your summary: …"`). Zadanie
  (`self.task`) pozostaje treścią użytkownika; kontrakt jest deterministyczną ramą promptu (EN).
- **Bez eskalacji:** `effective_tools` = rola ∩ rodzic — niezmienione; persona to tylko prompt.
- (Opcjonalnie, odłożone) walidacja `outputs` w streszczeniu — na razie tylko prompt-steering.

### 3.3 UI + selfcheck
- **Frontend:** edytor ról w **Extensions → Subagents** (`SubagentsConfig`/odpowiednik) — pola
  Instructions (textarea) + Inputs/Outputs (lista name/description) + Effort. `lib/api.ts` typy ról.
- **Selfcheck:** `api_smoke`/`agent_selfcheck` — round-trip roli z `instructions`/`inputs`/`outputs`
  (zapis→odczyt), `team` wstrzykuje kontrakt do `extra_system`, brak eskalacji utrzymany.
- **Akceptacja:** role z personą+I/O zapisują/odczytują się; kontrakt w prompcie subagenta;
  brak regresji M17 (zakres ∩ rodzic). **Live:** jakość delegacji z kontraktem (maszyna usera).

### ✅ Realizacja (2026-06-07)
- **Model danych:** [`roles.py`](../../../caelo_core/agent/roles.py) — `_clean_role` dostał `instructions`
  (cap `MAX_INSTRUCTIONS`), `inputs`/`outputs` (czyszczone `_clean_io`: drop bez `name`, `io_type`∈
  {text,file} inaczej `text`, `required` bool, limit `MAX_IO_FIELDS`, cap opisu). Nowy
  `_normalize_role` (w `get()`/`list()`) gwarantuje pełny, spójny kształt też dla ról WBUDOWANYCH
  (surowe dict-y). Helpery: `role_persona` (instructions > prompt — fallback wsteczny M17),
  `role_io_contract` (deterministyczna rama EN), `role_system_prompt` (persona + kontrakt).
- **Role wbudowane:** każda dostała sensowne `outputs` (reviewer → findings+verdict, security-auditor
  → findings, researcher → findings, tester → results, …) + `inputs` tam, gdzie ma sens (implementer/
  design-doc-writer → opcjonalny `review_file`, design-doc-reviewer → `design_doc`). Persony wzorowane
  na `bundled/personas/*.toml` z Grok CLI.
- **Wstrzyknięcie:** [`team.py`](../../../caelo_core/agent/team.py) `SubAgent.run` używa
  `role_system_prompt(self.role)` jako `extra_system` (zamiast samego `prompt`). Bez eskalacji
  (`effective_tools` = rola ∩ rodzic — niezmienione).
- **Trasa (naprawa luki B9 przy okazji):** [`routes/team.py`](../../../caelo_core/routes/team.py) `RoleReq`
  **nie miał** `reasoning_effort` (per-rola effort z UI był dropowany przez Pydantic!) — dodano
  `reasoning_effort` + `instructions` + `inputs` + `outputs`; walidacja w `_clean_role`.
- **Frontend:** [`api.ts`](../../../desktop/src/renderer/src/lib/api.ts) `TeamRoleIO` + pola w `TeamRole`;
  [`SubagentsPanel.tsx`](../../../desktop/src/renderer/src/components/extensions/SubagentsPanel.tsx) — pole
  **Instructions (role persona)** (edytuje `instructions`; init z `prompt` dla builtinów — fallback) +
  komponent `IoListEditor` (name / typ text|file / req / description + Add/Remove) dla **Inputs** i
  **Outputs**. `blankRole()` uzupełniony.
- **Selfchecki:** `agent_selfcheck` `test_persona_io` (+11: walidacja `_clean_role`/`_clean_io`,
  fallback persony, kontrakt, system prompt, normalizacja builtinów, reviewer findings+verdict,
  round-trip rejestru); `api_smoke`/smoke_routes (+1: `/team/roles` round-trip effort+persona+I/O
  przez `RoleReq`). **Cała bateria zielona** (agent/api_smoke/headless/acp/mcp/lsp/sandbox/genjobs/
  embeddings/packages/history). Frontend: **typecheck (node+web) ✓, lint 0 błędów, vitest 162/162 ✓**,
  podgląd (`preview:web`): edytor renderuje Instructions + Inputs/Outputs (+effort), „Add field" dodaje
  wiersz z name/typ(file)/req/description, **0 błędów konsoli**.
- **Odłożone (świadomie, decyzja §11):** walidacja `outputs` w faktycznym streszczeniu subagenta —
  na razie tylko prompt-steering. **Live:** jakość delegacji z kontraktem (maszyna usera).

---

## 4. ✅ B12 — Opcja realnych `git worktree` — ZROBIONE 2026-06-07 — **[P3] S**

**Cel:** dla workspace będącego repo git — użyć `git worktree` zamiast kopii katalogu (M17):
szybciej (brak kopiowania), naturalny diff, integracja z gitem. **Opcja, NIE zamiennik** — kopia
zostaje domyślną (działa, gdy workspace nie jest repo / brak gita).

### 4.1 Wariant git w [`worktree.py`](../../../caelo_core/agent/worktree.py)
- `is_git_repo(root) -> bool` (sprawdź `.git` lub `git -C root rev-parse`).
- `create_worktree(src_root, dest_root, *, use_git: bool)`:
  - `use_git and is_git_repo` → `git -C <src> worktree add --detach <dest> HEAD` (scrubbed env +
    tree-kill jak `run_command`; **NIE** sandbox in-process — to git lokalny). Zwróć rodzaj („git").
  - inaczej → istniejące `copy_worktree` (fallback). Zwróć rodzaj („copy").
- `compute_changes` dla git: `git -C <wt> add -A && git -C <wt> diff --cached` (lub `git status
  --porcelain` + `git diff`) — **ale** zachowaj wspólny kształt zwrotu (`{files, diff, paths}`), by
  `MergeStore`/UI nie wiedziały, który wariant. Dla kopii — bez zmian.
- `discard_worktree` dla git: `git -C <src> worktree remove --force <dest>` (+ `worktree prune`);
  dla kopii — `shutil.rmtree` (bez zmian).
- `apply_changes` — bez zmian (pisze zmienione pliki do realnego workspace przez sandbox +
  snapshot do checkpointu M13; działa identycznie dla obu wariantów = scalenie cofalne).

### 4.2 Wpięcie + config
- [`team.py`](../../../caelo_core/agent/team.py:193) `_workspace_for_role`/`new_worktree_path`: wybór
  wariantu z flagi zespołu/configu; `_finalize_worktree`/`_cleanup_worktree` wołają warianty
  `discard`. `worktrees_base` bez zmian (`config.WORKTREES_DIR`).
- `config.py` `AGENT_GIT_WORKTREE` (env `CAELO_GIT_WORKTREE`, domyślnie OFF → kopia); headless flaga
  `--worktree` (parytet CLI `--worktree [NAME]`).
- **Bezpieczeństwo:** worktree git współdzieli `.git`; to wciąż lokalne, sandboxowane przy SCALANIU
  (`Workspace.resolve`). `IGNORE_DIRS` zawiera `.git` — przy git-worktree nie kopiujemy plików, więc
  nie ma ryzyka rekurencji.

### 4.3 Selfcheck + akceptacja
- Nowy/rozszerzony selfcheck: **guard `is_git_repo`** — gdy brak gita w środowisku selfchecka,
  testuj tylko fallback do kopii (skip git-ścieżki z notą, nie fail). Asercje: kształt zwrotu
  `compute_changes` identyczny dla git i kopii; `discard` sprząta; fallback gdy nie-repo.
- **Akceptacja:** kopia bez zmian (domyślnie); git-worktree tworzy/diffuje/sprząta, gdy repo + flaga.
  **Live:** realne `git worktree add/remove` na repo usera.

### ✅ Realizacja (2026-06-07)
- **Warstwa git** w [`worktree.py`](../../../caelo_core/agent/worktree.py): `is_git_repo` (top-level repo,
  nie podkatalog — przez `git rev-parse --show-toplevel`), `create_worktree(src, dest, *, use_git)`
  (`git worktree add --detach HEAD` gdy repo+flaga, inaczej `copy_worktree`; zwraca rodzaj
  `'git'|'copy'`), `_compute_changes_git` (`git add -A` + `git diff --cached --no-renames
  --name-status` → A/M/D → created/modified/deleted; `git diff --cached` jako tekst). Operacje git:
  `scrubbed_env` + shell=False + timeout; każda porażka → **graceful fallback do kopii** (nigdy nie
  wywraca delegacji).
- **Wspólny kształt:** `compute_changes(orig, wt, *, kind)` dyspozytuje (git→`git diff`, inaczej
  porównanie drzew) zwracając **identyczne** `{files,diff,paths}` — `MergeStore`/UI nie wiedzą, który
  wariant. `apply_changes` **bez zmian** (czyta pliki z worktree → zapis przez sandbox + snapshot M13
  = scalenie cofalne). `discard_worktree(wt, *, kind, src_root)`: git → `git worktree remove --force`
  + `prune`; inaczej `rmtree`.
- **Wpięcie** [`team.py`](../../../caelo_core/agent/team.py): `SubAgent._workspace_for_role` woła
  `create_worktree(..., use_git=self.team.use_git_worktree)` i zapamiętuje `_worktree_kind`;
  `_finalize_worktree`/`_cleanup_worktree` przekazują `kind`+`src_root`. `PendingMerge`/`MergeStore`
  niosą `kind`+`src_root`, więc apply/reject/clear sprzątają właściwym wariantem (brak osieroconych
  wpisów `.git/worktrees`). `TeamManager.use_git_worktree` z `config.AGENT_GIT_WORKTREE`, odświeżane
  w `run()`.
- **Config + flaga:** [`config.py`](../../../config.py) `AGENT_GIT_WORKTREE` (env `CAELO_GIT_WORKTREE`,
  **domyślnie OFF** → kopia); headless [`--worktree`](../../../caelo_core/headless.py) (parytet CLI
  `--worktree [NAME]`; ustawia flagę na bieg, jak `--sandbox`). **Bez UI** (plan: frontend opcjonalny).
- **Różnica semantyczna (świadoma, opt-in):** git-worktree startuje z **HEAD** (stan zacommitowany),
  kopia z bieżącego drzewa roboczego — przy włączonej opcji subagent pracuje od HEAD; diff liczony vs
  HEAD. Domyślnie OFF, więc zachowanie M17 niezmienione.
- **Selfchecki:** `agent_selfcheck` `test_git_worktree` (+14: fallback poza repo, kopia shape/discard,
  `is_git_repo`, realne `git worktree add`, created/modified/deleted, kształt = kopia, apply, `git
  worktree remove`+prune — pod guardem `shutil.which('git')`); `headless_check` `test_worktree_flag`
  (+1: `--worktree` włącza flagę). **Cała bateria zielona** (agent/headless/api_smoke/acp/mcp/lsp/
  sandbox/genjobs/history/embeddings/packages; git 2.40 w środowisku → ścieżka git faktycznie wykonana).
  Brak zmian frontu → typecheck/lint/vitest bez wpływu (B11 pozostaje zielony).
- **Live (maszyna usera):** realne `git worktree add/remove` w przebiegu delegacji z `--worktree`/
  `CAELO_GIT_WORKTREE=1` na repo usera.

---

## 5. ✅ B13 — Web tools w agencie (`web_fetch`) — ZROBIONE 2026-06-07 — **[P3] S**

**Cel:** agent (nie tylko czat) dostaje dostęp do sieci pod bramką: `web_fetch` (pobierz URL) i —
opcjonalnie — `web_search`. „Tylko Grok" + reżim bezpieczeństwa: https-only, allowlista domen,
cap rozmiaru, **bramka z prefiksem `WebFetch(domain:…)` z B4** (matcher już istnieje).

### 5.1 Narzędzia ([`tools.py`](../../../caelo_core/agent/tools.py:62))
- `TOOLS` += schemat `web_fetch` (`{url, max_bytes?}`) i (opcjonalnie) `web_search` (`{query}`).
- `web_fetch(ws, url, **_) -> str`: walidacja **https-only** + host w allowliście (reużyj wzorca
  pobrań mediów: `backend_media` `MAX_MEDIA_BYTES`/`requests` https-only + size-cap, P1-14) →
  GET (timeout, cap) → zwróć tekst (HTML→tekst minimalnie / surowo). Błąd → `"Error: …"` (generic,
  bez wycieku — `errors.upstream_error`).
- `web_search` (opcjonalne, „tylko Grok"): jedno wywołanie `responses_client.stream_response` z
  `tools=build_search_tools("on", ["web"])` i bez pętli MCP → zwróć tekst+cytowania jako string.
  (Alternatywa: odłożyć `web_search`, zostawić sam `web_fetch` — patrz §9.)
- `_EXECUTORS` += `web_fetch`/`web_search`.

### 5.2 Bramka + widoczność
- [`permissions.py`](../../../caelo_core/agent/permissions.py): `web_fetch`/`web_search` **NIE** READONLY
  bez bramki — to egress sieciowy. Traktuj jako mutujące-pod-bramką (lub osobna klasa) z prefiksem
  reguł `WebFetch`.
- [`permission_rules.py`](../../../caelo_core/agent/permission_rules.py): `targets_for_tool` mapuje
  `web_fetch` → `WebFetch` (target = URL/host) — matcher `_match_webfetch` (domain:+globy) **gotowy**
  z B4. `web_search` → `WebFetch` (target = `domain:search`) lub własny prefiks (decyzja §9).
- [`session.py`](../../../caelo_core/agent/session.py:228) `_all_tools`: **advertuj tylko gdy włączone**
  (config/`--disable-web-search` off) — wzorzec `lsp` (ukryte gdy brak, by model nie planował wokół
  niedostępnej zdolności). Bramka/deny przez istniejące ścieżki `_gate_mutation`/`evaluate_rules`.
- `config.py` `WEB_FETCH_ENABLED` + `WEB_FETCH_ALLOW_DOMAINS`; headless `--disable-web-search`
  (parytet CLI). Allowlista domen także przez reguły `--allow "WebFetch(domain:docs.rs)"`.

### 5.3 Selfcheck + akceptacja
- `agent_selfcheck.py` (mock `requests`): `web_fetch` https-only (http→reject), domain-allow rule
  auto-accept, deny twardo blokuje, cap rozmiaru, ukryte gdy wyłączone, advertowane gdy włączone.
- **Akceptacja:** narzędzia gated + ukrywalne; reguły `WebFetch` działają (deny>allow); P0-1
  nietknięte. **Live:** realny fetch (sandbox blokuje sieć) na maszynie usera.

### ✅ Realizacja (2026-06-07)
- **Zakres:** zrobione `web_fetch` (prosty, gated); **`web_search` świadomie odłożone** (decyzja
  §11 — wymaga przepięcia `responses_client`+klucza do egzekutora narzędzia; follow-up).
- **Egzekutor** [`tools.py`](../../../caelo_core/agent/tools.py) `web_fetch(ws, url, max_bytes=)`:
  **https-only**, **SSRF-guard** (`_web_host_blocked`: localhost/loopback/sieci prywatne/link-local/
  reserved/multicast jako literał IP), opcjonalna **twarda allowlista hostów**
  (`WEB_FETCH_ALLOW_DOMAINS`, subdomeny), **cap** rozmiaru + **re-walidacja po redirectach**
  (allowed→blocked), HTML→tekst (`_html_to_text`, bez nowej zależności), błąd sieci → **generyczny**
  komunikat (`type(exc).__name__`, surowy log). `import requests`+`config` w tools; `_EXECUTORS` += web_fetch.
- **Bramka** [`permissions.py`](../../../caelo_core/agent/permissions.py): `web_fetch` w **MUTATING** (egress,
  NIE readonly); klucz „Always allow" **per-host** (`webfetch:<host>` — jedno zatwierdzenie nie
  autoryzuje innych hostów). [`permission_rules.py`](../../../caelo_core/agent/permission_rules.py)
  `targets_for_tool`: `web_fetch` → `WebFetch(url)` (matcher `domain:`/glob z B4 — deny>allow).
- **Widoczność** [`session.py`](../../../caelo_core/agent/session.py): `WEB_FETCH_TOOL` advertowany **tylko**
  gdy `config.WEB_FETCH_ENABLED` **i** orkiestrator (`tool_names is None`) — ukryty gdy wyłączone i
  dla subagentów (wzorzec `lsp`). Egzekucja idzie zwykłą ścieżką mutującą (plan-mode blokuje, bypass
  auto-akceptuje, deny/allow przez istniejące checki).
- **Config + flaga:** [`config.py`](../../../config.py) `WEB_FETCH_ENABLED` (env `CAELO_WEB_FETCH`,
  **domyślnie OFF**), `WEB_FETCH_ALLOW_DOMAINS` (`CAELO_WEB_FETCH_DOMAINS` CSV), `WEB_FETCH_MAX_BYTES`/
  `WEB_FETCH_TIMEOUT_S`; headless [`--disable-web-search`](../../../caelo_core/headless.py) (parytet CLI —
  wyłącza na bieg). W headless web_fetch działa tylko z `--allow "WebFetch(domain:…)"`/`--always-approve`
  (fail-closed).
- **Frontend:** [`agentClient.ts`](../../../desktop/src/renderer/src/lib/agentClient.ts) `ApprovalDetail.url`
  + parser; karta zatwierdzenia `web_fetch` (URL + „Web/network") w
  [`AgentPanel.tsx`](../../../desktop/src/renderer/src/components/code/AgentPanel.tsx) (+ `preview_change`
  zwraca `{kind:"web_fetch",url}`).
- **Selfchecki:** `agent_selfcheck` `test_web_fetch` (+19: https-only, SSRF loopback/localhost/private,
  allowlista+subdomeny, redirect re-walidacja, cap+truncation, generyczny błąd, MUTATING, default
  approval, reguły allow/deny, `targets_for_tool`, klucz per-host, advertise off/on/subagent). **Cała
  bateria zielona** (agent/headless/api_smoke/acp/mcp/lsp/sandbox/genjobs/history/embeddings/packages).
  Frontend: **typecheck (node+web) ✓, lint 0 błędów, vitest 162/162 ✓**.
- **Bez preview:** jedyna powierzchnia UI (gałąź karty `web_fetch`) wymaga ŻYWEGO agenta (approval po
  WS) — devMock nie serwuje strumienia agenta, więc preview nie może jej wykonać (jak istniejące karty
  diff/command/mcp); gałąź pokryta typecheckiem.
- **Live (maszyna usera):** realny `web_fetch` (sandbox blokuje sieć) z `CAELO_WEB_FETCH=1` + zatwierdzenie/
  reguła `WebFetch(domain:…)`.

---

## 6. ✅ B14 — Config projektowy hierarchiczny (cwd→root) — ZROBIONE 2026-06-07 — **[P3] M**

**Cel:** w dużym repo/monorepo czytać reguły i config **od korzenia projektu do cwd** (deeper-wins),
jak CLI (`--project-root`, walk po `.git`). **Znaczna część już zrobiona w B5** (root+global +
`<ws>/.caelo/*`); B14 = **residuum**: walk po katalogach + odkrycie korzenia repo dla headless `--cwd`.

### 6.1 Odkrycie korzenia projektu
- `config.py` (lub `caelo_core/agent/project.py`): `find_project_root(start) -> Path` — walk w górę
  za `.git` (cap głębokości; `GIT_CEILING_DIRECTORIES` opcjonalnie). Parytet CLI: `--project-root`/
  `--no-project-root`/`--cwd-only`.
- [`headless.py`](../../../caelo_core/headless.py:198): gdy `--cwd` zagnieżdżone w repo, `set_workspace`
  może użyć korzenia projektu (flaga; domyślnie zachowanie dziś = `--cwd` jako root, bez regresji).

### 6.2 Walk reguł root↔cwd
- [`caelomd.py`](../../../caelo_core/agent/caelomd.py): obok `_read_dir_md(root)`+`_read_dir_md(global)`
  dodaj **walk od korzenia projektu do workspace/cwd** (sklejanie, deeper-wins; cap per plik). B5
  §1.1 świadomie pominął walk — to jest jego dokończenie. Zachowaj dedup po `normcase` + adnotacje
  źródła. (W GUI workspace = projekt, więc realna wartość głównie w headless `--cwd`.)
- `.caelo/*.json` hierarchicznie: `state.py` `_discover_lsp_configs`/`reload_permission_rules`/
  (B7) sandbox discovery — rozszerz o pliki w katalogach na ścieżce korzeń→cwd (deeper-wins), nie
  tylko `<ws>/.caelo`. Reużyj `load_json_or_backup`; workspace-aware rebuild (wzorzec `get_lsp`).

### 6.3 Selfcheck + akceptacja
- `agent_selfcheck`/`api_smoke`: `find_project_root` znajduje `.git`; CAELO.md z podkatalogów
  sklejane deeper-wins; `.caelo/permissions.json` z głębszego katalogu nadpisuje płytszy.
- **Akceptacja:** walk root→cwd działa dla CAELO.md i reguł; headless odkrywa korzeń repo; B5 nie
  zregresowane (single-root path nadal działa). **Uwaga:** to logika discovery, nie tekst UI (OK).

### ✅ Realizacja (2026-06-07)
- **Nowy leaf** [`agent/project.py`](../../../caelo_core/agent/project.py): `find_project_root(start)` (walk
  w górę za `.git` dir/plik; cap głębokości + `GIT_CEILING_DIRECTORIES`; brak repo → `start`) i
  `project_dir_chain(ws_root)` (katalogi od korzenia repo DO workspace, **najpłytszy pierwszy** =
  deeper-wins; korzeń-repo/brak-repo → `[ws_root]` = zachowanie sprzed B14). Tylko stdlib (bez cykli).
- **CAELO.md** [`caelomd.py`](../../../caelo_core/agent/caelomd.py) `load_caelo_md`: zamiast tylko workspace
  czyta cały łańcuch (global → przodkowie → workspace); workspace = najgłębszy („Workspace project
  rules"), przodkowie oznaczeni („ancestor: …"). Monorepo-subdir dziedziczy reguły przodków.
- **`.caelo/*.json` hierarchicznie** [`state.py`](../../../caelo_core/state.py): `reload_permission_rules`
  sumuje allow/deny z `permissions.json` całego łańcucha; `_discover_lsp_configs` scala `lsp.json`
  (deeper wygrywa per serwer). [`sandbox/profiles.py`](../../../caelo_core/sandbox/profiles.py)
  `_project_config` scala `sandbox.json` łańcucha (deeper per klucz). Wszystkie: pojedynczy root → jeden
  plik (bez regresji B5).
- **Headless** [`headless.py`](../../../caelo_core/headless.py): flaga **`--project-root`** (opt-in) →
  workspace = `find_project_root(--cwd)` (korzeń repo); domyślnie `--cwd` jako root (bez zmiany
  granicy sandboxa). Parytet CLI.
- **Zakres (świadomy):** walk po przodkach (korzeń-repo→workspace) DZIAŁA bez zmiany granicy workspace
  — dlatego `--project-root` (zmiana korzenia/sandboxa) jest opcjonalny, a dziedziczenie configu działa
  zawsze, gdy workspace jest podkatalogiem repo. To logika discovery, nie tekst UI.
- **Selfchecki:** `agent_selfcheck` `test_project_config` (+9: `find_project_root` z/bez repo,
  `project_dir_chain` deeper-first/single, CAELO.md przodek+workspace, `permissions.json` allow-przodek
  +deny-workspace, `lsp.json` deeper-wins) + `headless_check` `test_project_root_flag` (+2: `--project-root`
  ustawia korzeń repo, brak flagi = `--cwd`). **Cała bateria zielona** (agent/headless/api_smoke/
  handshake/acp/mcp/lsp/sandbox/genjobs/history/embeddings/packages). Backend-only → front bez zmian.
- **Live (maszyna usera):** workspace = podkatalog monorepo z `CAELO.md`/`.caelo/*` w przodkach;
  headless `--cwd <subdir> --project-root` na realnym repo.

---

## 7. Wspólne zasady (z CLAUDE.md — nie regresować)

- **Bez zmian root-modułów** (`config.py`/`api_manager.py`/…); nowy kod w `caelo_core/`. B9/B13 to
  cienkie warstwy param/endpoint, nie restrukturyzacja `api_manager`/`responses_client`.
- **Tylko Grok** — B13 `web_search` przez Responses xAI (lub odłożone); żadnego multi-providera.
- **Bez nowych ciężkich zależności** — B12 = launcher `git` (systemowy), B13 = `requests` (już jest),
  B10 auto-compact = istniejące LLM/obcięcie. Żadnego nowego pakietu backendu.
- **Fail-closed** — B13 web tools domyślnie pod bramką (deny>allow); B9/B10/B11/B12/B14 nie
  rozluźniają zgody. Headless/ACP nadal odrzucają mutacje bez jawnej zgody/reguły.
- **stdout święty / UTF-8** — B10 eksport md jawnie UTF-8; headless export na stdout/plik, logi stderr.
- **Reużyj helperów** — `load_json_or_backup`/`atomic_write_text`, `scrubbed_env`/`_tree_kill` (B12),
  `RuleSet`/`WebFetch` matcher z B4 (B13), wzorzec `lsp` „ukryj gdy brak" (B13), `get_lsp`/`reload_*`
  workspace-aware (B14), `errors.upstream_error` (B13).
- **Tekst UI po angielsku**; komentarze/docstringi mogą być po polsku.
- **„Selfcheck albo się nie stało":** każdy element ma asercje (rozszerzone suity lub nowe) w
  `caelo_core/tests/` (pytest) + Vitest dla czystych funkcji renderera (B10).
- **Brak eskalacji** (B11): `effective_tools` = rola ∩ rodzic; persona to tylko prompt.

---

## 8. Sekwencja, zależności, zrównoleglenie

```
B9  effort        ── niezależne (S)        ┐
B10 eksport+compact ── niezależne (S)      │
B11 persony+I/O   ── lekko zależy B9 (effort to pole persony)  ┼─ wszystkie [P3], równoległe
B12 git worktree  ── niezależne (S)        │
B13 web tools     ── używa B4 RuleSet (gotowe) (S)  │
B14 config hier.  ── dokończenie B5 (M)    ┘
```
**Rekomendacja:** **B9 → B11 → B10 → B13 → B12 → B14.**
- B9 najpierw (najmniejszy, odblokowuje pole `reasoning_effort` w B11 personach).
- B11 zaraz po (persony domykają warstwę ról M17; korzysta z B9).
- B10 eksport (a) szybki; auto-compact (b) można odłożyć/rozbić.
- B13 tani dzięki gotowemu matcherowi `WebFetch` z B4.
- B12 samodzielny; wartość zależy od repo git usera.
- B14 ostatni — największy (M) i w dużej części pokryty przez B5; residuum (walk + `.git`).
**Wspólny wątek:** B9 i B11 dzielą pole `reasoning_effort` — zrobić raz w `_clean_role`/`AgentSession`.

---

## 9. Akceptacja zbiorcza Tier-3

| Element | Backend selfcheck | Frontend | Na żywo (maszyna usera) |
|---|---|---|---|
| B9 effort ✅ | `agent_selfcheck` +10 ✅ + `api_smoke` +2 ✅ + `headless_check` +2 ✅ | selektor Auto/Low/Med/High (czat+agent+rola) ✅ (typecheck/lint/vitest/podgląd) | pole `reasoning.effort` akceptowane przez xAI |
| B10 eksport+compact ✅ | `api_smoke` +4 ✅ + `headless_check` +4 ✅ + `agent_selfcheck` +9 ✅ | Vitest +7 ✅ + przyciski Export (czat+History) ✅ (podgląd e2e) | jakość streszczenia |
| B11 persony+I/O ✅ | `agent_selfcheck` +11 ✅ + `api_smoke` +1 ✅ (round-trip + kontrakt) | edytor ról (instructions/I/O/effort) ✅ (typecheck/lint/podgląd) | jakość delegacji z kontraktem |
| B12 git worktree ✅ | `agent_selfcheck` +14 ✅ (fallback+git, guard `which('git')`) + `headless_check` +1 ✅ | (env/flaga — bez UI) | `git worktree add/remove` na repo |
| B13 web tools ✅ | `agent_selfcheck` +19 ✅ (https-only/SSRF/allowlista/cap/reguły/advertise) | karta zatwierdzenia `web_fetch` (URL) ✅ (typecheck) | realny `web_fetch` (`web_search` odłożony) |
| B14 config hier. ✅ | `agent_selfcheck` +9 ✅ (`find_project_root`, walk deeper-wins) + `headless_check` +2 ✅ | — (logika discovery) | monorepo `--cwd` zagnieżdżone |

---

## 10. Ryzyka i szacunki

| Element | Wysiłek | Główne ryzyko | Mitigacja |
|---|---|---|---|
| B9 | S | nazwa pola xAI (`reasoning.effort` vs `reasoning_effort`) różni się czat/Responses | param opcjonalny (tylko gdy podany); live-verify; defensywny parser |
| B10 | S | auto-compact rozcina parę tool_call↔tool → 400 | kompaktuj tylko zamknięte segmenty; opt-in + próg; błąd połknięty |
| B11 | S–M | rozrost configu ról; jakość promptów persony | tolerancyjny `_clean_role` + limity; iteracja live |
| B12 | S | różnice git po platformach; współdzielony `.git` | guard `is_git_repo`; fallback do kopii; tree-kill + scrubbed env |
| B13 | S | egzfiltracja przez fetch (SSRF) | https-only + allowlista domen + cap + bramka `WebFetch` (deny>allow); generic errors |
| B14 | M | regresja B5 single-root; głębokość walk w monorepo | domyślnie zachowanie dziś; cap głębokości; deeper-wins z dedup |

---

## 11. Otwarte pytania / decyzje (rozstrzygnąć w trakcie)

- **B9 pole effort:** czy chat/completions xAI używa `reasoning_effort` (flat) a Responses
  `reasoning.effort` (zagnieżdżone)? Live-verify; do tego czasu param opcjonalny w obu klientach.
- **B10 import md:** czy w ogóle wspierać md→historia (stratne) czy tylko eksport + wznawianie przez
  `-r`/`-c`/`session/load`? Rekomendacja: tylko eksport; import = istniejące sesje.
- **B10 auto-compact:** streszczenie przez LLM (lepsze, koszt+sieć) vs deterministyczne obcięcie+nota
  (tańsze, testowalne)? Rekomendacja: deterministyczne jako baza + opcjonalne LLM-summary za flagą.
- **B11 walidacja outputs:** czy egzekwować `outputs` w streszczeniu subagenta (parsowanie) czy tylko
  prompt-steering? Rekomendacja: na start prompt-steering; walidacja odłożona.
- **B12 domyślność:** git-worktree domyślny gdy repo, czy zawsze opt-in? Rekomendacja: opt-in
  (kopia jest sprawdzona i bezpieczna); włączać flagą/configiem.
- **B13 `web_search`:** dołączyć teraz (przez Responses) czy odłożyć i dać sam `web_fetch`?
  Rekomendacja: `web_fetch` najpierw (prosty, gated); `web_search` jako follow-up.
- **B14 zakres:** czy walk root→cwd ma sens w GUI (jeden root) czy tylko headless `--cwd`?
  Rekomendacja: zaimplementować, ale realna wartość = headless/monorepo; GUI bez zmian.

---

*Dokument towarzyszy [`PLAN_M19_PARYTET_GROK_CLI.md`](PLAN_M19_PARYTET_GROK_CLI.md) (§6),
[`PLAN_M19_TIER1.md`](PLAN_M19_TIER1.md) i [`PLAN_M19_TIER2.md`](PLAN_M19_TIER2.md). Aktualizować
status w nagłówku przy realizacji. Punkty styku zweryfikowane w kodzie 2026-06-07.*
