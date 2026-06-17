# PLAN_M14_ROZSZERZALNOSC.md — MCP / komendy / hooki / skille (rozpis zadań)

> Rozpis milestone'u **M14** z `PLAN_ROZBUDOWY.md` — skok platformowy. Cel: z „agenta, który
> edytuje pliki" zrobić **programowalną platformę**, której narzędzia służą całemu hubowi
> (czat i agent), przez **klienta MCP**, **komendy**, **hooki** i **skille**.
>
> Tagi: **[P0]** krytyczne, **[P1]** ważne. Wysiłek: S≈dni, M≈1–2 tyg., L≈3–4 tyg.
>
> ## ✅ STATUS (2026-06-05): M14 KOMPLETNE — B1–B6 + F1–F5
> Wszystkie zadania zrobione i zweryfikowane self-checkami (xAI mockowane — realne MCP/czat user
> sprawdza na swojej maszynie). **Backend:** `grok_mcp.json` 24/24 (`mcp_check`), `agent_selfcheck`
> 139/139 (MCP w agencie + hooki), `api_smoke` OK (pętla narzędzi MCP w czacie, trasy /mcp,
> komendy+skille, remote MCP). **Decyzja:** klient MCP = własna cienka warstwa synchroniczna dla
> stdio (nie SDK) — hybryda, zero nowych zależności. **Frontend:** moduł Extensions (4 zakładki) +
> karta zatwierdzenia MCP + komendy slash w composerze/palecie; typecheck OK. **P0-1…P0-8 + M5–M6
> bez regresji.** Szczegóły per-zadanie w sekcjach poniżej.

---

## 0. Dwie drogi MCP — i dlaczego budujemy własnego klienta

