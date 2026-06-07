# PLAN_M22_PROJEKTY_CZATU.md — Rozdzielenie projektów czatu od workspace'ów Code

> M9-B5 zrobił z „projektu" JEDEN wspólny byt dla chat/media/voice/code, a `set_workspace()`
> w module Code wiązał otwarty folder z projektem **i ustawiał go aktywnym** (`select_project`).
> Efekt: na liście projektów w czacie mieszały się foldery Code („VN Shift_files",
> „grok_desktop_app") z projektami czatowymi, a utworzony projekt był „pustą etykietą" (zarządzanie
> wiedzą siedziało w osobnym, niepowiązanym `KnowledgePopover`; brak rename/delete/instrukcji).
>
> **Decyzja (feedback usera):** **osobny model danych** — projekt czatu ≠ workspace Code — oraz
> projekt czatu z pełnym zarządzaniem: **rename + delete · wiedza w przełączniku · instrukcje per
> projekt (system prompt) · grupowanie rozmów**.
>
> **Realizacja „osobnego modelu":** trwały **dyskryminator `kind`** (`'chat'` | `'code'`) w tabeli
> `projects` + kolumna `instructions`. To genuinely odrębne zbiory (czat nigdy nie widzi folderów
> Code i odwrotnie) z niezależnym cyklem życia, BEZ nieproporcjonalnej migracji do równoległych
> tabel dla `history_events`/`artifacts`/`gen_jobs`/`collection_files` (wszystkie trzymają
> `project_id` i działają bez zmian). Najtrudniejsza część: **rozszczepienie bieżącego projektu** —
> `current_project_id` = aktywny projekt CZATU; projekt Code dla stemplowania `mode=code` jest
> wyprowadzany z workspace i NIE nadpisuje czatu.
>
> **STATUS (2026-06-07): ✅ KOMPLETNY** — backend + frontend, selfchecki zielone (`api_smoke`
> rozszerzony `_unit_projects_routes`, `headless_check`, `agent_selfcheck`; Vitest). **Weryfikacja
> LIVE** (realne kolekcje/wiedza/instrukcje na żywo) — u usera.

---

## 0. Schemat + migracja — `caelo_core/history_store.py`

Wzorzec migracji jak `vector_store_id` (idempotentny `ALTER TABLE` + `PRAGMA table_info`):

- `projects.kind TEXT NOT NULL DEFAULT 'chat'` + **backfill** `UPDATE projects SET kind='code'
  WHERE root != ''` (dotychczasowe projekty z folderem → Code).
- `projects.instructions TEXT NOT NULL DEFAULT ''` (system prompt per projekt czatu).
- `Project` dataclass + `to_dict()` + `_row_to_project()` — pola `kind`/`instructions` (fallback).
- `add_project(..., kind='chat', instructions='')`; `ensure_project_for_root(..., kind='code')`;
  `list_projects(kind=None)` (filtr); **NOWE** `update_project(id, *, name=None, instructions=None)`
  i `delete_project(id) -> Project|None` (kaskada w jednej transakcji: `event_embeddings`/`history_fts`/
  `history_events`/`artifacts`/`gen_jobs`/`collection_files` + `projects`; zwraca projekt → caller
  sprząta katalog dokumentów).

## 1. Rozszczepienie bieżącego projektu — `caelo_core/state.py`

- `set_workspace()` → `ensure_project_for_root(root, kind='code')`, zapamiętuje
  `self._code_project_id`, **NIE woła `select_project`** (folder nie zmienia projektu czatu).
- `record_event()` → dla `mode == 'code'` stempluje `_code_project_id` (fallback `current_project_id`),
  inaczej `current_project_id`.
- `__init__` → jeśli wczytany `current_project_id` wskazuje projekt `kind='code'` (legacy), zeruje go
  (czat startuje czysto).
- `Backend.list_projects(kind=None)`; **NOWE** `update_project(...)`/`delete_project(...)` (delete:
  usuwa też katalog `PROJECT_DOCS_DIR/<id>/`, czyści aktywny czat/`_code_project_id`, jeśli dotyczyło).
- Spójność M21: zapis sesji agenta i `record_event(mode=code)` trafiają pod projekt Code (filtr sesji
  i tak po `cwd`).

## 2. Trasy — `caelo_core/routes/projects.py` + `routes/chat.py`

- `GET /projects` → `list_projects(kind='chat')` (czat/galeria/historia widzą tylko projekty czatu).
- **NOWE** `PATCH /projects/{id}` (`UpdateProjectReq{name?, instructions?}`) → `update_project`.
- **NOWE** `DELETE /projects/{id}` → `delete_project`; 404 gdy brak.
- `routes/chat.py` (~240): dokleja `current_project().instructions` do `system_prompt` PRZED
  promptem z ramki (jedno źródło prawdy w backendzie; `getattr`-guard na atrapy self-checków).

## 3. Frontend (`desktop/src/renderer/`)

- `lib/api.ts` — `HubProject` + `kind?`/`instructions?`; **NOWE** `updateProject(c, id, patch)` (PATCH),
  `deleteProject(c, id)` (DELETE).
- `lib/hub.tsx` — `reloadProjects` dostaje tylko projekty czatu (filtr serwerowy); wystawia
  `updateProject`/`deleteProject` (po delete bieżącego → `selectProject(null)`).
- `components/ProjectSwitcher.tsx` — **przepisany na menedżera**: widok listy (wybór / „New project")
  ↔ widok szczegółów (⚙): **rename** + **instrukcje** (textarea → `updateProject`) + **wiedza**
  (lista/dodaj/usuń + „Attach all" — gdy podano `onAttach`, tj. w czacie) + **delete** (z
  potwierdzeniem). Wchłonął logikę `KnowledgePopover` (plik **usunięty**). Wejście w szczegóły
  wybiera projekt (kolekcje są skopowane do aktywnego). Usunięto „Recent folders" z przełącznika.
- `components/ChatView.tsx` — `<ProjectSwitcher conn={conn} onAttach={att.add} />` (usunięty osobny
  `<KnowledgePopover>`); lista rozmów filtrowana `conversationsForProject(convo.convos,
  hub.currentProjectId)`; „New chat" dziedziczy `hub.currentProjectId`.
- `components/Gallery.tsx` / `History.tsx` — `<ProjectSwitcher conn={conn} />` (bez wiedzy).
- **Grupowanie rozmów:** `lib/storage.ts` — `Conversation` + `project_id?`, `newConversation(projectId?)`,
  czysta `conversationsForProject(convos, projectId)`; `lib/useConversations.ts` — `createChat(projectId?)`.

## 4. Migracja i kompatybilność (WAŻNE)
- DB: idempotentne `ALTER TABLE` + backfill `kind` (root≠'' → code). **Konsekwencja:** każdy projekt
  z folderem (np. „Test27", „VN Shift_files") staje się `code` i **znika z przełącznika czatu**; jego
  historia/artefakty nie są kasowane — są pod projektem `code`, widoczne w Galerii/Historii pod
  „All projects".
- Ustawienia: legacy `current_project_id` wskazujący projekt Code → zerowany przy starcie.
- localStorage: rozmowy bez `project_id` traktowane jak „bez projektu" (widoczne pod „All projects").

## 5. Self-checki
- `tools/smoke_routes.py` `_unit_projects_routes` (rozszerzony): `create` → `kind='chat'`; projekt
  `code` niewidoczny w `list(kind='chat')`; `record_event(mode='code')` stempluje projekt Code, nie
  czatu; `PATCH` rename+instrukcje; `current_project()` wystawia instrukcje; `DELETE` kaskaduje +
  czyści aktywny; 404 dla PATCH/DELETE nieznanego.
- `desktop/test/storage.test.ts` — `newConversation(projectId)` + `conversationsForProject`.
