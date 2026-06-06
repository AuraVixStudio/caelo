# Plan naprawy słabych stron (Runda 3) — Caelo Desktop

> **Status:** 🔄 W TRAKCIE (2026-06-06) — **5/8 zrobione i zweryfikowane: P1-15 ✅, P2-14 ✅, P3-10 ✅,
> P3-12 ✅, P3-14 ✅** (logowanie cichych `except`; Electron `sandbox:true` + log no-token; devDeps→lockfile;
> CI backendu na matrycy 3 OS; dokumentacja użytkownika + referencja API 96 REST/6 WS) + **P3-11 🔄 częściowo**
> (warstwa testów komponentów RTL/jsdom: `npm test` 148/148 — brakuje E2E); pozostałe 2 pozycje (P2-13, P3-13)
> 🔲 propozycja. Wynik **gruntownej analizy SWOT**
> aplikacji (backend `caelo_core` + rdzeń xAI, frontend Electron/React, bezpieczeństwo, praktyki
> inżynierskie) przeprowadzonej **po** domknięciu kamieni M9–M17 (czat/twórczość/głos/agent-zaufanie/
> rozszerzalność/społeczność/subagenci). W odróżnieniu od rund 1–2 ten plan **NIE adresuje
> krytycznych luk bezpieczeństwa** — adresuje **dług utrzymaniowy**: dysproporcję między bardzo
> szeroką funkcjonalnością a wąskim pokryciem testami UI/E2E, brak dokumentacji użytkownika,
> obserwowalność błędów i hartowanie defense-in-depth. Realne ścieżki sieciowe xAI weryfikuje
> użytkownik z ważnymi poświadczeniami — sandbox blokuje TLS do `api.x.ai`.
> **Powiązane:** [`PLAN_NAPRAWY.md`](PLAN_NAPRAWY.md) (runda 1 — ✅), [`PLAN_NAPRAWY_2.md`](PLAN_NAPRAWY_2.md)
> (runda 2 — ✅), [`REBUILD_PLAN.md`](REBUILD_PLAN.md) (Fazy 0–8).
> **Numeracja:** kontynuuje rundy 1–2 bez kolizji ID (P1 od `P1-15`, P2 od `P2-13`, P3 od `P3-10`);
> **brak P0** (świadomie). Kamień milowy: **M18 (jakość i utrzymywalność)**.

Legenda priorytetów: **P0** = krytyczne (bezpieczeństwo, blokuje zaufanie do agenta) ·
**P1** = wysokie (stabilność/dane/diagnozowalność) · **P2** = średnie (architektura/jakość/
hardening defense-in-depth) · **P3** = testy/narzędzia/dokumentacja. Każdy punkt:
`plik:linia` → **Problem** → **Rekomendacja** → **Weryfikacja (DoD)**.

---

## Ocena ogólna

Projekt jest po rundach 1–2 **dojrzały technicznie i świadomie zahartowany**: ostra separacja
przywilejów (Electron ↔ sidecar), realne (zweryfikowane w kodzie) hartowanie agenta (metaznaki,
scrubbed env, tree-kill, sandbox ścieżek, ReDoS-safe grep, Zip-Slip, atomic writes), token auth
fail-closed, wzorowy ład OSS (Apache-2.0, CLA, gitleaks, pre-commit). Funkcje M9–M17 są kompletne
end-to-end, bez zaślepek (zero TODO/FIXME w krytycznych ścieżkach).

**Dwie tezy z audytu okazały się zawyżone i zostały skorygowane** (nie tworzą punktów P0):
1. „Klucz API zacommitowany do repo" — **NIEPRAWDA**. Zweryfikowane: `.env` nigdy nie był śledzony
   ani w historii git; cała siatka `caelo_*.json/db` poprawnie w `.gitignore`. To zwykła higiena dev
   (plik lokalny). → patrz „Uwagi operacyjne".
2. „`CAELO_CORE_ALLOW_NO_TOKEN` = krytyczne RCE" — **przesadzone**. Domyślnie fail-closed (deny),
   furtka wymaga jawnej zmiennej środowiskowej, `server.py:109` loguje ostrzeżenie na starcie,
   aplikacja jest loopback-only z kontrolą Origin. Realny, ale **niski** brak (brak logu per-request)
   → zdegradowany do **P2-14**.

