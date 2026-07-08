# macOS — lokalny build + podpis + notaryzacja (na Macu Apple Silicon)

Jak **na fizycznym Macu** (Apple Silicon, np. MacBook Air M4) zbudować, **podpisać
Developer ID** i **notaryzować** instalator `.dmg` Caelo — krok po kroku. To alternatywa
dla ścieżki CI ([`MACOS_SIGNING.md`](MACOS_SIGNING.md)); używaj jej, gdy chcesz zbudować
lokalnie i mieć pełną kontrolę nad artefaktem.

**Wymagania wstępne (założone):**
- Aktywne, płatne członkostwo **Apple Developer Program**.
- Istniejący certyfikat **Developer ID Application** — w tym repo powstał wcześniej na
  Windows (patrz [`MACOS_SIGNING.md`](MACOS_SIGNING.md)) i masz plik `caelo_developer_id.p12`
  + jego hasło eksportu (to `MAC_CSC_KEY_PASSWORD`).
- Dane notaryzacji: `APPLE_ID` (e-mail konta), `APPLE_TEAM_ID` (10 znaków),
  `APPLE_APP_SPECIFIC_PASSWORD` (hasło aplikacji `xxxx-xxxx-xxxx-xxxx`).

> macOS Caelo jest **arm64-only** (Apple Silicon). Intela (x64) nie budujemy — patrz
> [`RELEASING.md`](RELEASING.md) („Gotchas") i `PLAN_OTWARTE.md` (J1-x64).

---

## Krok 0 — Jednorazowa konfiguracja Maca

Wszystkie polecenia w aplikacji **Terminal** (`/Applications/Utilities/Terminal.app`).

### 0a. Narzędzia deweloperskie Apple (codesign, notarytool, stapler)

```bash
xcode-select --install        # instaluje Command Line Tools (codesign, git, clang)
```

Sprawdź, że `notarytool` działa (potrzebne do notaryzacji przez electron-builder):

```bash
xcrun notarytool --help
```

- Jeśli to **działa** → wystarczą Command Line Tools.
- Jeśli **błąd** typu „unable to find utility notarytool" → zainstaluj pełny **Xcode**
  z App Store, potem: `sudo xcode-select -s /Applications/Xcode.app/Contents/Developer`
  i `sudo xcodebuild -license accept`.

### 0b. Homebrew + Node 22 + Python 3.11 + gh

```bash
# Homebrew (jeśli nie masz):
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
# (po instalacji wykonaj polecenia „Next steps" z outputu, by dodać brew do PATH)

brew install node@22 python@3.11 git gh
brew link --overwrite node@22        # upewnij PATH → node 22

node -v        # v22.x  (musi zgadzać się z CI)
python3.11 -V  # Python 3.11.x  (sidecar budujemy na 3.11, jak w CI)
```

### 0c. Klonowanie repo (prywatne)

```bash
gh auth login                        # zaloguj do GitHub (HTTPS, przeglądarką)
cd ~/Developer 2>/dev/null || mkdir -p ~/Developer && cd ~/Developer
gh repo clone AuraVixStudio/caelo
cd caelo
```

---

## Krok 1 — Zainstaluj tożsamość podpisu (certyfikat) w Keychain

electron-builder przy lokalnym budowaniu bierze certyfikat z **login Keychain** (NIE
ustawiamy `CSC_LINK` — to jest tylko dla CI z base64).

1. Przenieś `caelo_developer_id.p12` na Maca (AirDrop / pendrive / bezpieczny transfer).
2. **Dwuklik** na `.p12` → Keychain Access doda go do pęku **login** → podaj **hasło
   eksportu** `.p12` (to `MAC_CSC_KEY_PASSWORD` z Kroku 3c w `MACOS_SIGNING.md`).
3. Sprawdź, że tożsamość podpisu jest widoczna:

```bash
security find-identity -v -p codesigning
```

Powinieneś zobaczyć wpis:
`… "Developer ID Application: AuraVix Studio … (TEAMID)"`

Zapamiętaj **dokładny** ciąg w cudzysłowie — przyda się, gdyby electron-builder nie wybrał
tożsamości automatycznie (Krok 4, `-c.mac.identity=`).

> Nie masz `.p12` pod ręką? Na Macu możesz wygenerować **nowy** cert Developer ID w
> Keychain Access → Certificate Assistant → Request a Certificate…, wgrać CSR w
> Apple Developer i pobrać cert (Apple daje do 5 certów Developer ID Application).
> Ale skoro `.p12` istnieje, najprościej go zaimportować.

---

## Krok 2 — Dane notaryzacji jako zmienne środowiskowe

electron-builder (przez `@electron/notarize` → `notarytool`) czyta je z ENV — dokładnie te
same nazwy co w CI. Ustaw je w bieżącej sesji terminala (podmień wartości na swoje):

```bash
export APPLE_ID="grooverpty@gmail.com"          # e-mail konta Apple Developer
export APPLE_TEAM_ID="XXXXXXXXXX"               # 10-znakowy Team ID
export APPLE_APP_SPECIFIC_PASSWORD="xxxx-xxxx-xxxx-xxxx"
```

> ⚠️ NIE ustawiaj `CSC_LINK` / `CSC_KEY_PASSWORD` — cert bierzemy z Keychain (Krok 1).
> Jeśli je ustawisz, electron-builder zaimportuje `.p12` do tymczasowego pęku (też zadziała,
> ale przy lokalnym budowaniu Keychain jest prostszy).

---

## Krok 3 — Zbuduj sidecar (PyInstaller, natywnie arm64)

Sidecar musi powstać na tym samym OS/arch, co aplikacja (cross-compile jest niepraktyczny).
Utwórz venv na **Pythonie 3.11** (jak CI), potem zbuduj:

```bash
cd caelo_core
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
cd ..
```

(`build_sidecar.sh` sam doinstaluje PyInstaller i wygeneruje `dist/caelo-core/caelo-core`.)

---

## Krok 4 — Zbuduj, podpisz i notaryzuj `.dmg`

```bash
cd desktop
npm ci                       # zależności frontendu (dokładnie z lockfile)

npm run pack:sidecar:unix    # = bash ../build_sidecar.sh  → dist/caelo-core/caelo-core
npm run build                # electron-vite → out/main, out/preload, out/renderer

# Build + podpis Developer ID + notaryzacja. Hardened Runtime i entitlements są już w
# electron-builder.yml; APPLE_* z Kroku 2 uruchamiają notarytool.
npx electron-builder --mac --arm64 -c.mac.notarize=true --publish never
```

Co się dzieje: electron-builder podpisuje `.app` (w tym zagnieżdżony sidecar PyInstaller),
wysyła paczkę do Apple (`notarytool submit --wait`), a po akceptacji **staplerem wkleja
bilet** do `.dmg`. To potrafi potrwać kilka–kilkanaście minut (notaryzacja po stronie Apple).

W logu szukaj: `signing … Developer ID Application: …`, `notarization successful`, `stapling`.

> Gdyby electron-builder nie wybrał tożsamości (kilka certów w Keychain), dołóż jawnie:
> `-c.mac.identity="Developer ID Application: AuraVix Studio (TEAMID)"` (ciąg z Kroku 1).

---

## Krok 5 — Weryfikacja (że naprawdę jest podpisane + notaryzowane)

```bash
# 1) Podpis .app poprawny i „głęboki"
codesign --verify --deep --strict --verbose=2 "dist/mac-arm64/Caelo.app"

# 2) Tożsamość podpisu
codesign -dv --verbose=4 "dist/mac-arm64/Caelo.app" 2>&1 | grep -i authority

# 3) Bilet notaryzacji przyklejony do .dmg
xcrun stapler validate "dist/Caelo-0.1.3-arm64.dmg"

# 4) Gatekeeper zaakceptuje (to widzi użytkownik)
spctl -a -vvv -t install "dist/Caelo-0.1.3-arm64.dmg"
```

Sukces = `stapler validate` mówi „The validate action worked", a `spctl` → `accepted` +
`source=Notarized Developer ID`.

---

## Krok 6 — Co powstało

W `desktop/dist/`:

| Plik | Do czego |
| --- | --- |
| `Caelo-0.1.3-arm64.dmg` | instalator do pobrania przez użytkownika |
| `Caelo-0.1.3-arm64.dmg.blockmap` | delta dla auto-update |
| `latest-mac.yml` | feed auto-update (SHA512 pod ten build) — **musi** trafić do Release'u |

---

## Krok 7 — Publikacja do wydania v0.1.3

Wgraj trzy pliki macOS do Release'u (tag `v0.1.3`) tym samym mechanizmem, co Windows:

```bash
gh release upload v0.1.3 \
  "dist/Caelo-0.1.3-arm64.dmg" \
  "dist/Caelo-0.1.3-arm64.dmg.blockmap" \
  "dist/latest-mac.yml"
```

(Jeśli Release jeszcze nie istnieje, najpierw `gh release create v0.1.3 …` — patrz
[`RELEASING.md`](RELEASING.md).)

Złożenie całego wydania trzech platform (Windows lokalnie, Linux z CI, macOS stąd) opisuje
[`RELEASING.md`](RELEASING.md).

---

## Rozwiązywanie problemów

- **`No identity found` / electron-builder nie widzi certu** — `.p12` nie ma klucza
  prywatnego albo nie jest w pęku *login*. Sprawdź `security find-identity -v -p codesigning`;
  jeśli pusto, ponownie zaimportuj `.p12` (dwuklik) do **login**.
- **`unable to find utility "notarytool"`** — same Command Line Tools nie wystarczają na
  Twojej wersji macOS → zainstaluj pełny Xcode i ustaw `xcode-select -s` (Krok 0a).
- **Notaryzacja `Invalid` z listą problemów** — najczęściej brak uprawnienia w
  `desktop/build/entitlements.mac.plist` (sidecar PyInstaller wymaga `allow-jit` /
  `allow-unsigned-executable-memory` / `disable-library-validation` — już są) albo binarka
  bez Hardened Runtime. Pełny raport: `xcrun notarytool log <submission-id> --apple-id …`.
- **`The specified item could not be found in the keychain` przy notaryzacji** — złe
  `APPLE_APP_SPECIFIC_PASSWORD`/`APPLE_ID`/`APPLE_TEAM_ID` (Krok 2). To hasło **aplikacji**,
  nie zwykłe hasło Apple.
- **Sidecar nie startuje w spakowanej apce** — zbudowany na złym Pythonie/arch. Buduj venv
  Pythonem **3.11 arm64** (`python3.11 -V`) i `npm run pack:sidecar:unix` na tym Macu.
- **`out/main/index.js does not exist`** — pominąłeś `npm run build` przed electron-builderem.
