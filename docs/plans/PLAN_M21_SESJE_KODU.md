# PLAN_M21_SESJE_KODU.md — Zapis i wznawianie sesji agenta kodowania

> Tryb **Code** nie zapisywał historii sesji agenta — rozmowa żyła tylko w `useState`
> panelu i ginęła przy zmianie zakładki / reloadzie. M21 dodaje **trwałe, wznawialne
> sesje agenta** z listą i filtrami (po projekcie/folderze i tekstem).
>
> **Kontekst architektoniczny:** czat trzyma całą historię w rendererze (`useConversations`,
> `localStorage`) i wysyła ją co turę → backend bezstanowy. **Agent jest inny** — protokół
> WS `/agent/stream` jest **stanowy po stronie backendu**: front wysyła tylko `{type:'message',
> text}`, a pełną historię LLM trzyma `AgentRunner._session.history`. Dlatego „zapis sesji"
> musi żyć po stronie backendu (a `entries` w panelu to tylko widok strumienia).
>
> **Reużyte:** tryb headless (M19-B1) miał już persystencję sesji (`DATA_DIR/sessions/<id>.json`)
> i `AgentRunner` wspierał `initial_history` do wznawiania — M21 wydziela ten magazyn do
> wspólnego modułu i podłącza go do WS. Zasady: `config.load_json_or_backup` + `atomic_write_text`,
> WS fail-closed (token+Origin).
>
> **STATUS (2026-06-07): ✅ KOMPLETNY** — backend + frontend, selfchecki zielone
> (`api_smoke` `_unit_sessions_routes` + live token-gate, `headless_check`, `agent_selfcheck`,
> `acp_check`; Vitest `agentSession.test.ts`). **Weryfikacja LIVE** interaktywnego UI (realne WS
> resume w Electronie) — u usera; `preview:web`/devMock nie ma tras sesji.

---

## 0. Magazyn sesji — `caelo_core/agent/sessions.py` (NOWY)

Transport-neutralny magazyn (NIE importuje `state`/`api_manager` — zero cykli), wspólny dla
trybu headless i WS. Format pliku **v2** `DATA_DIR/sessions/<id>.json`:

```json
{ "v": 2, "id", "cwd", "project_id", "title", "model",
  "created_at", "updated_at", "history": [ {role, content, ...}, ... ] }
```

- `load(sid) -> dict` — znormalizowany v2; **toleruje stary headless format** `{"id","cwd",
  "history"}` (brak pól → `project_id=None`, `title` z 1. wiadomości user, czasy z mtime).
- `load_history(sid) -> list` — sama historia (dla headless/`resume_session`).
- `save(*, id, cwd, history, project_id=None, model=None, title=None, created_at=None)` —
  atomowo; zachowuje `created_at` i wcześniejsze pola przy istniejącym pliku, ustawia `updated_at`.
- `list_meta(project_id=None) -> list[dict]` — metadane (bez `history`), najnowsze pierwsze;
  filtr po projekcie.
- `delete(sid) -> bool`, `latest() -> str|None`, `title_from_history(history)`.

`headless.py` zrefaktorowany: prywatne `_sessions_dir/_session_path/_load_session/_save_session/
_latest_session` to teraz **cienkie aliasy** do `sessions` (self-checki ich używają), a `_run`
zapisuje przez `sessions.save(...)` ze stemplem `project_id` + `model`.

## 1. AgentRunner — `caelo_core/agent/runner.py`

- Konstruktor: `session_id: Optional[str] = None`; property `current_session_id`.
- `new_session(session_id=None) -> str` — porzuca bieżącą `AgentSession` (świeża historia),
  generuje/ustawia id.
- `resume_session(session_id, history)` — wstrzykuje historię przed 1. turą (`_ensure_session`),
  więc model kontynuuje z pełnym kontekstem.
- `_persist_session(model)` w `finally` `run_turn` — **no-op bez `session_id`** (headless zapisuje
  sam), inaczej `sessions.save(...)`. Obok istniejącego M9 `record_event(mode="code")`.

## 2. Protokół WS — `caelo_core/routes/agent.py`

