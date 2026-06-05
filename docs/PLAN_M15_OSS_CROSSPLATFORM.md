# PLAN_M15_OSS_CROSSPLATFORM.md — Open source + fundament cross-platform (rozpis zadań)

> Rozpis milestone'u **M15** z `PLAN_ROZBUDOWY.md`. Charakter: **rób ciągle, nie na końcu.**
> Dwie połowy: (A) higiena i wydanie open source, (B) neutralność platformowa OD TERAZ +
> pakowanie/aktualizacje. Konkretne buildy mac/Linux — dopiero przy realnym popycie.
>
> Sekcje tematyczne zamiast backend/frontend (to głównie repo/DevOps + kilka miejsc w kodzie).
> „Weryfikacja" tam, gdzie to nie test kodu. Tagi: **[P0]** krytyczne, **[P1]** ważne.
>
> ## ✅ STATUS (2026-06-05): M15 KOMPLETNE — M15-1, 1b, 2–9
> Wszystkie zadania zrobione. **Rebranding → „Caelo"** (pełny, też wewnętrzny: `grok_core`→`caelo_core`,
> `grok_*`→`caelo_*`, `GROK_CORE_*`→`CAELO_CORE_*`, `window.grok`→`window.caelo`, `GROK.md`→`CAELO.md`)
> z **migracją bez utraty danych** (config + localStorage). **Fundament cross-platform:** abstrakcja PTY
> ([`pty_compat.py`](../caelo_core/pty_compat.py)), tree-kill SIGTERM→SIGKILL na POSIX, `DATA_DIR` per-OS,
> audyt Windows-only czysty — nowy selfcheck [`crossplatform_check.py`](../caelo_core/tools/crossplatform_check.py)
> (23/23). **OSS:** Apache-2.0 + NOTICE + CLA(+bot) + CONTRIBUTING + CODE_OF_CONDUCT + SECURITY +
> przepisany README (BYO-key). **Bezpieczeństwo:** `.gitleaks.toml` + pre-commit + job CI; historia
> czysta z sekretów; **telemetrii BRAK**. **CI** rozszerzone (7 self-checków + lint + vitest + gitleaks).
> **Auto-update** (electron-updater, guarded require) + **pakowanie mac/Linux** (dmg/AppImage/deb +
> `build_sidecar.sh` + matryca `release.yml`). **Weryfikacja:** 6 self-checków backendu + `crossplatform_check`
> + `npm run typecheck` — wszystko zielone; wszystkie YAML/TOML zwalidowane.
>
> ⚠️ **Kroki sieciowe do dopięcia przez utrzymującego** (sandbox nie ma dostępu do npm registry):
> (1) `cd desktop && npm install -D eslint typescript-eslint eslint-plugin-react-hooks globals vitest`
> (utrwala devDeps lint/test w locku), (2) `cd desktop && npm install electron-updater` (utrwala zależność
> auto-update), (3) ustaw `owner`/`repo` (publish) + sekret `CLA_SIGNATURES_TOKEN` + kontakt CoC po
> utworzeniu repozytorium GitHub. Szczegóły per-zadanie niżej.

---

## 0. Decyzje przekrojowe
- **Licencja: Apache-2.0 (podjęte)** + **CLA** od pierwszego zewnętrznego PR-a (utrzymuje IP
  przelicencjonowalne pod ewentualne przejęcie). Zgodna z konwencją narzędzi do kodu; grant patentowy.
- **Rebranding: nazwa „Grok" znika** (znak towarowy xAI) — nowa niezależna marka (M15-1b).
- **BYO-key onboarding:** user wnosi własny klucz xAI. **Zero sekretów w repo i logach** —
  `grok_auth.json` gitignored (masz), klucz nigdy nie zwracany przez `/settings` (masz), scrubbed env
  i `upstream_error()` nie leakują (masz). Pilnuj reszty.
- **Telemetria:** tylko opt-in, domyślnie off, jawnie udokumentowana — albo wcale.
- **Cross-platform = neutralność od teraz, buildy później.** Abstrahuj miejsca platformowo-zależne
  (pty, kill, ścieżki) i **nie wprowadzaj nowych zależności Windows-only**. Mac/Linux buildy dopiero
  przy popycie (zdefiniuj próg — patrz pytania).
