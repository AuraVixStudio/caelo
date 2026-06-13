# PLAN_FAZA_B_RUNBOOK.md — runbook publikacji (Faza B)

> **Źródło:** [`PLAN_NAPRAWY_4.md`](PLAN_NAPRAWY_4.md) §„Faza B — Publikacja" + [`ANALIZA_PROGRAMU_2026-06-10.md`](ANALIZA_PROGRAMU_2026-06-10.md) §5.
> **Cel:** doprowadzić Caelo do pierwszej publikacji (remote → CI → public → podpisany release z auto-update),
> w kolejności, w której **bezpieczeństwo jest własnością kolejności** (scan-before-public nieprzekraczalny).
> **Data:** 2026-06-12. **Gałąź robocza:** `m15-oss-crossplatform` (nie `main`).
>
> **Decyzje przyjęte (2026-06-12):**
> - **Repo:** `AuraVixStudio/caelo` (organizacja GitHub, nie konto osobiste `grooverpty`).
> - **Code signing:** certyfikat w chmurze **Asseco SimplySign** (klucz nieeksportowalny, autoryzacja przez
>   aplikację mobilną + „SimplySign Desktop" jako wirtualny czytnik kart).

---

## 0. Dwie konsekwencje decyzji (czytaj najpierw)

1. ⚠️ **Repo to ORGANIZACJA → `gitleaks-action` wymaga (darmowej) licencji.**
   `gitleaks/gitleaks-action@v2` jest darmowy tylko dla kont osobistych; dla repozytoriów organizacji
   wymaga klucza `GITLEAKS_LICENSE` (darmowy, z gitleaks.io). Bez niego job „Secret scan" w `ci.yml`
   padnie przy pierwszym biegu CI. Rozwiązanie — patrz **Krok 1**, opcje A/B.

2. ⚠️ **Cert SimplySign jest w chmurze → podpisujemy LOKALNIE, nie w CI.**
   Klucz prywatny jest nieeksportowalny i autoryzowany przez aplikację mobilną, więc nie da się go wstawić
   do GitHub Actions jako `.pfx` (`CSC_LINK` odpada). Podpisane wydania budujemy na maszynie Windows usera,
   gdzie aktywny jest SimplySign Desktop; electron-builder woła `signtool` po cert ze sklepu Windows. CI
   `release.yml` może co najwyżej budować artefakty **niepodpisane**. Szczegóły — **Krok 6**.

**Legenda:** 👤 = robi user (sieć / credentiale / cert — niedostępne z sandboxa) · 🤖 = robi asystent (kod/config).

---

## Status na 2026-06-12

| Krok | Pozycja | Status |
|---|---|---|
| 0 | Prep w kodzie (genjobs cost, files gitignore, repo wiring, bump) | ✅ **ZROBIONE** — commit `664e713` |
| 1 | ROAD-3.6-a — remote + push + 1. CI | ⬜ |
| 2 | ROAD-3.6-d — koszt video/edit\|extend | ✅ (wchłonięte w Krok 0) |
| 3 | ROAD-3.6-e — los `files/` + docs | ✅ (wchłonięte w Krok 0) |
| 4 | ROAD-3.6-b — gitleaks pełnej historii → public | ⬜ |
| 5 | ROAD-3.6-f — dev-deps + pytest | ⬜ |
| 6 | ROAD-TOP2 / ROAD-3.6-c — podpis SimplySign + auto-update + release | 🟡 🤖-część zrobiona (2026-06-13: guard `release.yml` + szablon podpisu + hook sidecara); 👤-reszta ⬜ |

---

## Krok 0 — Przygotowanie w kodzie ✅ ZROBIONE (🤖)

Commit **`664e713`** na `m15-oss-crossplatform`:

- **ROAD-3.6-d** — [`genjobs.py:89`](../../caelo_core/genjobs.py) `estimate_cost` rozlicza wideo wg długości
  **wyjścia**: `edit` zachowuje długość źródła, `extend` = źródło + dodane sekundy (z `source_duration`),
  zamiast bezwarunkowego `duration=6`. Nowe opcjonalne pole `source_duration` w `VideoJobReq`
  ([`routes/genjobs.py:66`](../../caelo_core/routes/genjobs.py)). `estimate_cost` pozostaje czyste
  (bez importu `api_manager`/`state`). **+4 asercje** w `genjobs_check._unit_cost_source_duration`
  (suita `RESULT: OK`).
- **ROAD-3.6-e** — `files/` (lokalny zrzut brand-packa) → [`.gitignore`](../../.gitignore) `/files/`
  (źródłem prawdy zostaje `assets/brand/`); `docs/guides/USER_GUIDE.md` zacommitowany; `docs/README.md`
  już był w repo.
- **Repo wiring** — [`package.json`](../../desktop/package.json) `repository = AuraVixStudio/caelo`
  + bump `0.0.1 → 0.1.0` (zsynchronizowane w `package-lock.json`, by `npm ci` nie protestował);
  [`electron-builder.yml`](../../desktop/electron-builder.yml) `owner: AuraVixStudio` / `repo: caelo`
  odkomentowane (feed auto-update = GitHub Releases).

**Świadome odstępstwo:** `electron-updater` **NIE** trafił do `dependencies` — nie ma go w `package-lock.json`,
a `npm ci` wymaga zgodności lockfile↔package.json (regeneracja wymaga sieci/TLS). Dodanie odłożone do
**Kroku 6** (`npm install electron-updater`). Runtime działa już dziś przez `require`-fallback w
[`main/index.ts:448`](../../desktop/src/main/index.ts) + `npm install electron-updater` w `release.yml`.

**Follow-up (opcjonalny, frontend):** renderer nie wysyła jeszcze `source_duration` (do odczytania z
`HTMLVideoElement.duration` przy stagowaniu źródła wideo). Bez niego koszt edit/extend spada na `duration`
(brak regresji). Do dorobienia osobno, jeśli chcemy pełną ścieżkę szacunku.

---

## Krok 1 — Remote + push + pierwszy bieg CI (👤) · ROAD-3.6-a

> **Cel:** sama obecność remote zdejmuje ryzyko „jedyna kopia na jednym dysku" (SWOT #1). Repo zostaje
> **PRYWATNE** do czasu czystego gitleaks (Krok 4).

Na maszynie usera (jest sieć + `gh`):

```powershell
gh auth login                              # raz, jeśli nie zalogowany
# utwórz PRYWATNE repo w organizacji i wypchnij bieżącą gałąź jednym strzałem:
gh repo create AuraVixStudio/caelo --private --source=. --remote=origin --push
git push -u origin main                     # główna gałąź (wyzwala CI: on.push.branches=[main])
git push origin m15-oss-crossplatform       # gałąź robocza
```

**Gitleaks dla organizacji — wybierz JEDNO przed/przy pierwszym CI:**

- **Opcja A (zalecana):** weź **darmowy** klucz dla organizacji z gitleaks.io i dodaj jako sekret repo:
  ```powershell
  gh secret set GITLEAKS_LICENSE -b "<klucz>" -R AuraVixStudio/caelo
  ```
- **Opcja B:** poproś asystenta o patch [`ci.yml`](../../.github/workflows/ci.yml), który zamienia
  `gitleaks-action` na bezpośrednie wywołanie binarki gitleaks (bez licencji). Wtedy sekret nie jest
  potrzebny, a skan i tak biegnie na pełnej historii (`--log-opts=--all`).

**DoD:** remote istnieje; obie gałęzie wypchnięte; CI na `main` zielone — joby: `secrets` (gitleaks),
`backend` (pytest 3×OS: windows/ubuntu/macos), `frontend` (typecheck + ESLint + Vitest), `e2e` (Playwright).
Środowiskowe zgrzyty pierwszego biegu naprawiamy wspólnie — wklej logi nieudanego joba.

---

## Krok 2 — ROAD-3.6-d ✅ (wchłonięte w Krok 0)

Fix kosztu `video/edit|extend` + test jadą w commicie `664e713`. Nic dodatkowego po stronie usera.

## Krok 3 — ROAD-3.6-e ✅ (wchłonięte w Krok 0)

`files/` zignorowane, `USER_GUIDE.md` zacommitowany, `docs/README.md` już w repo. Nic dodatkowego.

---

## Krok 4 — gitleaks na PEŁNEJ historii PRZED public (👤) · ROAD-3.6-b

> **Nieprzekraczalna bramka „scan-before-public".** Repo zostaje **prywatne**, dopóki wynik nie jest czysty.
> To skan LOKALNY binarką (pełna kontrola), niezależny od joba CI.

```powershell
# instalacja binarki (uwaga TLS — ew. trusted CA / własny bucket scoop):
scoop install gitleaks            # albo: choco install gitleaks
# skan CAŁEJ historii, wszystkich gałęzi, bez wtypisywania sekretów na ekran:
gitleaks detect --source . --config .gitleaks.toml --log-opts="--all" --redact -v
```

- **Wynik czysty (exit 0)** → przełącz repo na publiczne:
  ```powershell
  gh repo edit AuraVixStudio/caelo --visibility public --accept-visibility-change-consequences
  ```
- **Są znaleziska** → **NIE upubliczniaj.** Czyszczenie historii (`git filter-repo`) + **rotacja**
  ujawnionego sekretu, potem skan ponownie. Asystent przygotuje polecenia `filter-repo` pod konkretne
  trafienie (wklej wynik gitleaks z `--redact`, bez surowego sekretu).

Config skanu: [`.gitleaks.toml`](../../.gitleaks.toml) (already-allowlisted: `.env`, `caelo_*.json`,
`caelo_auth.json`, lockfile, sygnatury CLA, publiczny PKCE `client_id` grok-cli — to NIE sekret).

**DoD:** gitleaks czysty na pełnej historii; repo publiczne.

---

## Krok 5 — dev-deps + pytest lokalnie (👤) · ROAD-3.6-f

```powershell
# TLS-interception: dołóż --trusted-host pypi.org --trusted-host files.pythonhosted.org
# lub ustaw $env:PIP_CERT / NODE_EXTRA_CA_CERTS na korpo CA.
caelo_core\.venv\Scripts\pip install -r caelo_core\requirements-dev.txt
caelo_core\.venv\Scripts\python -m pytest caelo_core\tests -v
```

**Uwaga:** krok pytest **jest już wpięty w CI** ([`ci.yml:75-79`](../../.github/workflows/ci.yml) instaluje
`requirements-dev.txt` i odpala `pytest caelo_core/tests`). ROAD-3.6-f sprowadza się więc do
**potwierdzenia zielonego pytest lokalnie** (domyka `0.4` z [`PLAN_WERYFIKACJI_LIVE.md`](PLAN_WERYFIKACJI_LIVE.md)).

**DoD:** lokalny `pytest caelo_core/tests` zielony (= CI też zielone).

---

## Krok 6 — Podpis SimplySign + auto-update + release (👤 + 🤖) · ROAD-TOP2 / ROAD-3.6-c

> **🤖 Zrobione 2026-06-13 (część asystenta — kod/config, nic nie aktywuje się bez certu/sekretów):**
> - **6.4 guard** — [`release.yml`](../../.github/workflows/release.yml): `--publish always` → **`--publish never`**
>   + `upload-artifact` (build waliduje pakowanie cross-OS, ale CI NIE wypchnie niepodpisanego instalatora
>   ani `latest.yml`); `permissions: contents: read`; nazwa joba „Build (UNSIGNED…)".
> - **6.3 pre-stage** — [`electron-builder.yml`](../../desktop/electron-builder.yml): szablon podpisu SimplySign
>   (zakomentowany `certificateSubjectName`/`certificateSha1` + `rfc3161TimeStampServer` + `signingHashAlgorithms`)
>   zastąpił mylącą notkę o `CSC_LINK`. **Aktywacja = odkomentuj i wpisz CN/Thumbprint SWOJEGO certu** (6.2/6.3 niżej).
> - **„exe sidecara" (DoD TOP2)** — [`build_sidecar.ps1`](../../build_sidecar.ps1): bramkowany podpis sidecara
>   (`signtool` po `$env:CAELO_SIGN_THUMBPRINT`, **no-op bez zmiennej**) + dodany **UTF-8 BOM** (PS 5.1 z
>   `powershell -File` na non-UTF8 codepage psuł parsowanie polskich znaków/`—` — teraz czyste).
>
> **👤 Pozostaje:** 6.1 (`npm install electron-updater`), 6.2 (setup SimplySign Desktop), 6.3 (przekaż CN/Thumbprint
> → odkomentuj w `electron-builder.yml`), 6.4 lokalny podpisany `dist:full` + tag, 6.5 DoD. Plus Kroki 1/4/5 (remote,
> gitleaks→public, pytest) PRZED Krokiem 6 (kolejność = własność bezpieczeństwa).

### 6.1 Auto-update (electron-updater) — dokończenie zależności (👤)

```powershell
cd desktop
npm install electron-updater     # aktualizuje package.json + package-lock.json (sync dla npm ci)
```

`electron-updater` jest już wpięty w [`main/index.ts:448`](../../desktop/src/main/index.ts) (ładowany przez
`require` w try/catch — brak pakietu = auto-update wyłączony, nie crash). Feed = GitHub Releases
(`electron-builder.yml` → generuje `app-update.yml` w paczce + `latest.yml` w wydaniu).
Zacommituj zaktualizowane `package.json`+`package-lock.json`.

### 6.2 Środowisko podpisu SimplySign (👤, raz)

1. Zainstaluj **SimplySign Desktop** + narzędzia Certum (proCertum CardManager / CSP).
2. Zaloguj się przez aplikację mobilną SimplySign — certyfikat pojawi się jako **wirtualna karta**
   w sklepie certyfikatów Windows.
3. Odczytaj dane certu:
   ```powershell
   Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Format-List Subject, Thumbprint, NotAfter
   ```
   Przekaż asystentowi **Subject (CN)** albo **Thumbprint**.

### 6.3 Wpięcie certu w electron-builder (🤖)

W [`electron-builder.yml`](../../desktop/electron-builder.yml), sekcja `win:` (asystent doda po otrzymaniu danych):
```yaml
win:
  certificateSubjectName: "<CN z certu>"      # ALBO certificateSha1: "<THUMBPRINT>"
  rfc3161TimeStampServer: http://time.certum.pl
  signingHashAlgorithms: [sha256]
```
To każe electron-builderowi wołać `signtool` po cert ze **sklepu Windows** (wirtualna karta SimplySign),
dzięki czemu `latest.yml` policzy hash **podpisanego** pliku — krytyczne dla poprawnego auto-update.

**Stan 2026-06-13:** powyższy blok jest już **wstawiony jako zakomentowany szablon** w `electron-builder.yml`
(sekcja `win:`). Po Kroku 6.2 odczytaj CN/Thumbprint i **odkomentuj** trzy linie (jedno z `certificateSubjectName`
/ `certificateSha1` + `rfc3161TimeStampServer` + `signingHashAlgorithms`).

**Sidecar (`caelo-core.exe`) — osobny podpis (domyka „exe sidecara" z DoD TOP2):** electron-builder podpisuje
powłokę Electron + instalator NSIS, ale **nie** spakowany sidecar PyInstaller. `build_sidecar.ps1` ma teraz
bramkowany krok podpisu — przed `npm run dist:full` ustaw thumbprint certu:
```powershell
$env:CAELO_SIGN_THUMBPRINT = "<THUMBPRINT certu SimplySign>"   # bez zmiennej krok jest no-op
```
Skrypt wywoła `signtool sign /sha1 <tp> /fd sha256 /tr http://time.certum.pl /td sha256` na `caelo-core.exe`
(wymaga aktywnego SimplySign Desktop, jak podpis instalatora).

### 6.4 Budowa + publikacja podpisanego wydania LOKALNIE (👤)

SimplySign Desktop aktywny; autoryzacja w aplikacji mobilnej nastąpi w trakcie podpisu.

```powershell
# 1) wersja: package.json musi == tag (electron-builder bierze wersję z package.json)
#    (już 0.1.0 z Kroku 0; przyszłe wydania: npm version <x.y.z> --no-git-tag-version)
git tag v0.1.0
git push origin v0.1.0

# 2) build + podpis + publish do GitHub Releases
$env:GH_TOKEN = "<token z uprawnieniem 'repo'>"
cd desktop
npm run dist:full        # pack:sidecar (PyInstaller) + build (frontend) + electron-builder --win
npx --no-install electron-builder --win --publish always
```

> CI `release.yml` na runnerze GitHuba zbuduje wersję **niepodpisaną** (cert chmurowy tam niedostępny).
> Dlatego **podpisane** wydania robisz lokalnie powyżej. Asystent może dodać do `release.yml`
> guard/komentarz, żeby nie publikował niepodpisanych artefaktów przez przypadek.

### 6.5 DoD Kroku 6

- W GitHub Releases jest **podpisany** instalator `Caelo-Setup-0.1.0.exe` + `latest.yml`.
- Instalacja starszej wersji → klient oferuje aktualizację (electron-updater czyta `latest.yml`).
- SmartScreen: nie ostrzega (cert EV) lub buduje reputację z pobraniami (cert OV/standard) —
  zależnie od typu posiadanego certu SimplySign.

---

## Skrót kolejności

| # | Krok | Kto | Bramka (DoD) |
|---|------|-----|--------------|
| 0 | Prep w kodzie | 🤖 ✅ | suity zielone (commit `664e713`) |
| 1 | Remote + push + 1. CI (+ gitleaks org-license) | 👤 | CI zielone |
| 4 | gitleaks pełnej historii → **public** | 👤 | wynik czysty, repo public |
| 5 | pip dev-deps + pytest lokalnie | 👤 | pytest zielony |
| 6 | electron-updater + podpis SimplySign + tag + release | 👤+🤖 | podpisany release + auto-update |

(Kroki 2 i 3 wchłonięte przez Krok 0.)

---

## Po Fazie B

Dalej wg [`PLAN_NAPRAWY_4.md`](PLAN_NAPRAWY_4.md): **Faza C** (weryfikacja LIVE D/F/G/H/I/J/K),
potem **Faza G** TOP-10 (TOP2 = auto-update/signing domknięty tu w Fazie B; reszta od pozycji `S`).

---

*Runbook pochodny od PLAN_NAPRAWY_4.md §„Faza B". Pozycje `⬜` = do zrobienia, `✅` = zrobione.
Aktualizować status w tabeli po każdym kroku.*
