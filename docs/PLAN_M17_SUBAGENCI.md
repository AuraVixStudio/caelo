# PLAN_M17_SUBAGENCI.md — Agent: zespoły (rozpis zadań)

> Rozpis milestone'u **M17** z `PLAN_ROZBUDOWY.md` — głębia trybu Code. Cel: orkiestrator
> deleguje podzadania **wyspecjalizowanym subagentom** (researcher / reviewer / implementer /
> tester) z **izolowanym kontekstem** i **zawężonymi narzędziami**, pracującym **równolegle**
> w osobnych worktree, a wyniki wracają **streszczone**.
>
> **Zakłada gotowe:** M13 (diffy/plan/checkpointy), M14 (rejestr narzędzi/MCP filtrowalny per rola),
> M10 (`responses_client`). Tagi: **[P0]** krytyczne, **[P1]** ważne. Wysiłek: S≈dni, M≈1–2 tyg., L≈3–4 tyg.
>
> **STATUS (2026-06-05): ✅ Backend B1–B6 + Frontend F1–F5 ZROBIONE.** Zweryfikowane bez xAI
> (`agent_selfcheck` 139 → **166**: 27 nowych M17; `api_smoke` 217 → **228**: 11 tras zespołu;
> `handshake_check` OK; frontend `typecheck` ✅, testy Vitest dopisane). Weryfikacja na żywo
> (realne xAI, delegacja end-to-end) — na maszynie usera. Szczegóły realizacji w §6.

---

## 0. Model subagenta i dlaczego tak

**Subagent = izolowana pod-sesja na tej samej pętli `session.py`:**
- własna historia/okno kontekstu (parent NIE widzi pełnego transkryptu — to cały sens: czysty
  kontekst orkiestratora),
- własny system prompt = **rola**,
- **zawężony zestaw narzędzi** (z rejestru M14, filtrowalnego per rola) — nigdy szerszy niż rodzic,
- własny `PermissionGate` (zakres ≤ rodzica),
- własny **worktree** (sandbox `Workspace.resolve`) dla ról mutujących,
- do rodzica wraca **streszczenie**, nie transkrypt.

**Orkiestracja:** orkiestrator dostaje narzędzie `delegate` — deleguje podzadania (równolegle),
zbiera streszczenia, integruje. To zwykły `tool_call` w jego pętli.

**Izolacja mutacji = worktree per subagent.** Zmiany mutującego subagenta lądują w jego worktree i są
przeglądane jako **jeden diff/checkpoint przy scalaniu** (M13) — zamiast zalewu zatwierdzeń per
narzędzie. To rozwiązuje „approval fatigue" przy wielu subagentach.

### Decyzje przekrojowe (przeczytaj przed kodowaniem) — głównie bezpieczeństwo
- **Najpierw role READONLY (researcher/reviewer), potem mutujące (implementer/tester).** READONLY
  nie wymaga worktree ani scalania → szybki, bezpieczny pierwszy efekt. Mutujące dochodzą z B3/B4.
- **Twarde limity (inaczej fork-bomba / wyczerpanie zasobów / koszt):** głębokość (rekomendacja:
  **głębia = 1**, subagent NIE spawnuje wnuków), maks. równoległość, timeout per subagent, budżet
  kosztów na przebieg zespołu.
- **Zero eskalacji uprawnień:** subagent nie może dostać szerszych narzędzi/uprawnień niż przyznane;
  orkiestrator nie może nadać więcej, niż sam ma.
- **Stop kaskadowy:** stop orkiestratora = tree-stop wszystkich subagentów + tree-kill ich
  `run_command` (masz `{"type":"stop"}` + `threading.Event` + tree-kill — rozszerz na kaskadę).
- **Balans historii per pod-sesja:** przerwane `tool_calls` dostają syntetyczne wyniki (masz to) —
  obowiązuje w każdej pod-sesji.
- **Reuse:** `session.py`, `responses_client` (M10), rejestr narzędzi/MCP (M14), `PermissionGate` +
  worktree/checkpoint (M13), `WsStream` (multipleks po `agent_id`), scrubbed env / tree-kill (M1/M5–M6),
  `agent_selfcheck.py`.