| | **Klient MCP w `grok_core`** (rdzeń M14) | **Native Remote MCP xAI** (skrót) |
|---|---|---|
| Transport | **stdio + Streamable HTTP** | tylko zdalne HTTP |
| Wykonanie | **lokalne** (w sidecarze) | po stronie xAI |
| Serwery lokalne (filesystem, git, Twoje Ren'Py/DAZ) | ✅ | ❌ (xAI ich nie dosięgnie) |
| Bramka `PermissionGate` / zgoda | ✅ pełna | ❌ `require_approval` nieobsługiwane |
| Dane | zostają lokalnie | lecą do xAI |
| Konfiguracja | własna (`grok_mcp.json`) | `tools=[{"type":"mcp","server_url":…}]` |

**Decyzja:** **klient lokalny domyślnie** (kontrola, stdio, dane lokalnie); native Remote MCP tylko
jako opcja dla **zaufanych, read-only** serwerów zdalnych HTTP, z jawnym ostrzeżeniem.

### Decyzje przekrojowe (przeczytaj przed kodowaniem)
- **Hooki = uogólniony `PermissionGate`.** Masz już pre-tool gate; M14 robi z niego konfigurowalny
  system (pre/post-tool, pre-session). Nie buduj obok — rozszerz.
- **Komendy** = szablon promptu + opcjonalna akcja; działają w czacie i agencie.
- **Skille** = lokalne pakiety (instrukcje + opcjonalne skrypty/zasoby) ładowane do kontekstu;
  Twoje Ren'Py/DAZ jako pierwsze. (Niezależne od wbudowanych „skills" konta xAI — patrz pytania.)
- **Bezpieczeństwo serwerów stdio:** uruchomienie serwera = uruchomienie dowolnej komendy →
  **traktuj jak `run_command`**: scrubbed env, tree-kill (masz to), jawna zgoda na dodanie/start.
- **Reuse:** narzędzia przekazujesz przez `responses_client` (M10); strumień przez `WsStream`;
  bramka przez `PermissionGate`; modal zatwierdzenia z M13-F1.
- **Oficjalny MCP SDK (Python)**, nie własna implementacja — mniej długu, zgodność ze spec.
- **UI po angielsku** (konwencja repo): „MCP servers", „Commands", „Hooks", „Skills".

---

## 1. Backend (`grok_core`)

### ✅ M14-B1 [P0] Klient MCP (stdio + Streamable HTTP)  — L  — **DONE**
- **Cel:** sidecar łączy się z serwerami MCP i odkrywa ich narzędzia/zasoby/prompty.
- **Zakres:** `grok_core/mcp/client.py` (oficjalny MCP SDK): połączenie ze skonfigurowanymi serwerami
  (stdio jako podproces + HTTP), handshake, `list_tools/resources/prompts`, `call_tool`. Hardening
  podprocesu: scrubbed env, tree-kill, cykl życia. Konfiguracja `grok_mcp.json` (atomowo,
  `load_json_or_backup`).
- **DoD:** konfiguruję serwer filesystem (stdio) → narzędzia odkryte → wywoływalne; serwer ubity czysto.
- **Selfcheck:** nowy `grok_core/tools/mcp_check.py` — połącz z mock-serwerem, list+call tool,
  podproces tree-killed, `grok_mcp.json` corrupt → backup.
- **Status (2026-06-05):** ⚠️ **decyzja:** klient = WŁASNA cienka warstwa synchroniczna (nie SDK) —
  hybryda per ustalenie z userem (`grok_core/mcp/client.py` + `manager.py`), zero nowych zależności,
  jak `responses_client` wobec SDK OpenAI. **stdio w pełni** (newline JSON-RPC 2.0, handshake,
  list/call, paginacja, scrubbed env, tree-kill, Windows `cmd /c` dla `.cmd`/`npx`). Streamable HTTP /
  remote = native remote MCP (B3), transport abstrakcyjny (`McpTransport`) gotowy na SDK później.
  `McpManager` (namespacing `mcp__srv__tool`, routing, klasyfikacja gate przez `readOnlyHint`,
  maskowanie sekretów). REST `routes/mcp.py` (list/add/del/enable/start/stop/status, start jawny =
  gate). `backend.mcp` (leniwy) + `backend.shutdown()` w lifespan. **`mcp_check.py` 24/24 OK** (mock
  stdio server). Real serwer (filesystem/git) weryfikuje user na swojej maszynie.

### ✅ M14-B2 [P0] Rejestracja narzędzi MCP w Responses + bramka  — M  — **DONE**
- **Cel:** narzędzia MCP używalne przez czat i agenta, bezpiecznie.
- **Zakres:** mapuj odkryte narzędzia MCP → definicje function-calling w `responses_client` (M10);
  na `tool_call` routuj do klienta MCP, wykonaj, zwróć wynik; **mutujące/wrażliwe przez
  `PermissionGate`** (zgoda + podgląd argumentów). READONLY mogą iść bez bramki (jak Twoje tools).
- **DoD:** czat/agent woła narzędzie MCP; mutujące wymaga zgody; wynik wraca do modelu.
- **Selfcheck:** `mcp_check`/`agent_selfcheck` — narzędzie zarejestrowane, `tool_call` zroutowany do
  MCP, narzędzie bramkowane zablokowane do zatwierdzenia.
- **Status (2026-06-05):** **Agent:** `session.py` scala `TOOLS` + `mcp.tool_defs_for_responses()`;
  `_handle_tool_call` rozróżnia plikowe/MCP; mutujące MCP przez bramkę (klucz `mcp:<name>`
  „Always allow" w `grok_permissions.json`), READONLY (`readOnlyHint`) bez zgody; plan mode blokuje
  mutujące MCP; mutujące MCP → „partial undo". Karta zatwierdzenia: `detail.kind="mcp_tool_call"`.
  **Czat:** `responses_client` ma klient-side function calling (pętla: stream → `function_call` →
  `tool_handler` → `function_call_output` → kolejna tura, do `max_tool_iters`); FLAT format narzędzia
  Responses. Polityka czatu (brak modala): READONLY działa; mutujące tylko gdy WCZEŚNIEJ dopuszczone
  na współdzielonej allowliście, inaczej odmowa z komunikatem. **Selfcheck:** `agent_selfcheck`
  +13 (`test_mcp_in_agent`, 127/127 OK), `api_smoke` `_unit_responses_mcp_loop` + `_unit_mcp_routes`
  (OK). Bez `function_tools` zachowanie czatu IDENTYCZNE jak przed M14 (zero regresji).

### ✅ M14-B3 [P1] Native Remote MCP (skrót dla zdalnych HTTP)  — S/M  — **DONE (backend)**
- **Cel:** wygodne podłączenie zaufanego zdalnego serwera HTTP zarządzanego przez xAI.
- **Zakres:** dodanie serwera jako `tools=[{"type":"mcp","server_label","server_url","authorization"}]`
  w żądaniu Responses. **Jawne oznaczenie:** wykonanie po stronie xAI, brak lokalnej zgody, dane do xAI.
- **DoD:** dodaję URL zdalnego MCP → jego narzędzia używalne przez xAI; ostrzeżenie widoczne w UI.
- **Selfcheck:** `api_smoke` — żądanie zawiera blok mcp; ostrzeżenie obecne.
- **Status (2026-06-05):** serwer `transport:"remote"` w `grok_mcp.json` (autoryzacja maskowana w UI);
  `McpManager.remote_tool_blocks()` → `responses_client(..., remote_tools=...)` doklejane do
  `payload.tools`; czat je przekazuje. **Selfcheck:** `api_smoke` `mcp-loop: native remote MCP block
  in Responses payload` + `mcp_check` remote-block/maskowanie. Ostrzeżenie „xAI-side, brak bramki" =
  w UI (F1, „advanced").

### ✅ M14-B4 [P0] Komendy (slash commands)  — M  — **DONE**
- **Cel:** szybkie, powtarzalne akcje w czacie i agencie.
- **Zakres:** `grok_core/commands/` — rejestr: wbudowane `/plan` `/review` `/commit` `/test` `/mcp`
  + użytkownika. Komenda = szablon promptu + opcjonalna akcja (np. `/commit` woła `git.py` przez
  bramkę). Ładowane z `grok_commands.json` + katalog komend.
- **DoD:** `/plan` w czacie odpala tryb planowania; `/commit` proponuje commit (przez zgodę).
- **Selfcheck:** `api_smoke`/`agent_selfcheck` — komenda sparsowana, szablon rozwinięty, akcja bramkowana.
- **Status (2026-06-05):** `grok_core/commands/registry.py` `CommandRegistry` — wbudowane
  `/plan`(mode=plan) `/review` `/commit` `/test` `/mcp`(action=open_mcp) + użytkownika
  (`grok_commands.json` + katalog `commands/*.md` z frontmatter; user nadpisuje builtin). `expand()`
  podstawia `{input}`/`{args}`. Każda komenda niesie `target`(chat/agent/both)+`mode`+`action` →
  renderer stosuje (F3). „Akcja przez bramkę": `/commit`/`/test` to prompty wykonywane przez agenta
  (git/test przez gated `run_command`). REST `routes/commands.py`. `backend.commands`. Wspólny
  `grok_core/markdown_meta.py` (frontmatter bez YAML-dep). **Selfcheck:** `api_smoke`
  `_unit_commands_skills` B4 (OK).

### ✅ M14-B5 [P0] Hooki (uogólniony `PermissionGate`)  — M  — **DONE**
- **Cel:** deterministyczne reguły cyklu życia narzędzi.
- **Zakres:** uogólnij `PermissionGate` w system hooków: `pre_tool` / `post_tool` / `pre_session`.
  Wbudowane: blokada groźnych komend (masz `command_metachars`), log audytu. Użytkownika: uruchom
  skrypt (np. auto-format po zapisie). Deterministyczne, niezależne od modelu.
- **DoD:** hook `pre_tool` blokuje `rm -rf`; `post_tool` formatuje zapisany plik; audyt loguje wywołania.
- **Selfcheck:** rozszerz `agent_selfcheck.py` — hooki odpalają w kolejności, blokada działa,
  allowlist nienaruszona; **P0-1…P0-8 i M5–M6 bez regresji**.
- **Status (2026-06-05):** `grok_core/hooks.py` `HookManager` — `pre_tool` (block_command/block_path),
  `post_tool` (audit + run_script), `pre_session`. Wbudowane domyślne: `block-dangerous-commands`
  (regex intencyjny PONAD P0-1: bare `rm -rf`/`format`/`dd`/force-push) + `audit-all` (JSONL
  `grok_audit.log`, miękka rotacja). `run_script` (opt-in) = scrubbed env + tree-kill + timeout +
  `{path}` (auto-format po zapisie). Hooki odpalają w `session.py` PRZED bramką (block nie dochodzi do
  approval) — `PermissionGate` NIETKNIĘTY (działa OBOK). REST `routes/hooks.py` (list/add/enable/del +
  `/audit`). `backend.hooks` (leniwy). **Selfcheck:** `agent_selfcheck` `test_hooks` +12 (139/139 OK):
  blokada przed bramką, allowlista nienaruszona, audyt, run_script. **P0/M5–M6 bez regresji.**

### ✅ M14-B6 [P1] Skille (pakiety)  — M  — **DONE**
- **Cel:** wielokrotnego użytku workflowy jako pakiety (most do Twojego dorobku Ren'Py/DAZ).
- **Zakres:** `grok_core/skills/` — skill = folder z `SKILL.md` (instrukcje) + opcjonalne skrypty/
  zasoby; odkrywanie, lista, wstrzykiwanie do kontekstu czatu/agenta na żądanie lub po triggerze.
  Twoje workflowy („nowa scena VN", „eksport WebM") jako pierwsze skille.
- **DoD:** skill odkryty, a jego instrukcje wstrzyknięte przy wywołaniu.
- **Selfcheck:** skill odkryty, `SKILL.md` sparsowany, wstrzyknięty, brak/za duży tolerowany.
- **Status (2026-06-05):** `grok_core/skills/manager.py` `SkillManager` — odkrywa **wbudowane**
  (`skills/builtin/`, pakowane w `grok_core.spec` przez `collect_data_files`) + **użytkownika**
  (`config.SKILLS_DIR`); user nadpisuje builtin. Pierwsze skille: `renpy-new-scene` + `daz-export-webm`.
  Stan „enabled" w `SKILLS_DIR/_state.json`; włączone → `injected_text()` (cap per-skill+łączny)
  wstrzykiwane do system promptu agenta (`session._build_system_prompt`, jak GROK.md). `create_skill`
  (szablon blank/renpy/daz, sandbox nazwy), `delete_skill` (tylko user). REST `routes/skills.py`.
  `backend.skills`. **Selfcheck:** `api_smoke` `_unit_commands_skills` B6 (OK): odkrycie, get/inject/
  create/delete, traversal odrzucony, brak/za duży tolerowany.

---

## 2. Frontend (`desktop/src/renderer`)

> **Status (2026-06-05): F1–F5 DONE.** Nowy moduł **Extensions** (`components/Extensions.tsx`,
> w lewym pasku + leniwy) z 4 zakładkami: **MCP Servers** (F1), **Commands** (B4-mgmt), **Hooks**
> (F4), **Skills** (F5). Karta zatwierdzenia agenta (M13-F1) rozszerzona o `mcp_tool_call` (F2).
> Komendy slash w composerze czatu (`/` → lista) + palecie Ctrl-K (F3). API w `lib/api.ts`,
> typy `McpServerInfo`/`HookInfo`/`SkillInfo`/`SlashCommand`. **Typecheck OK**; Vitest
> `desktop/test/slashCommands.test.ts` (commitnięte; uruchamialne po `npm install -D`). Renderowanie
> 4 zakładek zweryfikowane w `preview:web` (bez błędów konsoli; sieć mockowana → puste listy).

### ✅ M14-F1 [P0] Menedżer serwerów MCP  — M  — **DONE**
- **Cel:** dodawaj/zarządzaj serwerami i widz ich narzędzia.
- **Zakres:** UI dodaj/usuń/włącz serwer (komenda stdio lub URL HTTP), lista odkrytych narzędzi,
  toggle per serwer, oznaczenie local vs remote-xAI. Zgoda na pierwszy start serwera stdio.
- **DoD:** dodaję serwer → widzę jego narzędzia → włączam dla czatu/agenta.
- **Test:** Vitest — stan konfiguracji serwera.
- **Status:** `components/extensions/McpServers.tsx` — formularz add (stdio argv / remote URL+auth,
  ostrzeżenie remote), lista serwerów ze statusem (badge ready/error/remote), Start (z `confirm()` —
  jawna zgoda), Stop, toggle Enabled, Remove, chipy odkrytych narzędzi (`ro` = readonly).

### ✅ M14-F2 [P0] Zatwierdzanie wywołań narzędzi MCP  — S/M  — **DONE**
- **Cel:** ta sama kontrola co przy edycjach agenta.
- **Zakres:** rozbuduj modal zatwierdzenia (M13-F1) o wywołania MCP: nazwa narzędzia, serwer,
  argumenty; accept/reject; „Always allow" per narzędzie.
- **DoD:** gdy model woła mutujące narzędzie MCP, modal je pokazuje; zgoda → wykonanie.
- **Test:** Vitest — stan zatwierdzania narzędzia MCP.
- **Status:** `ApprovalDetail` (`lib/agentClient.ts`) + parser rozszerzone o `mcp_tool_call`
  (server/tool/qualified_name/description/args). `AgentPanel.tsx` renderuje kartę MCP (badge „MCP",
  narzędzie, serwer, JSON argów) z tymi samymi przyciskami Accept/Reject/Always allow (B2 utrwala
  klucz `mcp:<name>`).

### ✅ M14-F3 [P0] Paleta komend → slash commands  — S/M  — **DONE**
- **Cel:** komendy w zasięgu klawiatury.
- **Zakres:** komendy w composerze (wpisz `/`) i w palecie komend (M9-F5); wbudowane + użytkownika; wykonanie.
- **DoD:** wpisanie `/` pokazuje komendy; wybór wykonuje.
- **Test:** Vitest — filtr komend.
- **Status:** `lib/slashCommands.ts` (czyste utile: `filterSlashCommands`/`slashQuery`/`matchSlash`/
  `expandTemplate`). Composer `ChatView` pokazuje dropdown gdy `/<partial>`; Enter/Tab dokończa, na
  Send rozwija szablon (akcja `open_mcp` → nawigacja do Extensions). Hub (`lib/hub.tsx`) ładuje komendy
  + `runSlashCommand`/`composerDraft`; `AppCommandPalette` dorzuca je do Ctrl-K. Vitest
  `slashCommands.test.ts`.

### ✅ M14-F4 [P1] Edytor hooków + log audytu  — S/M  — **DONE**
- **Cel:** widoczność i kontrola reguł.
- **Zakres:** UI podgląd/włączanie/edycja hooków (pre/post-tool); podgląd logu audytu.
- **DoD:** włączam hook; widzę jego odpalenie w logu.
- **Test:** Vitest — stan listy hooków.
- **Status:** `components/extensions/HooksPanel.tsx` — lista hooków (toggle/remove), formularz add
  (event + type: block_command/block_path/run_script, pattern/command/match_tools), log audytu
  (Refresh/Clear, badge action blocked/tool/hook_script).

### ✅ M14-F5 [P1] Biblioteka skilli  — M  — **DONE**
- **Cel:** przeglądaj/włączaj/twórz skille.
- **Zakres:** UI lista skilli, tworzenie z szablonu (Ren'Py/DAZ), wywołanie; gotowe pod marketplace (M16).
- **DoD:** włączam skill → wpływa na następny czat/agenta.
- **Test:** Vitest — stan listy skilli.
- **Status:** `components/extensions/SkillsLibrary.tsx` — lista (builtin/user), rozwijany podgląd
  `SKILL.md`, toggle Enabled (→ wstrzyknięcie do agenta), Create z szablonu (blank/renpy/daz),
  Delete (tylko user).

---

## 3. Kolejność i zależności

```
B1 (klient MCP)  ──►  B2 (rejestracja + bramka)  ──►  F1 (menedżer), F2 (zatwierdzanie)
B4 (komendy)  ──►  F3            [na bazie PermissionGate + Responses]
B5 (hooki)    ──►  F4            [uogólnienie PermissionGate]
B6 (skille)   ──►  F5
B3 (remote MCP)  ── opcja, równolegle
```

- **Fundament:** `B1` + `B2` — klient MCP z bramką. Bez nich „rozszerzalność" nie istnieje.
- **Pierwszy „wow" (i moment platformowy):** `B1→B2→F1→F2` — podłączasz lokalny serwer MCP
  (filesystem/git) i model używa jego narzędzi **za Twoją zgodą**, w czacie *i* w agencie. To jest
  ta chwila, gdy hub staje się platformą, a nie zamkniętym zestawem funkcji.
- `B4/F3` (komendy) i `B5/F4` (hooki) idą na Twoim `PermissionGate`/Responses — niski koszt, duża UX.
- `B6/F5` (skille) to most do Twojego dorobku Ren'Py/DAZ i rozbieg pod marketplace (M16).
- `B3` (remote MCP) tylko gdy ktoś realnie chce zdalny HTTP — pamiętając o braku bramki.

## 4. Definicja ukończenia M14 (całość)  — ✅ SPEŁNIONE (1–6)

1. Podłączam lokalny serwer **stdio MCP** (filesystem/git) → jego narzędzia odkryte i wywoływalne
   przez czat **i** agenta, bramkowane przez `PermissionGate`.
2. (Opcjonalnie) dodaję zdalny serwer HTTP przez native Remote MCP — jawnie oznaczony (po stronie xAI,
   bez lokalnej zgody).
3. **Slash commands** (`/plan` `/review` `/commit` `/test` `/mcp` + własne) działają w czacie i agencie.
4. **Hooki** (uogólniony `PermissionGate`): pre-hook blokuje groźną komendę, post-hook się odpala,
   log audytu zapisuje wywołania.
5. **Skille** jako pakiety odkrywane i wstrzykiwalne; Ren'Py/DAZ jako pierwsze.
6. Podprocesy MCP zahartowane (scrubbed env, tree-kill, sandbox + zgoda na start); trasy fail-closed;
   `agent_selfcheck.py` rozszerzony; **P0-1…P0-8 + M5–M6 bez regresji**.

## 5. Otwarte pytania techniczne

- **Native remote MCP w UI — eksponować?** Skoro brak `require_approval` i dane lecą do xAI, może
  warto ukryć go za „advanced" i domyślnie promować tylko klienta lokalnego. Decyzja UX.
- **Zgoda na start serwera stdio:** dodanie serwera uruchamia dowolną komendę. Traktować jak
  `run_command` (gate + jawna zgoda + scrubbed env + tree-kill). Potwierdź, że tak.
- **MCP transport:** stdio + Streamable HTTP (SSE wycofane). Potwierdź wersję spec/SDK w venv sidecara.
- **Skille lokalne vs wbudowane skille xAI:** Twoje to lokalne pakiety; xAI ma własne wbudowane na
  koncie. Chcesz móc korzystać też z tych xAI, czy tylko własne lokalne? (Wpływa na model „skilla".)
- **MCP Apps (interaktywne UI w iframe, spec ze stycznia 2026):** poza M14, ale zarezerwuj miejsce
  w architekturze widoku narzędzi, gdybyś chciał renderować bogate UI z serwerów MCP później.
- **Spójność z M13 (subagenci M17):** subagenci powinni dziedziczyć dostęp do narzędzi MCP z
  zawężeniem per rola — zaprojektuj rejestr narzędzi tak, by dało się go filtrować per (sub)agent.