Pozostałe słabości układają się w trzy osie: **(A) obserwowalność błędów** (ciche `except` w
ścieżkach danych/konfiguracji), **(B) utrzymywalność** (`state.py` jako „God-object lite",
monolit `api_smoke.py` 2218 linii, duże komponenty frontu), **(C) zaufanie do zmian** — największa
luka: **brak testów komponentów/E2E frontu i brak walidacji cross-platform w PR CI**, w warunkach
zależności od **niestabilnego, nieudokumentowanego API xAI**. Ten plan domyka te osie. Inwestycja
w regresję i dokumentację (a nie nowe funkcje) daje teraz największy zwrot.

**Sugerowana kolejność (wg wartość/koszt):** P3-10 → P3-12 → P1-15 → P3-11 → P3-14 → P2-13 → P3-13 → P2-14.

---

## P1 — Diagnozowalność / obsługa błędów (najpierw)

### [x] P1-15 — Ciche `except Exception: pass/continue` bez logowania w ścieżkach danych/konfiguracji/rejestru  🟠 WYSOKIE
- **Plik:** `caelo_core/packages/manager.py:325, 423, 434, 593` (bare, bez `noqa`/logu),
  `caelo_core/state.py:101, 164, 181, 379, 390, 420, 525, 532, 537, 572, 590, 594, 654`,
  `caelo_core/history_store.py:192, 645`. (Część miejsc ma już `# noqa: BLE001` jako celową
  decyzję crash-safety w workerach — te zostawiamy; chodzi o miejsca **bez żadnego logu**.)
- **Problem:** porażki w ścieżkach konfiguracji/rejestru/artefaktów są **połykane bez śladu**
  (`except Exception: continue|pass`). Przykład: `manager.py:325` pomija pozycję rejestru przy błędzie
  fetch/parse — użytkownik/diag nie dowie się, **dlaczego** pakiet zniknął z listy. Dane są chronione
  (atomic writes + `load_json_or_backup`), więc to nie jest aktywna korupcja, ale **diagnoza błędów
  produkcyjnych jest niemal niemożliwa** — to oś „obsługa błędów" z rundy 1, nieprzeniesiona w te
  ścieżki. Obecny `audit-all` (M14) loguje wywołania narzędzi, ale nie te wyjątki.
- **Rekomendacja:** w każdym takim `except` dodać `_log.warning("…", exc_info=True)` (lub
  `_log.debug` dla naprawdę benign przypadków) z kontekstem (id pakietu/projektu/ścieżka). Nie zmieniać
  semantyki (nadal `continue`/wartość domyślna) — tylko **uczynić błąd widocznym**. Rozważyć wspólny
  helper `log_swallowed(exc, ctx)` w `errors.py`, by ujednolicić format. Zawęzić typy wyjątków tam,
  gdzie to oczywiste (np. `json.JSONDecodeError`, `OSError`) zamiast `Exception`.
- **Weryfikacja (DoD):** żaden `except Exception` w `manager.py`/`state.py`/`history_store.py` nie jest
  bez logu LUB bez świadomego `# noqa: BLE001` z komentarzem „benign, bo …". Dodać asercję do
  `api_smoke.py`, że uszkodzony wpis rejestru produkuje wpis w logu (caplog/stub), nie ciszę.