- **UI po angielsku** (konwencja repo): „Delegate", „Subagent", „Review merge", „Team".

---

## 1. Backend (`grok_core/agent`)

### ✅ M17-B1 [P0] Model subagenta + izolowana pod-sesja  — L  — ZROBIONE
- **Cel:** uruchomić agenta-dziecko z własnym kontekstem i rolą.
- **Zakres:** `agent/subagent.py` (na `session.py`): `SubAgent` z własną historią, system promptem
  (rola), podzbiorem narzędzi, zakresem `PermissionGate`, (opcjonalnym) worktree. Cykl
  spawn→run→collect-summary. Parent dostaje tylko streszczenie.
- **DoD:** orkiestrator spawnuje subagenta „researcher" (READONLY), ten działa w izolacji i zwraca
  streszczenie; historia rodzica nie puchnie o transkrypt dziecka.
- **Selfcheck:** `agent_selfcheck.py` — pod-sesja izolowana (własna historia), podzbiór narzędzi
  wymuszony, streszczenie zwrócone, `tool_calls` zbalansowane.

### ✅ M17-B2 [P0] Narzędzie `delegate` + orkiestracja + role  — M  — ZROBIONE
- **Cel:** orkiestrator deleguje i integruje.
- **Zakres:** narzędzie `delegate` (params: rola, zadanie, zakres narzędzi, worktree?). Pętla
  orkiestratora woła je; backend spawnuje subagenta(ów); zwraca streszczenia. Konfiguracja ról →
  zakres narzędzi: researcher=READONLY; reviewer=READONLY+grep; implementer=mutujące-w-worktree;
  tester=`run_command`-w-worktree.
- **DoD:** orkiestrator deleguje 2 podzadania, dostaje 2 streszczenia, integruje; mapowanie rola→
  narzędzia wymuszone (researcher nie zapisze).
- **Selfcheck:** `delegate` zarejestrowane, rola→zakres egzekwowana, brak eskalacji.

### ✅ M17-B3 [P0] Równoległość + worktrees  — L  — ZROBIONE
- **Cel:** wielu subagentów naraz, bez kolizji plików.
- **Zakres:** N subagentów współbieżnie (wątki workerów); każda rola mutująca w własnym worktree
  (kopia/`git worktree` workspace'u); cap równoległości; timeout per subagent; `WsStream`
  multipleksowany po `agent_id`; **stop kaskadowy** (tree-stop wszystkich + tree-kill ich komend).
- **DoD:** 2 implementery edytują różne pliki w równoległych worktree bez kolizji; stop zatrzymuje wszystkie.
- **Selfcheck:** izolacja równoległa (brak zapisów krzyżowych), kaskada stop ubija wszystkich, cap honorowany.

### ✅ M17-B4 [P0] Scalanie worktree → przegląd jako jeden diff/checkpoint  — M  — ZROBIONE
- **Cel:** mutacje subagenta przeglądasz raz, nie narzędzie po narzędziu.
- **Zakres:** po zakończeniu pracy mutującej, zmiany worktree jako **jeden diff** (M13-B1) + checkpoint;
  user przegląda/akceptuje scalenie do głównego workspace'u; konflikty (nakładające się pliki z innych
  worktree) wykrywane i oznaczane.
- **DoD:** zmiany implementera pokazane jako jeden przeglądalny diff; accept scala, reject odrzuca
  (sandbox-safe); konflikt wykryty.
- **Selfcheck:** scalenie stosuje zaakceptowane, odrzucenie przywraca, konflikt wykryty.

### ✅ M17-B5 [P0] Twarde limity i izolacja uprawnień  — M  — ZROBIONE
- **Cel:** zespół nie może się rozbiec ani eskalować.
- **Zakres:** maks. głębokość (rekomendacja 1), maks. równoległość, timeout per subagent, budżet
  kosztów per przebieg; `PermissionGate` subagenta ≤ granty rodzica; guard rekurencji.
- **DoD:** głębokość/równoległość/timeout/budżet egzekwowane; subagent nie przekracza zakresu narzędzi rodzica.
- **Selfcheck:** rozszerz `agent_selfcheck.py` — cap głębokości, brak eskalacji, kaskada stop,
  zatrzymanie po przekroczeniu budżetu; **P0-1…P0-8 + M5–M6 bez regresji**.