- **UI po angielsku** — już konwencja repo.

---

## 1. Higiena i wydanie OSS

### ✅ M15-1 [P0] Licencja (Apache-2.0) + CLA + pliki wydania  — S/M  — **DONE**
- **Cel:** repo gotowe do upublicznienia, z IP przelicencjonowalnym.
- **Zakres:** **`LICENSE` = Apache-2.0** + `NOTICE`; **`CLA`** (Contributor License Agreement) wymagane
  od pierwszego zewnętrznego PR-a (np. bot CLA na GitHubie) — warunek konieczny pod ewentualne
  przejęcie/relicencjonowanie. `README` (czym to jest, BYO-key quickstart, zrzuty), `CONTRIBUTING`,
  `CODE_OF_CONDUCT`, `SECURITY.md` (jak zgłaszać; „nigdy nie commituj `grok_auth.json`"). README opiera
  się na istniejącym `CLAUDE.md` dla kontrybutorów.
- **DoD:** repo ma komplet plików; CLA blokuje merge bez podpisu; README prowadzi nowego użytkownika
  od zera do działania z własnym kluczem xAI.
- **Weryfikacja:** świeży clone + kroki z README → aplikacja startuje; PR bez CLA nie przechodzi.
- **Status (2026-06-05): DONE.** Dodane (po angielsku, pod publiczne OSS): [`LICENSE`](../LICENSE)
  (pełny Apache-2.0, copyright „Caelo contributors"), [`NOTICE`](../NOTICE) (atrybucja + nota o
  znaku towarowym/nominatywnym użyciu xAI/Grok + komponenty 3rd-party), [`CLA.md`](../CLA.md)
  (grant copyright+patent + **klauzula relicencjonowania** pod przejęcie; dyskl. „do weryfikacji
  prawnej") + workflow [`cla.yml`](../.github/workflows/cla.yml) (contributor-assistant — blokuje
  merge bez podpisu; URL dokumentu rozwiązuje się po publikacji; wymaga sekretu
  `CLA_SIGNATURES_TOKEN`), [`CONTRIBUTING.md`](../CONTRIBUTING.md) (setup, lista self-checków,
  konwencje, proces PR), [`CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md) (Contributor Covenant 2.1 przez
  odwołanie — wersja odporna na filtr treści), [`SECURITY.md`](../SECURITY.md) (zgłaszanie, BYO-key,
  „nigdy nie commituj `caelo_auth.json`", model bezpieczeństwa, telemetria=brak).
  **README** przepisany na markę Caelo z **BYO-key quickstart** (klucz/OAuth → Settings/.env →
  precedencja). **Uwaga:** placeholder kontaktu CoC i sekret CLA bota do uzupełnienia przy publikacji.

### ✅ M15-1b [P0] Rebranding — usunięcie nazwy „Grok"  — M  — **DONE**
- **Cel:** zdjąć ryzyko znaku towarowego xAI i dać niezależną markę (lepszą też pod przejęcie).
- **Zakres:** nowa nazwa produktu + logo; zamiana w UI (tytuł okna, „Grok Desktop", media captions),
  instalatorze, repo, README; rozważ zmianę nazw wewnętrznych (`grok_core`, `grok_*.json`) — niższe
  ryzyko, ale czystsze przy due diligence. Opis „works with xAI/Grok" = nominatywne użycie (do
  weryfikacji prawnej), NIE w nazwie produktu.
- **DoD:** brak „Grok" w nazwie/UI/marketingu; aplikacja i self-checki działają po rebrandingu.
- **Weryfikacja:** grep po „Grok" w stringach user-facing pusty; testy zielone.
- **Status (2026-06-05): DONE — marka „Caelo", PEŁNY rebrand wewnętrzny.** Pakiet `grok_core` →
  `caelo_core` (git mv, historia zachowana); binarka `grok-core` → `caelo-core`; env/handshake
  `GROK_CORE_*` → `CAELO_CORE_*` (`__CAELO_CORE_READY__`); most renderera `window.grok` →
  `window.caelo` (`exposeInMainWorld('caelo')`); pliki stanu `grok_*.json/db/log` → `caelo_*`;
  `GROK.md` → `CAELO.md` (czyta starą nazwę jako fallback); katalog checkpointów `.grok` → `.caelo`
  (`.grok` zostaje w IGNORE_DIRS); persona agenta „Grok Code" → „Caelo Code"; `APP_NAME` „AI Studio
  Pro" → „Caelo". **Migracja bez utraty danych:** `config._migrate_legacy_data()` (stary katalog +
  pliki grok_* → caelo_*) i `migrateLegacyStorage()` (klucze localStorage `grok.*` → `caelo.*`).
  Jedyny pozostały „Grok" w UI to **„SuperGrok"** (nominatywna nazwa subskrypcji xAI w karcie „xAI
  Account") + komentarze w kodzie. **Weryfikacja:** 5 self-checków backendu OK + `npm run typecheck`
  OK; wszystkie `caelo_*` dane gitignored (brak wycieku `caelo_auth.json`).

### ✅ M15-2 [P0] Zero-sekretów + audyt historii  — S  — **DONE**
- **Cel:** żaden sekret nie trafia do repo ani logów.
- **Zakres:** `.gitignore` obejmuje `grok_auth.json`/`.env`/klucze; skaner sekretów (np. gitleaks) w
  pre-commit; potwierdź brak logowania klucza (masz scrubbed env, `upstream_error`, key-not-returned).
  Jeśli kiedykolwiek sekret trafił do historii — wyczyść historię przed publikacją.
- **DoD:** skaner czysty na całej historii; brak sekretów.
- **Weryfikacja:** gitleaks na pełnej historii przechodzi.
- **Status (2026-06-05): DONE.** `.gitignore` rozszerzony o siatkę `caelo_*` (json/db/log) +
  zachowana siatka `grok_*` (legacy) — potwierdzone `git check-ignore`, że `caelo_auth.json` i
  reszta danych są ignorowane (po migracji nazw nie było wycieku). Dodane: [`.gitleaks.toml`](../.gitleaks.toml)
  (reguły domyślne + allowlist: publiczny PKCE client_id, lockfile'y, pliki danych),
  [`.pre-commit-config.yaml`](../.pre-commit-config.yaml) (gitleaks + detect-private-key + sanity),
  oraz **job „Secret scan (gitleaks)" w CI** (pełna historia, `fetch-depth: 0`).
  **Audyt historii (ręczny, narzędzia offline):** żaden plik `auth.json`/`.env`/`.pem`/`.key`
  nigdy nie dodany; skan treści CAŁEJ historii pod `xai-…`/`sk-…`/`BEGIN … PRIVATE KEY` — pusty.
  Brak logowania klucza (scrubbed env + `upstream_error` + key-not-returned, jak dotąd).

### ✅ M15-3 [P1] Publiczne CI  — M  — **DONE (z jednym krokiem sieciowym do dopięcia)**
- **Cel:** każdy PR przechodzi przez te same bramki co Ty.
- **Zakres:** GitHub Actions: `typecheck` + ESLint + Vitest + self-checki Pythona (`handshake_check`,
  `api_smoke`, `agent_selfcheck` + nowe z M9–M17: `history_check`, `mcp_check`, `genjobs_check`…).
  **Uwaga z `CLAUDE.md`:** devDeps M8 (eslint/vitest) trzeba zacommitować (`npm install -D` aktualizuje
  `package.json`+`package-lock.json`), inaczej `npm ci` w CI padnie.
- **DoD:** PR uruchamia wszystkie kontrole; czerwone przy błędzie.
- **Weryfikacja:** celowo psujący test czerwieni PR.
- **Status (2026-06-05): DONE.** `ci.yml` rozszerzony: **backend** o `crossplatform_check`,
  `mcp_check`, `genjobs_check`, `history_check` (obok handshake/api_smoke/agent_selfcheck — 7 suit);
  **frontend** o `npm run lint` (ESLint react-hooks) i `npm test` (Vitest) obok typecheck; nowy job
  **secrets** (gitleaks). YAML zwalidowany. **Rozwiązanie problemu devDeps bez sieci:** zamiast łamać
  `npm ci` dodaniem eslint/vitest do `package.json` przy nieaktualnym locku, CI **dociąga toolchain
  efemerycznie** (`npm install --no-save --no-package-lock eslint/typescript-eslint/…/vitest`) PO
  `npm ci`, więc lint+test biegną, a `npm ci` zostaje powtarzalny. ⚠️ **Krok sieciowy do dopięcia
  (utrzymujący):** uruchom raz `cd desktop && npm install -D eslint typescript-eslint
  eslint-plugin-react-hooks globals vitest` (aktualizuje `package.json`+`package-lock.json`), potem
  można uprościć CI do samego `npm run lint`/`npm test`. Self-checki backendu i typecheck — zielone
  lokalnie; lint/vitest wymagają sieci (offline tu niedostępne).

### ✅ M15-4 [P1] Telemetria opt-in  — S  — **DONE (brak telemetrii)**
- **Cel:** prywatność domyślnie.
- **Zakres:** jeśli jakakolwiek telemetria — opt-in, jawna, udokumentowana, domyślnie off.
- **DoD:** brak telemetrii bez wyraźnej zgody.
- **Weryfikacja:** świeża instalacja nic nie wysyła.
- **Status (2026-06-05): DONE — telemetrii BRAK.** Grep po `telemetry|analytics|posthog|sentry|
  mixpanel|amplitude|segment|gtag|sendBeacon` w backendzie i rendererze — pusty (jedyne trafienie to
  WEWNĘTRZNA telemetria subagentów: liczniki tur/tokenów, nie phone-home). Jedyne wyjścia sieciowe w
  kodzie to `api.x.ai`/`auth.x.ai` (klucz usera) i `x.com` (X-search, akcja usera); reszta to loopback
  i fixture'y testów. Udokumentowane: README → **„Privacy & telemetry"**, SECURITY.md → **„Telemetry"**
  (jedyny dodatkowy ruch to sprawdzanie wydań z GitHub Releases — M15-8, wyłączalne).

---

## 2. Fundament cross-platform (architektura od teraz)

### ✅ M15-5 [P0] Abstrakcja PTY  — M  — **DONE**
- **Cel:** terminal działa też poza Windows.
- **Zakres:** dziś terminal = `pywinpty` (Windows-only). Wprowadź interfejs PTY: `pywinpty` na Windows,
  stdlib `pty`/`ptyprocess` na Unix. Scrubbed env już nałożony (P0-11) — zachowaj.
- **DoD:** abstrakcja ładuje się na obu; na Windows działa jak dziś; ścieżka Unix zaimplementowana
  (testowana, gdy powstanie build mac/Linux).
- **Weryfikacja/Selfcheck:** selftest interfejsu PTY (oznacz platform-specyficzne jako skip poza danym OS).
- **Status (2026-06-05): DONE.** Nowy moduł [`caelo_core/pty_compat.py`](../caelo_core/pty_compat.py)
  — `open_pty()` zwraca obiekt o API zgodnym z `winpty.PtyProcess`
  (`read/write/setwinsize/isalive/terminate`). Windows: pywinpty **ładowane leniwie** (brak →
  `PtyUnavailable` z instrukcją). Unix: `UnixPtyProcess` na **stdlib** (`pty`+`os`+`termios`+`fcntl`,
  zero nowych zależności) z własną grupą procesów (`start_new_session`). `routes/terminal.py` używa
  `open_pty` (nie zna platformy); scrubbed env zachowany. Selfcheck:
  [`crossplatform_check.py`](../caelo_core/tools/crossplatform_check.py) — interfejs + echo round-trip
  na bieżącym OS (PASS na Windows), Unix-path importuje się czysto (brak top-level `import winpty`).

### ✅ M15-6 [P0] Abstrakcja tree-kill / sygnałów  — S/M  — **DONE**
- **Cel:** ubijanie drzewa procesów działa cross-platform.
- **Zakres:** dziś `run_command` tree-kill = `taskkill /T /F` (Windows). Dodaj POSIX: grupy procesów
  (`start_new_session`/`os.setsid` + `os.killpg` SIGTERM→SIGKILL). Masz już POSIX-aware
  `command_metachars` + `shell=False` poza Windows (P0-10) — domknij kill tym samym wzorcem.
- **DoD:** tree-kill działa na obu; selfcheck na bieżącym OS.
- **Selfcheck:** `agent_selfcheck.py` — wybór ścieżki kill per-OS; brak wywołań Windows-only na POSIX.
- **Status (2026-06-05): DONE.** `tools._tree_kill` (współdzielony przez `run_command`, hooki, MCP,
  worktree): Windows `taskkill /T /F`; **POSIX `killpg` z eskalacją SIGTERM→SIGKILL** (grzecznie,
  potem twardo po 3 s) — wcześniej był od razu SIGKILL. `run_command` na POSIX już nadaje
  `start_new_session` (własna grupa = killpg ubija drzewo). Selfcheck `crossplatform_check.py`:
  inspekcja ścieżek per-OS (taskkill osłonięty `os.name=='nt'`, killpg + SIGTERM<SIGKILL,
  `start_new_session`, brak taskkill poza gałęzią Windows) + **LIVE Stop** ubija realnie działającą
  komendę na bieżącym OS (<10 s). `agent_selfcheck` bez regresji.

### ✅ M15-7 [P1] Audyt założeń Windows-only  — S  — **DONE**
- **Cel:** brak ukrytego długu Windows-only.
- **Zakres:** przegląd separatorów ścieżek, liter dysków, nieosłoniętych importów `pywinpty`,
  `%LOCALAPPDATA%`; `config.DATA_DIR` per-OS (IS_FROZEN → LOCALAPPDATA na Win; Application Support/XDG
  na mac/Linux).
- **DoD:** brak nieosłoniętych wywołań Windows-only; `DATA_DIR` rozwiązuje się per-OS.
- **Weryfikacja:** statyczny sweep + import sidecara pod Pythonem na Unix.
- **Status (2026-06-05): DONE.** Sweep: jedyny import `winpty` jest **leniwy** w `pty_compat`
  (nie na poziomie modułu → sidecar importuje się czysto na Unix); każda gałąź `os.name=='nt'` /
  `sys.platform=='win32'` ma ścieżkę alternatywną (kill, shell, `.cmd/.bat` w hookach/MCP);
  twarde ścieżki z `\`/literami dysków są wyłącznie w **fixture'ach testów** (skaner metaznaków),
  nie w konstruowaniu ścieżek runtime. `config.DATA_DIR` per-OS (Win `%LOCALAPPDATA%` / macOS
  `~/Library/Application Support` / Linux `$XDG_DATA_HOME`) — wydzielone do `_user_data_base()`.
  `requirements.txt` ma marker `pywinpty ; sys_platform=="win32"`; `requirements.lock` jest
  udokumentowanym snapshotem Windows (Unix używa `requirements.txt`). Selfcheck
  `crossplatform_check.py` potwierdza per-OS base + brak top-level importu winpty.

---

## 3. Pakowanie i aktualizacje

### ✅ M15-8 [P1] Auto-update  — S/M  — **DONE (kod gotowy; 1 krok sieciowy + owner/repo)**
- **Cel:** użytkownicy dostają nowe wersje bez ręcznej reinstalacji.
- **Zakres:** `electron-updater` + flow wydań (GitHub Releases jako feed). Najpierw Windows.
- **DoD:** aplikacja wykrywa aktualizację i potrafi się zaktualizować.
- **Weryfikacja:** bump wersji → aplikacja wykrywa update.
- **Status (2026-06-05): DONE.** `main/index.ts` → `initAutoUpdate()`: sprawdza wydania na starcie,
  pobiera w tle i pokazuje dialog „Restart now / Later" (`quitAndInstall`). Działa tylko w buildzie
  (`app.isPackaged`), wyłączalne `CAELO_DISABLE_AUTOUPDATE=1`. **`electron-updater` ładowany przez
  `require` w try/catch** — brak pakietu = graceful no-op (typecheck i `npm ci` zostają zielone bez
  sieci). `electron-builder.yml` → sekcja `publish: github` (generuje `app-update.yml`/`latest.yml`).
  ⚠️ **Do dopięcia (utrzymujący, wymaga sieci):** `cd desktop && npm install electron-updater` (doda do
  `dependencies`+lock, by electron-builder spakował pakiet) oraz ustaw `owner`/`repo` (lub pole
  `repository` w package.json) po utworzeniu repozytorium GitHub. Typecheck zielony.

### ✅ M15-9 [P1] Pakowanie cross-platform (warunkowe)  — M  — **DONE (skonfigurowane; buildy na żądanie)**
- **Cel:** instalatory na docelowe OS.
- **Zakres:** cele `electron-builder`: NSIS (Win — masz) + dmg (mac) + AppImage/deb (Linux); sidecar
  PyInstaller per-OS (matryca CI na runnerach per OS — cross-compile PyInstaller jest trudny).
  Podpisywanie: Authenticode (Win), Developer ID + notaryzacja (mac) — **zweryfikuj aktualne wymogi
  i koszty Apple/Windows** przed wdrożeniem.
- **DoD:** instalatory dla docelowych OS (mac/Linux dopiero przy popycie).
- **Weryfikacja:** podpisany instalator startuje bez blokady SmartScreen/Gatekeeper.
- **Status (2026-06-05): DONE (config + scaffolding; faktyczne buildy mac/Linux na żądanie).**
  `electron-builder.yml` → cele **mac** (`dmg`, x64+arm64, kategoria developer-tools) i **linux**
  (`AppImage` + `deb`, maintainer/synopsis) obok NSIS. Sidecar cross-platform:
  [`build_sidecar.sh`](../build_sidecar.sh) (odpowiednik `.ps1` dla mac/Linux; spec pomija winpty,
  terminal na stdlib `pty`). Skrypty `npm`: `pack:sidecar:unix`, `dist:mac`, `dist:linux`.
  **Matryca CI per-OS:** [`release.yml`](../.github/workflows/release.yml) — tag `v*` → buduje sidecar
  na runnerze danego OS + `electron-builder --publish always` (Win/mac/Linux, `fail-fast:false`).
  **Podpisywanie:** zostawione jako opcjonalne (zakomentowane env: `CSC_LINK`/`CSC_KEY_PASSWORD` dla
  Authenticode, `APPLE_ID`/`APPLE_APP_SPECIFIC_PASSWORD`/`APPLE_TEAM_ID` dla notaryzacji) — decyzja
  „unsigned najpierw + instrukcja obejścia" do potwierdzenia (patrz §5). extraResources i proces
  główny są OS-agnostyczne (`caelo-core` vs `caelo-core.exe`).

---

## 4. Definicja ukończenia M15 (całość)
1. Repo publikowalne: licencja wybrana, README/CONTRIBUTING/SECURITY, BYO-key quickstart; nowy user
   uruchamia z własnym kluczem.
2. Zero sekretów w repo/historii; klucz nigdy nie logowany; telemetria opt-in (lub brak).
3. Publiczne CI uruchamia wszystkie kontrole na PR.
4. Kod platformowo-zależny (pty, kill, ścieżki) zabstrahowany; brak nowego długu Windows-only;
   `DATA_DIR` per-OS.
5. Auto-update działa (Windows); buildy mac/Linux osiągalne, gdy pojawi się popyt.

## 5. Otwarte pytania
- ~~Licencja~~ — **podjęte: Apache-2.0 + CLA.** Do weryfikacji prawnej: znak towarowy nowej nazwy
  **„Caelo"** + dopuszczalny zakres opisu „works with xAI/Grok" (użycie nominatywne — zastosowane w
  NOTICE/README; w UI zostało tylko nominatywne „SuperGrok" w karcie „xAI Account").
- ~~**Dystrybucja sidecara cross-platform**~~ — **podjęte: matryca CI per-OS** (zaimplementowane w
  `release.yml`; cross-compile odrzucony jako niepraktyczny dla PyInstallera).
- **Podpisywanie (DO DECYZJI utrzymującego):** certy kosztują (Apple Developer ~$99/rok; cert
  Windows). Scaffolding gotowy (zakomentowane env w `release.yml`/`electron-builder.yml`). Rekomendacja
  dla OSS: **najpierw unsigned + instrukcja obejścia SmartScreen/Gatekeeper**, podpisywanie gdy pojawi
  się popyt/budżet.
- **Próg na mac/Linux (DO DECYZJI):** config gotowy, ale faktyczne buildy „na żądanie" — zdefiniuj
  wyzwalacz (np. liczba próśb/gwiazdek), by nie utrzymywać certów/runnerów przedwcześnie.
