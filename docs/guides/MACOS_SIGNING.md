# macOS — podpis Developer ID + notaryzacja na GitHub Actions

Jak zbudować **podpisany i notaryzowany** `.dmg` Caelo (Intel + Apple Silicon) na
GitHub Actions, mając **certyfikat Apple Developer ID Application**, ale **pracując na
Windows bez Maca**. Cała infrastruktura CI jest już gotowa:

- [`.github/workflows/release.yml`](../../.github/workflows/release.yml) — matryca `macos-13` (Intel)
  + `macos-14` (Apple Silicon); podpis/notaryzacja włączają się automatycznie, gdy sekret
  `MAC_CSC_LINK` jest ustawiony (bez niego → czysty **niepodpisany** `.dmg`, build zielony).
- [`desktop/electron-builder.yml`](../../desktop/electron-builder.yml) — sekcja `mac:` (Hardened
  Runtime, `dmg`, `entitlements`).
- [`desktop/build/entitlements.mac.plist`](../../desktop/build/entitlements.mac.plist) — uprawnienia
  wymagane do notaryzacji (JIT/biblioteki sidecara/sieć/mikrofon).

> ⚠️ **Sekrety NIGDY nie idą do repo.** Klucz prywatny i `.p12` generuj **poza** drzewem
> repo (np. `C:\certs\caelo-mac\`) i usuń po wgraniu do GitHub Secrets. `.gitignore` ma
> bezpiecznik (`*.p12`/`*.key`/…), ale najlepszą ochroną jest trzymanie ich poza repo.

Polecenia OpenSSL uruchamiaj w **Git Bash** (masz OpenSSL 1.1.1). Utwórz katalog roboczy:

```bash
mkdir -p /c/certs/caelo-mac && cd /c/certs/caelo-mac
```

---

## Krok 1 — Wygeneruj klucz prywatny + CSR (Windows, OpenSSL)

Certyfikat Apple wymaga **CSR** (Certificate Signing Request). Normalnie robi się go w
Keychain na Macu — bez Maca generujemy go OpenSSL-em. CN/e-mail w CSR są kosmetyczne
(Apple i tak nada podmiot `Developer ID Application: <Twoja firma> (<TeamID>)`).

```bash
openssl genrsa -out developer_id.key 2048

openssl req -new -sha256 -key developer_id.key -out developer_id.csr \
  -subj "/emailAddress=TWOJ@EMAIL.COM/CN=AuraVix Studio/C=PL"
```

Powstają: `developer_id.key` (**klucz prywatny — pilnuj go**) i `developer_id.csr`.

---

## Krok 2 — Wgraj CSR do Apple i pobierz certyfikat

Na stronie **Create a New Certificate**, na której jesteś:

1. Zaznacz **Developer ID Application** (już masz) → **Continue**.
   - Jeśli pyta o „Profile Type / G2 Sub-CA" — zostaw domyślne (**G2**).
2. **Choose File** → wskaż `developer_id.csr` → **Continue**.
3. **Download** → dostajesz `developerID_application.cer` (format DER). Zapisz do
   `C:\certs\caelo-mac\`.

---

## Krok 3 — Złóż `.p12` (cert + klucz + pośredni CA)

`.p12` musi zawierać Twój cert, klucz prywatny **oraz pośredni CA Apple** (inaczej
łańcuch podpisu bywa niekompletny na runnerze).

```bash
cd /c/certs/caelo-mac

# 3a. Twój cert DER → PEM
openssl x509 -inform DER -in developerID_application.cer -out developer_id.pem

# 3b. Pośredni CA Apple „Developer ID – G2" (pobierz raz)
curl -fsSLO https://www.apple.com/certificateauthority/DeveloperIDG2CA.cer
openssl x509 -inform DER -in DeveloperIDG2CA.cer -out DeveloperIDG2CA.pem

# 3c. Złóż .p12 (zapyta o hasło eksportu — ZAPAMIĘTAJ je, to MAC_CSC_KEY_PASSWORD)
openssl pkcs12 -export \
  -inkey developer_id.key \
  -in developer_id.pem \
  -certfile DeveloperIDG2CA.pem \
  -name "Developer ID Application" \
  -out caelo_developer_id.p12
```

Sprawdź, że łańcuch jest w środku (powinny być 2 wpisy `friendlyName`/`subject`):

```bash
openssl pkcs12 -in caelo_developer_id.p12 -info -nokeys -passin pass:TWOJE_HASLO 2>/dev/null | grep subject=
```

---

## Krok 4 — Zakoduj `.p12` do base64 (dla GitHub Secret)

GitHub Secrets to tekst, więc `.p12` (binarny) idzie jako base64 w jednej linii:

```bash
base64 -w0 caelo_developer_id.p12 > caelo_p12_base64.txt
```

(PowerShell alternatywnie: `[Convert]::ToBase64String([IO.File]::ReadAllBytes("caelo_developer_id.p12")) | Set-Content -NoNewline caelo_p12_base64.txt`)

---

## Krok 5 — Zbierz dane do notaryzacji

- **APPLE_TEAM_ID** — 10-znakowy identyfikator zespołu. Apple Developer → **Membership
  details** (albo prawy-górny przełącznik konta, w nawiasie przy nazwie zespołu).
- **APPLE_ID** — e-mail Twojego konta Apple Developer.
- **APPLE_APP_SPECIFIC_PASSWORD** — hasło dla aplikacji (NIE zwykłe hasło Apple):
  [appleid.apple.com](https://appleid.apple.com) → **Sign-In and Security → App-Specific
  Passwords → +** → nazwij np. „caelo-notarize" → skopiuj `xxxx-xxxx-xxxx-xxxx`.

---

## Krok 6 — Dodaj sekrety w GitHub

Repo **AuraVixStudio/caelo** → **Settings → Secrets and variables → Actions → New
repository secret**. Dodaj **pięć** sekretów:

| Nazwa sekretu                  | Wartość                                             |
| ------------------------------ | --------------------------------------------------- |
| `MAC_CSC_LINK`                 | zawartość `caelo_p12_base64.txt` (cała, jedna linia) |
| `MAC_CSC_KEY_PASSWORD`         | hasło eksportu `.p12` z Kroku 3c                    |
| `APPLE_ID`                     | e-mail konta Apple Developer                        |
| `APPLE_APP_SPECIFIC_PASSWORD`  | hasło aplikacji z Kroku 5 (`xxxx-xxxx-xxxx-xxxx`)   |
| `APPLE_TEAM_ID`                | 10-znakowy Team ID                                  |

Nazwy muszą być **dokładnie** takie — `release.yml` mapuje je na zmienne środowiskowe,
które czyta electron-builder.

---

## Krok 7 — Posprzątaj sekrety lokalnie

Po wgraniu do GitHub usuń pliki z kluczem/certem (albo zarchiwizuj **offline**, poza
repo). Klucz `developer_id.key` przyda się tylko, gdy będziesz odnawiać/odtwarzać `.p12`.

```bash
# gdy pewny, że sekrety są w GitHub:
shred -u caelo_p12_base64.txt 2>/dev/null || rm -f caelo_p12_base64.txt
```

---

## Krok 8 — Uruchom build

**Test bez tagu (zalecany pierwszy raz):** GitHub → **Actions → Release → Run workflow**
(gałąź `main`). Zbudują się Linux + oba macOS.

**Wydanie na tag:** `git tag v0.1.2 && git push origin v0.1.2` — workflow ruszy na tagu.
(Windows podpisujesz osobno lokalnie SimplySign — patrz runbook Fazy B; CI buduje tylko
Linux + macOS.)

W logu joba macOS szukaj:
- `signing` / `Developer ID Application: …` — podpis się powiódł,
- `notarization successful` (notarytool) — Apple zaakceptowało pakiet,
- `stapling` — bilet notaryzacji wklejony do `.dmg`.

Gotowe `.dmg` (Intel + Apple Silicon) pobierzesz z **Artifacts** joba (`caelo-unsigned-macos-*`
— nazwa mówi „unsigned", ale przy ustawionych sekretach artefakt jest **podpisany i
notaryzowany**; nazwę zostawiamy neutralną, bo bez sekretów faktycznie jest niepodpisany).

---

## Rozwiązywanie problemów

- **`security: SecKeychainItemImport: … password …`** — złe `MAC_CSC_KEY_PASSWORD`
  (musi być hasło eksportu z Kroku 3c, nie hasło Apple).
- **`The specified item could not be found in the keychain` / brak tożsamości podpisu** —
  `.p12` nie ma klucza prywatnego albo pośredniego CA. Powtórz Krok 3 z `-inkey` i `-certfile`.
- **`Team … is not … Developer ID`** — zły `APPLE_TEAM_ID` albo cert wystawiony na inny zespół.
- **Notaryzacja: `Invalid` z listą problemów** — najczęściej brakujące uprawnienie w
  `entitlements.mac.plist` (sidecar PyInstaller wymaga `allow-jit` /
  `allow-unsigned-executable-memory` / `disable-library-validation` — już są) albo
  binarka bez Hardened Runtime. Pełny raport: link `developer_log` z outputu notarytool.
- **Intelowy runner (`macos-13`) długo w kolejce** — to normalne u Apple; poczekaj lub
  puść ponownie.