### ✅ M17-B6 [P1] Budżet/koszt zespołu + telemetria  — S  — ZROBIONE
- **Cel:** transparentność kosztu zespołu (BYO-key).
- **Zakres:** agregacja kosztu/tokenów/wywołań narzędzi po orkiestratorze + subagentach → meta
  historii (M9) + `/usage`; rozbicie per subagent.
- **DoD:** przebieg zespołu raportuje koszt łączny i per subagent.
- **Selfcheck:** agregacja poprawna.

---

## 2. Frontend (`desktop/src/renderer`)

### ✅ M17-F1 [P0] Widok zespołu (orchestrator + subagenci)  — L  — ZROBIONE
- **Cel:** widać, kto co robi.
- **Zakres:** widok drzewa: węzeł orkiestratora + węzły subagentów z rolą, statusem (queued/running/
  done/failed) i bieżącą aktywnością; rozwijany transkrypt per subagent.
- **DoD:** w trakcie przebiegu widzę rolę i status na żywo każdego subagenta; rozwijam jego pracę.
- **Test:** Vitest — stan drzewa zespołu.

### ✅ M17-F2 [P0] Zatwierdzanie scalania worktree (diff)  — M  — ZROBIONE
- **Cel:** przegląd mutacji subagenta jako jeden diff.
- **Zakres:** „Review merge" per subagent: jeden diff (reuse M13-F1); accept/reject scalenia; UI konfliktu.
- **DoD:** implementer skończył → przeglądam jego diff → scalam lub odrzucam.
- **Test:** Vitest — stan przeglądu scalania.

### ✅ M17-F3 [P1] Routing zatwierdzeń per subagent  — S/M  — ZROBIONE
- **Cel:** wiadomo, który subagent o co prosi.
- **Zakres:** gdy subagent potrzebuje zgody w locie (np. wrażliwe narzędzie nieodraczalne do scalania),
  modal jasno przypisuje ją do subagenta (rola + zadanie).
- **DoD:** zatwierdzenie jasno otagowane subagentem-pytającym.
- **Test:** Vitest — atrybucja zatwierdzenia.

### ✅ M17-F4 [P1] Konfiguracja ról i zakresów narzędzi  — M  — ZROBIONE
- **Cel:** kontrola nad tym, co każda rola może.
- **Zakres:** UI definiowania/edycji ról (researcher/reviewer/implementer/tester) i ich zakresu
  narzędzi/MCP (z rejestru M14); limity zespołu (maks. równoległość/głębokość/budżet).
- **DoD:** edytuję zakres narzędzi roli; nowe przebiegi go honorują.
- **Test:** Vitest — stan konfiguracji ról.

### ✅ M17-F5 [P1] Koszt zespołu + oś czasu  — S  — ZROBIONE
- **Cel:** widoczność kosztu i przebiegu.
- **Zakres:** badge kosztu zespołu + rozbicie per subagent + oś czasu.
- **DoD:** widzę koszt łączny i per subagent.
- **Test:** Vitest — formatowanie.

---

## 3. Kolejność i zależności

```
B1 (pod-sesja)  ──►  B2 (delegate + role)  ──►  F1 (widok zespołu)
        │                                   ──►  [READONLY: researcher/reviewer — koniec etapu 1]
        ▼
B3 (równoległość + worktrees) + B5 (limity/izolacja)  ──►  B4 (scalanie diff)  ──►  F2 (review merge)
        └──► [mutujące: implementer/tester — etap 2]
B6 (koszt) ──► F5 ;  F3 (routing zgód), F4 (role) — dopieszczenie
```