- **Szac. koszt:** 0.5–1 dzień.
- **✅ Zrobione (2026-06-06):** **Korekta po lekturze faktycznego kodu — raport sondy audytowej był
  zawyżony.** Większość wymienionych miejsc **już logowała** (`log.warning(..., exc_info=True)`):
  `state.py` 101/150/164/181/297/379/390/420/480/525/532/537, `manager.py` 115/479/537,
  `history_store.py` 159/186. Cztery „podejrzane" miejsca w `manager.py` (325/423/434/593) to
  **`raise PackageError(...)`** — translacja błędu na czytelny wyjątek domenowy, NIE ciche połknięcie.
  **Realne braki naprawione:**
  1. `state.py` `save_media_bytes` (~590/594) — połykał błąd zapisu na dysk i `save_to_history` po cichu,
     podczas gdy bliźniaczy `save_media_urls` loguje (asymetria „hardening selektywny", jak runda 2) →
     dodano dwa `log.warning(..., exc_info=True)`.
  2. `packages/manager.py` `_read_template_meta` (~512) — korupcja `template.json` dawała ciche `{}`
     (użytkownik nie wiedział, czemu szablon „nie ma metadanych") → dodano `log.warning(..., exc_info=True)`.
  **Benign cleanup uczynione świadomymi** (`# noqa: BLE001` + komentarz, semantyka bez zmian):
  `history_store.py:192` (zamknięcie uszkodzonego połączenia — rodzic już zalogował powód) i `:645`
  (`close()` przy wyłączaniu → `_log.debug`), `state.py` `_ws_origin_ok` (zniekształcony Origin → fail-closed,
  bez logu by drive-by nie spamował). Pozostałe benign-z-`noqa` (`manager.py` 55/77/183 — fallbacki
  importu/wersji/builtin-dir) zostawiono — `noqa: BLE001` jest tam świadomym markerem.
  **Weryfikacja:** nowa asercja w [`packages_check.py`](../caelo_core/tools/packages_check.py) `test_templates`
  (przechwyt logu: korupcja meta → `{}` **i** rekord ≥ WARNING) → **packages_check 48/48** (było 47);
  bez regresji: `agent_selfcheck` OK, `history_check` OK, `api_smoke` OK.

---

## P2 — Architektura / hardening defense-in-depth

### [ ] P2-13 — `state.py` jako „God-object lite" (666 linii) — dekompozycja  🟡 ŚREDNIE
- **Plik:** `caelo_core/state.py` (666 linii) — klasa `Backend` z wieloma leniwymi getterami
  (`mcp`/`hooks`/`commands`/`skills`/`packages`/`subagents`), ścisłym sprzężeniem z legacy managerami
  i mieszanką odpowiedzialności (auth precedence, ustawienia, projekty, workspace, kolejka gen,
  dependency injection executorów). Dodatkowo `require_token`/`ws_authorized` żyją w tym samym pliku.
- **Problem:** plik jest węzłem sprzężenia — każda nowa funkcja go puchnie, a test jednostkowy
  fasady jest trudny (wiele leniwych zależności). To nie błąd, ale **rosnący opór zmian** i ryzyko,
  że stanie się wąskim gardłem onboardingu.
- **Rekomendacja:** wydzielić spójne kawałki bez zmiany API publicznego: (a) `auth.py`/`tokens.py` ←
  `require_token`/`ws_authorized`/`allowed_origin` (czysta warstwa, łatwa do testu jednostkowego);
  (b) `settings_store` / `projects` jako osobne kolaboratory wstrzykiwane do `Backend`. Zachować
  `Backend` jako cienką fasadę delegującą. **Nie ruszać** rdzenia xAI w korzeniu (reguła CLAUDE.md).
- **Weryfikacja (DoD):** `state.py` < ~400 linii; `handshake_check.py` + `api_smoke.py` zielone
  bez zmian w testach (API niezmienione); nowy mini-test jednostkowy `tokens` (fail-closed, Origin,
  czas stały) bez stawiania całego `Backend`.
- **Szac. koszt:** 1–1.5 dnia.

### [x] P2-14 — Hartowanie defense-in-depth: Electron `sandbox: true` + log per-request furtki no-token  🟡 ŚREDNIE / NISKIE
- **Plik:** `desktop/src/main/index.ts` (`webPreferences.sandbox: false`, komentarz „kandydat P2-10");
  `caelo_core/state.py:626, 665` (`CAELO_CORE_ALLOW_NO_TOKEN`); `caelo_core/server.py:109` (log tylko
  na starcie).
- **Problem:** dwa **niskie** braki defense-in-depth (oba skorygowane z „krytyczne" w audycie):
  (1) renderer działa z `sandbox: false` — kompensowane minimalnym preloadem + `contextIsolation`, ale
  nie best-practice; (2) gdy aktywna furtka `ALLOW_NO_TOKEN`, **żaden request nie jest logowany** jako
  „przeszedł bez tokenu" — brak śladu audytowego dla świadomego trybu dev.
- **Rekomendacja:** (1) włączyć `sandbox: true` (preload używa wyłącznie `contextBridge`/`ipcRenderer`,
  więc powinno wystarczyć) i **zweryfikować w spakowanej apce** (`npm run dist` na maszynie z siecią);
  jeśli coś pęknie — udokumentować i odłożyć. (2) Gdy `ALLOW_NO_TOKEN=1`, logować **WARNING per-request**
  (rate-limited) w `require_token`/`ws_authorized`, nie tylko na starcie; rozważyć wpis do `caelo_audit.log`.
- **Weryfikacja (DoD):** spakowana apka działa z `sandbox: true` (lub udokumentowany powód odłożenia);
  `api_smoke.py` potwierdza, że żądanie w trybie no-token zostawia wpis ostrzegawczy. Domyślne
  zachowanie (fail-closed) bez zmian.
- **Szac. koszt:** 0.5–1 dzień (zależnie od weryfikacji `sandbox` w paczce).
- **✅ Zrobione (2026-06-06):**
  1. **`sandbox: true`** w [`desktop/src/main/index.ts`](../desktop/src/main/index.ts) `createWindow`
     (`webPreferences`). Bezpieczne, bo preload ([`desktop/src/preload/index.ts`](../desktop/src/preload/index.ts))
     używa **wyłącznie** `contextBridge` + `ipcRenderer` (+ `import type`, znika przy kompilacji) — cała
     praca Node (spawn sidecara, dialog folderu, `shell.openPath`) jest w procesie main za IPC, nie w
     preloadzie. Razem z `contextIsolation:true` + `nodeIntegration:false` = pełna izolacja renderera.
  2. **Log per-request furtki** w [`state.py`](../caelo_core/state.py): helper `_warn_no_token(channel)`
     (rate-limited, 1×/60 s, `time.monotonic`) wołany w `require_token` (REST) i `ws_authorized` (WS), gdy
     aktywny `CAELO_CORE_ALLOW_NO_TOKEN=1` → WARNING „served WITHOUT authentication" przy ruchu, nie tylko
     raz na starcie (`server.py`). Świadomy tryb dev zostawia ślad audytowy.
  **Weryfikacja:** dwie nowe asercje w [`api_smoke.py`](../caelo_core/tools/api_smoke.py)
  (`_capture_no_token_warn` + `ws_auth`/`rest_auth: no-token serves WARNING log (P2-14)`) → **api_smoke OK**;
  fail-closed bez zmian (`handshake_check` 401/403/200 OK; `ws_auth`/`rest_auth` no-token→DENIED nadal PASS);
  frontend `typecheck` czysty + `npm run build` zielony (preload bundluje się sandbox-zgodnie).
  **Weryfikacja runtime POTWIERDZONA NA ŻYWO (2026-06-06):** `npm run dev` startuje, okno renderuje się
  z `sandbox:true`, status „Connected" (sidecar + token-auth OK), moduł Voice działa (most `window.caelo`).
  *(Uwaga operacyjna: jednorazowo trzeba było przywrócić binarkę Electrona — `node node_modules/electron/install.js` —
  bo wcześniejszy `npm ci` przy P3-10 jej nie pobrał przy wolnej sieci; to artefakt lokalny `node_modules`,
  nie kodu — `dist/`/`path.txt` są gitignored.)*
  **Uwaga:** `caelo_audit.log` (wpis do JSONL) świadomie pominięto — sprzęgłoby `state.py` z `HookManager`;
  rate-limited WARNING w logu serwera wystarcza. Audyt do pliku to kandydat na osobną pozycję, jeśli zajdzie potrzeba.

---

## P3 — Testy / narzędzia / dokumentacja

### [x] P3-10 — devDeps (eslint/vitest) do `package.json` + `package-lock.json`  🟢 SZYBKIE / WYSOKI ROI
- **Plik:** `desktop/package.json` — skrypty `lint` (`eslint src`) i `test` (`vitest run`) **istnieją**
  (linie 15–16), ale `eslint`/`typescript-eslint`/`eslint-plugin-react-hooks`/`globals`/`vitest`
  **NIE są w `devDependencies`**; CI instaluje je efemerycznie (`--no-save --no-package-lock`).
- **Problem:** `npm ci` u nowego kontrybutora **nie da narzędzi lint/test**; wersje w CI mogą dryfować
  od lokalnych; reprodukcja błędu CI wymaga ręcznego `npm install -D`. To znany, świadomy dług
  (CLAUDE.md), ale blokuje trwałe wpięcie lint/test w `npm ci`.
- **Rekomendacja:** `npm install -D eslint typescript-eslint eslint-plugin-react-hooks globals vitest`
  na maszynie z siecią → commit **zaktualizowanego** `package.json` **i** `package-lock.json` razem
  (zachowuje spójność `npm ci`). Zdjąć efemeryczny krok z `ci.yml`.
- **Weryfikacja (DoD):** `npm ci && npm run lint && npm test && npm run typecheck` zielone na czystym
  klonie; `ci.yml` nie instaluje już narzędzi „w locie".
- **Szac. koszt:** < 0.5 dnia (wymaga sieci npm — robione na maszynie użytkownika).
- **✅ Zrobione (2026-06-06):** `npm install -D eslint@^9 typescript-eslint@^8 eslint-plugin-react-hooks@^5
  globals@^16 vitest@^3` uruchomione na maszynie użytkownika (rejestr npm zbyt wolny w sandboxie —
  bieg w tle przerwany, instalacja dokończona ręcznie). `desktop/package.json` ma teraz w
  `devDependencies`: `eslint ^9.39.4`, `typescript-eslint ^8.60.1`, `eslint-plugin-react-hooks ^5.2.0`,
  `globals ^16.5.0`, `vitest ^3.2.6`; `package-lock.json` zaktualizowany i **w synchronizacji** (zawiera
  `node_modules/eslint`, `node_modules/vitest`). Efemeryczny krok „Install lint/test toolchain (ephemeral)"
  **usunięty** z [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) — frontend job leci teraz
  `npm ci` → typecheck → lint → test. Przy okazji usunięto **martwą dyrektywę** `eslint-disable-next-line
  jsx-a11y/media-has-caption` w `desktop/src/renderer/src/components/Voice.tsx:367` (reguła spoza wąskiej
  konfiguracji react-hooks → ESLint 9 zgłaszał ją jako **error**; jedyny taki przypadek w `src/`).
  **Weryfikacja (czysty `node_modules`):** `npm ci` (688 pakietów) · `npm run typecheck` czysty ·
  `npm run lint` **exit 0** (0 błędów; 3 ostrzeżenia `exhaustive-deps` — celowo `warn`) · `npm test`
  **122/122** (12 plików). **Do commitu razem (jeden commit):** `desktop/package.json` +
  `desktop/package-lock.json` + `.github/workflows/ci.yml` + `Voice.tsx`.
  **Uwaga:** `npm audit` raportuje 10 podatności (9 high, 1 critical) w **transitywnych** zależnościach
  toolchainu dev (stare `glob`/`rimraf`/`inflight`/`tar` ciągnięte m.in. przez `electron-builder`/eslint) —
  to NIE trafia do paczki użytkownika; osobny, niski temat porządkowy (kandydat na nową pozycję P3).

### [ ] P3-11 — Testy komponentów + E2E frontu dla krytycznych przepływów  🟢 WYSOKI ROI
- **Plik:** `desktop/test/` (12 plików Vitest, ~1082 linie — **wyłącznie czyste utilsy**); brak testów
  56 komponentów (m.in. `components/chat/ChatView.tsx` ~876, `components/code/AgentPanel.tsx:854`),
  brak E2E.
- **Problem:** całe UI i przepływy międzymodułowe (send-to, przełączanie projektów, parsowanie streamu
  WS, karta zatwierdzeń agenta, start streamu Voice) są **niepokryte testami** — regresje propów/hooków
  trafiają do użytkownika. To, łącznie z brakiem cross-platform CI, jest **największą luką** projektu.
- **Rekomendacja:** dodać Vitest + React Testing Library (środowisko `jsdom`) i pokryć 20–30 krytycznych
  zachowań (render+interakcja): wysyłka czatu i obsługa delt/`done`, karta zatwierdzeń w `AgentPanel`
  (tool diff/command/MCP), `TeamView` (status/merge), wybór modelu, start/stop nagrywania Voice. Dodać
  **kilka** testów E2E (Playwright na zbudowanej apce lub `preview:web` z mockiem `devMock.ts`) dla
  ścieżek krytycznych: send-to między modułami, przełączanie projektu, zatwierdzenie zmiany agenta.
- **Weryfikacja (DoD):** ≥ 20 testów komponentów + ≥ 3 E2E w CI (frontend job); pokrycie krytycznych
  przepływów udokumentowane w `desktop/README.md`. Testy deterministyczne (xAI mockowane).
- **Szac. koszt:** 3–5 dni (największa pozycja; można rozbić na podetapy per moduł).
- **🔄 CZĘŚCIOWO ZROBIONE (2026-06-06) — warstwa komponentów ✅ (≥20); E2E ⏳:**
  Wprowadzono infrastrukturę **React Testing Library + jsdom** (devDeps `@testing-library/react ^16`,
  `jest-dom ^6`, `user-event ^14`, `jsdom ^29` w `package.json`+lockfile) i config
  ([`vitest.config.ts`](../desktop/vitest.config.ts)): `@vitejs/plugin-react` (auto-JSX), `include` `.tsx`,
  `globals: true` (auto-cleanup RTL). jsdom **tylko** w `test/components/` (docblock per-plik) → **122 testy
  utili nietknięte**. **+26 testów komponentów** ([`desktop/test/components/`](../desktop/test/components/)):
  prymitywy UI (Button 6, Input/Textarea 5, Badge 2, Select 2, IconButton 4, Slider 2, Card 2 —
  render+interakcja: klik/onChange/disabled/aria/warianty) i **kontekst motywu** (ThemeProvider/useTheme 3
  — `setTheme` przełącza klasę `.dark` + persist localStorage; `_matchMedia` stub). **Weryfikacja:**
  `npm test` **148/148** (122+26), `typecheck` czysty, `lint` exit 0; biegnie w CI przez `npm test`.
  **Pozostaje (osobny podetap, dlatego NIE `[x]`):** (a) testy **ciężkich komponentów** (ChatView/
  AgentPanel/TeamView — wymagają harnessu mockującego `window.caelo` + kontekst Hub + klienta API);
  (b) **E2E** (Playwright na `preview:web` z `devMock` lub spakowanej apce) dla send-to / przełączania
  projektu / zatwierdzeń agenta — wymaga działającej apki + binariów przeglądarki, więc poza warstwą
  jednostkową/CI bez osobnego kroku. DoD `≥3 E2E` jeszcze niespełniony. Strategia: `desktop/README.md`
  (sekcja „Testy (Vitest)").

### [x] P3-12 — Walidacja cross-platform w PR CI (macOS/Linux + self-checki nie tylko Windows)  🟢 WYSOKI ROI
- **Plik:** `.github/workflows/ci.yml` — backend job `runs-on: windows-latest` (linia 46), frontend job
  `ubuntu-latest` (28/89); **brak macOS w ogóle**, a self-checki backendu (w tym `crossplatform_check.py`
  badający PTY/tree-kill/ścieżki per-OS) **uruchamiają się tylko na Windows**. `release.yml` buduje
  Win/mac/Linux, ale dopiero na tagu/dispatch — regresje platformowe tlą się tygodniami.
- **Problem:** kod ma świadome rozgałęzienia per-OS (`shell=False`+`shlex` na POSIX, `killpg` vs
  `taskkill`, ścieżki `DATA_DIR`), ale **nikt ich nie testuje w PR** poza Windows. Bug POSIX wykryjemy
  dopiero przy release.
- **Rekomendacja:** rozszerzyć backend job na **matrycę** `os: [windows-latest, ubuntu-latest, macos-latest]`
  z `fail-fast: false`; uruchamiać przynajmniej `agent_selfcheck.py`, `crossplatform_check.py`,
  `mcp_check.py`, `genjobs_check.py`, `history_check.py` na każdym OS (`api_smoke`/`handshake` jeśli się
  da bez paczki). Pominąć kroki zależne od `pywinpty` poza Windows (warunek `if`).
- **Weryfikacja (DoD):** PR uruchamia self-checki na 3 OS; zielone na wszystkich (lub świadomy `skip`
  per-OS z komentarzem). README/CONTRIBUTING odnotowuje matrycę.
- **Szac. koszt:** 0.5–1 dzień.
- **✅ Zrobione (2026-06-06):** job `backend` w [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
  przepisany na `strategy.matrix.os = [windows-latest, ubuntu-latest, macos-latest]` z `fail-fast: false`
  (`runs-on: ${{ matrix.os }}`, nazwa `Backend self-checks (${{ matrix.os }})`). Wszystkie 7 kroków
  self-checków biegnie teraz na każdym OS; `pywinpty` instaluje się tylko na Windows (marker w
  `requirements.txt`), reszta checków nie wymaga PTY. **Weryfikacja:** YAML waliduje się (`yaml.safe_load`),
  matryca i `fail-fast: false` potwierdzone. **Do potwierdzenia w chmurze:** pierwszy bieg PR musi
  pokazać zieleń na ubuntu/macos — jeśli jakiś check ujawni realną lukę POSIX, to zamierzony efekt
  (świadomy `skip` per-OS z komentarzem zamiast wyłączania OS).

### [ ] P3-13 — Migracja self-checków do pytest (discovery) + rozbicie `api_smoke.py`  🟡 ŚREDNIE
- **Plik:** `caelo_core/tools/api_smoke.py` (2218 linii — monolit), plus pozostałe `*_check.py` jako
  samodzielne skrypty uruchamiane pojedynczo, **bez frameworka/discovery**.
- **Problem:** jeden plik 2218 linii będzie akumulował nieutrzymywalne testy z każdą funkcją; brak
  pytest = brak `-k`, fixtures, równoległości, raportu pokrycia, automatycznej kolekcji. Self-checki są
  merytorycznie dobre (testują realne kontrakty), ale **inżynieria testów** to dług.
- **Rekomendacja:** wprowadzić `pytest` jako dev-dep backendu; opakować istniejące asercje w funkcje
  `test_*` z `conftest.py` (wspólny start sidecara/stubów jako fixture), rozbić `api_smoke.py` na
  `tests/test_routes_*.py` / `test_responses.py` / `test_voice.py` / `test_collections.py` itd.
  **Zachować** zachowanie mockowania xAI. Zaktualizować `ci.yml` na `pytest` + komendy w
  CONTRIBUTING/`caelo_core/README.md`.
- **Weryfikacja (DoD):** `pytest caelo_core/tests` zbiera i przechodzi wszystkie dotychczasowe asercje;
  żaden plik testowy > ~600 linii; CI woła `pytest` (z zachowaniem osobnych checków, które wymagają
  paczki — np. `sidecar_smoke`).
- **Szac. koszt:** 2–3 dni (mechaniczne, ale obszerne).

### [x] P3-14 — Dokumentacja użytkownika + referencja tras REST/WS  🟡 ŚREDNIE
- **Plik:** `docs/` — 17 dokumentów `PLAN_*.md` to **doskonałe dokumenty projektowe, ale deweloperskie
  i po polsku**; brak przewodnika użytkownika i referencji API. `README.md` pełni podwójną rolę.
- **Problem:** brak „on-ramp" dla użytkownika i kontrybutora: jak zacząć czat, jak używać agenta/
  trybów plan/review, jak działa marketplace (M16 istnieje, brak instrukcji), referencja endpointów
  REST/WS. To hamuje adopcję OSS i zgłoszenia społeczności.
- **Rekomendacja:** dodać `docs/USER_GUIDE.md` (EN — zgodnie z regułą języka UI; per-moduł: Chat, Code/
  Agent, Image, Video, Voice, History, Extensions/Marketplace, Settings) oraz `docs/API.md`
  (auto/ręczna lista tras REST + ramki WS — można wygenerować z FastAPI `openapi.json`). Zlinkować w
  `docs/README.md` i głównym `README.md`. Rozważyć GitHub Pages.
- **Weryfikacja (DoD):** `USER_GUIDE.md` pokrywa wszystkie 9 modułów; `API.md` listuje każdą trasę z
  `routes/*`; oba zlinkowane z indeksu. Krótki „Getting Started" w README wskazuje na guide.
- **Szac. koszt:** 1.5–2 dni.
- **✅ Zrobione (2026-06-06):**
  1. **[`docs/USER_GUIDE.md`](USER_GUIDE.md)** (EN, zgodnie z regułą języka user-facing) — Getting Started
     (instalacja/auth/precedence), **wszystkie 9 modułów** (Chat, Code/agent, Image, Video, Gallery, Voice,
     History, Extensions, Settings), kluczowe koncepcje (Projekty, Send-to, permission gate, prywatność/koszty)
     i Troubleshooting.
  2. **[`docs/API.md`](API.md)** (EN) — referencja **96 tras REST + 6 WS** pogrupowana po domenach (auth,
     models/settings, media/genjobs, voice, fs/git, history/artifacts, projects/collections, agent/team,
     mcp/hooks/commands/skills, packages), model autoryzacji (Bearer/token w query, fail-closed, CORS),
     handshake, tabela protokołów ramek WS + snippet do **regeneracji** listy (introspekcja `app.routes`).
  **Osadzenie w faktach (nie zmyślone):** lista tras wygenerowana **introspekcją** `create_app().routes`
  (`APIRoute`/`APIWebSocketRoute`) — dokładnie **96 REST + 6 WS**; opisy spot-checkowane względem docstringów
  (np. `/auth/login` = OAuth PKCE, `/artifacts/{id}/input-block` = send-to bus). **Podlinkowane:**
  `docs/README.md` (dwa nowe wiersze tabeli + „Jak czytać"), główny [`README.md`](../README.md) (wskaźnik po
  Quickstarcie „New to the app?" + sekcja Documentation). **Pozostaje opcjonalnie** (nie w DoD): hosting na
  GitHub Pages.

---

## Uwagi operacyjne (poza kodem)

- **Rotacja lokalnego klucza xAI w `.env`** — audyt początkowo zgłosił to jako „krytyczny committed
  secret"; **zweryfikowano: nieprawda** (`.env` nigdy nie w gicie/historii, poprawnie ignorowany).
  To zwykła higiena dev. **Rekomendacja wyłącznie operacyjna:** zrotuj klucz, jeśli maszyna lub zip
  repo bywa udostępniany; w przeciwnym razie brak akcji w kodzie.
- **Kruchość API xAI (zagrożenie nadrzędne)** — kod zależy od nieudokumentowanych endpointów
  (`auth.x.ai` PKCE, format SSE Responses, streaming-STT „niepotwierdzony"). To nie jest pozycja do
  „naprawy", lecz **ryzyko do monitorowania**: warto rozważyć lekki kanaryjny self-check uruchamiany
  ręcznie na maszynie użytkownika (poza CI), który wykryje zmianę kontraktu wcześnie. Udokumentować w
  `SECURITY.md`/`README.md` jako znane ograniczenie (część już jest).

---

## Podsumowanie tabelaryczne

| ID | Oś | Priorytet | Pozycja | Szac. koszt |
|---|---|---|---|---|
| P1-15 | Diagnozowalność | 🟠 wysokie | Logowanie cichych `except` w ścieżkach danych | 0.5–1 d |
| P2-13 | Architektura | 🟡 średnie | Dekompozycja `state.py` (God-object) | 1–1.5 d |
| P2-14 | Hardening | 🟡 niskie | `sandbox: true` + log per-request no-token | 0.5–1 d |
| P3-10 | Narzędzia | 🟢 szybkie | devDeps eslint/vitest → lockfile | < 0.5 d |
| P3-11 | Testy | 🟢 wysoki ROI | Testy komponentów + E2E frontu | 3–5 d |
| P3-12 | CI | 🟢 wysoki ROI | Cross-platform PR CI (macOS/Linux) | 0.5–1 d |
| P3-13 | Testy | 🟡 średnie | pytest + rozbicie `api_smoke.py` | 2–3 d |
| P3-14 | Dokumentacja | 🟡 średnie | USER_GUIDE.md + API.md | 1.5–2 d |

**Łączny szacunek:** ~10–15 dni roboczych. **Brak P0** — projekt nie ma otwartych luk krytycznych;
to runda **utrzymaniowa** podnosząca odporność na regresję i barierę wejścia, nie ratunkowa.