Każde połączenie startuje od świeżego `session_id` (`AgentRunner(..., session_id=secrets.token_urlsafe(8))`).
Nowe ramki:

- serwer→klient: `{"type":"session","id":"<sid>"}` (po połączeniu / wznowieniu / nowej sesji).
- klient→serwer: `{"type":"session","id":"<sid>"|null}` — `null` = nowa sesja (`new_session`),
  `<sid>` = wznów (`resume_session(sid, sessions.load(sid)["history"])`). **Busy-guard** (odrzut
  w trakcie tury). Workspace przełącza front osobną ramką `workspace` (nie handler).

## 3. REST — `caelo_core/routes/sessions.py` (NOWY, montaż w `server.py` pod `require_token`)

- `GET /agent/sessions?project_id=` → metadane (filtr po projekcie).
- `GET /agent/sessions/{id}` → pełna sesja z historią (transkrypt + wznowienie); 404 gdy brak.
- `DELETE /agent/sessions/{id}` → usunięcie; 404 gdy brak.

Sesje są globalne na maszynie (czytają `DATA_DIR` same), więc trasy nie potrzebują `Backend`.

## 4. Frontend (`desktop/src/renderer/`)

- `lib/api.ts` — typy `AgentSessionMeta`/`RawLlmMessage`/`AgentSessionFull` +
  `listAgentSessions(c, projectId?)`/`getAgentSession(c, id)`/`deleteAgentSession(c, id)`.
- `lib/agentClient.ts` — wariant `{type:'session',id}` w `AgentEvent` + parsing + metoda
  `setSession(id|null)`.
- `lib/agentSession.ts` (NOWY, czyste funkcje):
  - `historyToEntries(history)` — rekonstrukcja transkryptu (`Entry[]`) z surowej historii LLM
    (user/assistant/tool_calls/tool → wpisy; tool-calls jako zwinięte `status:'done'` z wynikiem
    z `tool_call_id`).
  - `filterSessions(sessions, query)` — filtr tekstowy po tytule/ścieżce/modelu (tokeny AND).
  - `sessionsForWorkspace(sessions, workspacePath)` — sesje danego **folderu** (po `cwd`).
- `components/code/AgentPanel.tsx` — stan `sessionId`, obsługa ramki `session`, **menu „Sessions"**
  (ikona `MessagesSquare` obok Checkpoints): **New** / **Open** (`getAgentSession` →
  `historyToEntries` → `setEntries` → `setSession`; przełącza workspace gdy inny `cwd`) / **Delete**,
  **pole filtra tekstowego** + przełącznik **This project / All projects**.
- `components/CodeView.tsx` — prop `onOpenWorkspace` (`ws.selectWorkspace`) do wznowienia z innego
  katalogu.

### Filtr po projekcie = po OTWARTYM FOLDERZE
W module Code „bieżący projekt" wynika z otwartego folderu (`set_workspace` →
`ensure_project_for_root`), a nie z (bywa nieaktualnego) `hub.currentProjectId`. Dlatego zawężenie
„This project" jest po `cwd` sesji = folderze (klient-side, `sessionsForWorkspace`) — odporne i
zgodne z modelem M22 (folder = projekt Code).

## 5. Stan / pliki
- Nowy stan: `DATA_DIR/sessions/<id>.json` (już gitignorowany — `/sessions/`, dzielony z headless).
- Self-checki: `tools/smoke_routes.py` `_unit_sessions_routes` (lista/filtr/get/404/delete + stary
  format) + `api_smoke.py` live token-gate `/agent/sessions`; `desktop/test/agentSession.test.ts`
  (`historyToEntries` + `filterSessions` + `sessionsForWorkspace`).

## 6. Znane ograniczenie
Po utracie i reconnekcie WS backend startuje nową sesję (nowe id) — wyświetlony transkrypt zostaje,
ale kontynuacja zaczyna świeży kontekst. Stara sesja jest na dysku → wystarczy ją otworzyć z menu,
by wznowić z pełnym kontekstem. (Przed M21 historia i tak ginęła przy reconnekcie — runner był
per-połączenie.)