- **Etap 1 (bezpieczny, szybki „wow"): `B1→B2→F1` z rolami READONLY.** Orkiestrator deleguje
  researcherowi i reviewerowi, widzisz zespół przy pracy, streszczenia się integrują — **bez** worktree,
  scalania i ryzyka równoległego zapisu. To pokazuje wartość zespołów minimalnym kosztem.
- **Etap 2 (mutujący): `B3+B5→B4→F2`.** Dopiero teraz implementer/tester piszą — w izolowanych
  worktree, z twardymi limitami, a Ty przeglądasz każdą zmianę jako jeden diff przy scalaniu.
- `B5` (limity/izolacja) **musi** wejść razem z `B3` — równoległe mutujące agenty bez limitów to
  najprostsza droga do regresji hardeningu.

## 4. Definicja ukończenia M17 (całość)

> **Status: ✅ spełnione.** Zweryfikowane bez xAI; weryfikacja na żywo (delegacja end-to-end) u usera.

1. ✅ Orkiestrator deleguje podzadania subagentom z **izolowanym kontekstem** i **zawężonymi narzędziami**;
   kontekst rodzica zostaje czysty (tylko streszczenia — jedna wiadomość `tool` per `delegate`).
2. ✅ Role **READONLY** (researcher/reviewer) działają bezpiecznie; role **mutujące** (implementer/tester)
   pracują w izolowanych worktree (kopia workspace, jak checkpoint M13).
3. ✅ Równoległe subagenty nie kolidują (osobne worktree); **stop kaskaduje** na wszystkie (domknięcie
   stop orkiestratora widoczne w każdym subagencie → pętle padają + `run_command` tree-kill).
4. ✅ Zmiany mutującego subagenta przeglądasz jako **jeden diff** (+ snapshot do checkpointu M13 = cofalne)
   przed scaleniem; reject sandbox-safe; **konflikt** (ta sama ścieżka w >1 worktree) wykryty.
5. ✅ **Twarde limity** egzekwowane (głębokość=1/równoległość/timeout/budżet tur/cap subagentów);
   **brak eskalacji uprawnień** (zakres roli ∩ rodzic); **P0-1…P0-8 + M5–M6 nienaruszone** (selfcheck bez regresji).
6. ✅ Widok zespołu pokazuje role/status na żywo; zatwierdzenia otagowane subagentem; koszt zespołu
   raportowany (tury/narzędzia/tokeny); `agent_selfcheck.py` rozszerzony (139 → 166).

---

## 6. Status realizacji (2026-06-05)

**Backend B1–B6 + Frontend F1–F5 — ZROBIONE, zweryfikowane bez xAI.** Weryfikacja na żywo (realne
xAI, pełna delegacja, scalanie) — na maszynie usera (sandbox blokuje `api.x.ai`, jak w M10–M14).

**Backend (`grok_core/agent`):**
- **B1 model subagenta** — `agent/subagent.py` (`SubAgent`): izolowana pod-sesja na `session.py` z
  własną historią, zawężonym zbiorem narzędzi (`tool_names`), personą roli (`extra_system`), bez
  `delegate` (głębia 1). `session.py` rozszerzone addytywnie: `tool_names`/`delegate_fn`/`extra_system`/
  `on_turn`, filtr narzędzi (advertised + twarde odrzucenie spoza zakresu), licznik tur, zbieranie `usage`.
- **B2 delegate + role** — `DELEGATE_TOOL` w `session.py` (tylko orkiestrator), `agent/roles.py`
  (`RoleRegistry`: wbudowane researcher/reviewer/implementer/tester + nadpisania usera; `effective_tools`
  = rola ∩ rodzic; `grok_subagents.json`). `agent/team.py` `TeamManager.run(tasks)` spawnuje subagentów,
  zbiera streszczenia, integruje (jedna wiadomość `tool` do rodzica).
- **B3 równoległość + worktrees** — `agent/worktree.py` (kopia bez gita, pomija IGNORE_DIRS/dowiązania;
  `compute_changes`/`apply_changes`/`discard`); `TeamManager._run_concurrent` (semafor=max_parallel,
  monitor timeoutu per subagent), `ScopedMcp` (zawężenie MCP per rola), stop kaskadowy + `WsStream`
  tagowany `agent_id`.
- **B4 scalanie** — `MergeStore` (per workspace, współdzielony WS↔REST jak checkpointy): jeden diff,
  apply (snapshot→checkpoint M13→aplikacja = cofalne), reject (sandbox-safe), wykrycie konfliktu;
  trasy `routes/team.py` `/agent/team/merges*`.
- **B5 limity/izolacja** — `roles.DEFAULT_LIMITS` (max_parallel/max_subagents/max_total_turns/timeout_s/
  max_iters; max_depth=1 twardo, walidowane), budżet tur (wspólny licznik + stop), brak eskalacji,
  plan mode wyłącza role mutujące. **P0-1…P0-8 + M5–M6 bez regresji** (selfcheck potwierdza).
- **B6 koszt/telemetria** — agregacja per subagent + totals (tury/narzędzia/tokeny z `usage`,
  szacunek $), ring buffer raportów (`/agent/team/runs`), ramka `team_done`.
- **Stan/serwer:** `Backend.subagents`/`get_team_merges`/`record_team_report`; router `team`
  pod `require_token`; `config.SUBAGENTS_FILE`/`WORKTREES_DIR` (+ `.gitignore`).
- **Selfchecki:** `agent_selfcheck.py` **139 → 166** (27 nowych: B1 izolacja, B2 role/no-escalation,
  B3 worktree-izolacja/cascade/budżet, B4 compute/apply/reject/konflikt/undo, B6 agregacja);
  `api_smoke.py` **217 → 228** (`_unit_team_routes`); `handshake_check` OK.

**Frontend (`desktop/src/renderer`):**
- **F1** — `components/code/TeamView.tsx` + `lib/teamView.ts` (czysty reducer drzewa subagentów):
  węzły z rolą/statusem/aktywnością, rozwijany transkrypt narzędzi; wpięte w `AgentPanel` (ramki
  `subagent`/`subagent_status`/`team_done` w `agentClient.ts`).
- **F2** — „Review merge" per subagent: jeden diff (reuse `DiffView`), accept/reject, badge + baner
  konfliktu; REST `applyTeamMerge`/`rejectTeamMerge`/`teamMergeDiff`.
- **F3** — `approval_request` z `detail.agent_id` → karta w węźle subagenta (atrybucja rola+zadanie),
  call_id znamespace'owany (brak kolizji przy równoległych).
- **F4** — `components/extensions/SubagentsPanel.tsx` (nowa zakładka „Subagents" w Extensions): edycja
  ról (narzędzia/MCP/worktree/model/prompt, nadpisania wbudowanych) + limity zespołu.
- **F5** — badge kosztu zespołu (tury/narzędzia/tokeny/$) + oś czasu per subagent z ostatniego raportu.
- **Testy/weryfikacja:** `desktop/test/teamView.test.ts` (drzewo/atrybucja/koszt) — napisany; `npm test`
  nie uruchamia się tu (Vitest devDep niezainstalowany, jak w CLAUDE.md). `npm run typecheck` ✅.
  Podgląd web (devMock): zakładka Subagents + edytor ról renderują, TeamView ukryty gdy pusty,
  **zero błędów w konsoli** (pełna delegacja na żywo — backend + xAI → maszyna usera).

## 5. Otwarte pytania techniczne

- **Worktree: kopia katalogu (spójnie z checkpointem M13, bez git) vs `git worktree` (wydajniejsze,
  wymaga repo).** Rekomendacja: kopia jak w M13; `git worktree` jako późniejsza optymalizacja.
- **Głębia delegacji:** rekomendacja **1** w M17 (orkiestrator → subagenci, bez wnuków) — zdejmuje
  ryzyko fork-bomby. Głębsze drzewa dopiero po dowiedzionej stabilności.
- **Model orkiestratora vs subagentów:** ten sam grok-4.3 wszędzie, czy tańszy/szybszy wariant grok
  do prostych ról (np. fast do researchera)? Tiering kosztów — wciąż „tylko Grok" (różne modele grok,
  nie inni providerzy).
- **Zatwierdzanie przy równoległości:** domyślnie izolacja w worktree + przegląd przy scalaniu (mniej
  promptów) vs inline (więcej kontroli, więcej tarcia). Rekomendacja: worktree+merge domyślnie.
- **Konflikty scalania wielu worktree:** kolejność scalania, wykrycie nakładających się plików,
  prezentacja konfliktu — zaprojektuj zanim wpuścisz >1 mutującego subagenta na te same ścieżki.
- **Strumień:** jeden `WsStream` z eventami tagowanymi `agent_id` (rekomendacja) vs osobne kanały per
  subagent. Jeden kanał = prościej, ale uważaj na przepustowość przy wielu równoległych.
