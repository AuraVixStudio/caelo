# PLAN_M16_SPOLECZNOSC.md — Społeczność / marketplace (rozpis zadań)

> Rozpis milestone'u **M16** z `PLAN_ROZBUDOWY.md` — „gdy rdzeń stabilny". Cel: dystrybucja i
> dzielenie się artefaktami rozszerzalności z M14 (**skille, komendy, konfiguracje serwerów MCP,
> szablony projektów**) — w duchu „Cheap, Accessible, Shareable", przy zerowej infrastrukturze.
>
> **Zakłada gotowe:** M14 (skille/komendy/MCP). Sekcje tematyczne. Tagi: **[P0]** krytyczne,
> **[P1]** ważne, **[P2]** później.
>
> ## ✅ STATUS (2026-06-06): M16 KOMPLETNE — M16-1…M16-7
> Wszystkie zadania zrobione i zweryfikowane. **Backend:** `caelo_core/packages/`
> (`manifest.py` format/walidacja/wersje + `manager.py` `PackageManager`) — pakiet
> `.caelopkg` = ZIP z `manifest.json` + `payload/`, integralność sha256, **import nic nie
> uruchamia** (skille/MCP instalują się WYŁĄCZONE, szablony tylko zapisują pliki, komendy
> to szablony), inspekcja → karta zgody, instalacja za jawnym `consent`. Registry oparte o
> git/GitHub (https-only, cap), eksport, szablony projektów (wbudowane Ren'Py VN + DAZ),
> sprawdzanie aktualizacji/kompatybilności. Trasy `routes/packages.py` (pod `require_token`),
> leniwy `backend.packages`. **Decyzja:** format ZIP (stdlib `zipfile`, zero nowych
> zależności) + zakładka „Marketplace" w module Extensions (nie osobny modul). **Self-checki:**
> `caelo_core/tools/packages_check.py` **47/47 OK** (round-trip, brak-zgody, integralność/tamper,
> Zip-Slip/limity, registry, aktualizacje, szablony), `api_smoke.py` `_unit_packages` (RESULT:
> OK, zero regresji), `agent_selfcheck`/`handshake_check` bez regresji. **Frontend:** Extensions
> → **Marketplace** (Browse/Installed/Import/Templates + karta zgody) + przyciski „Export" w
> panelach Skills/Commands/MCP/Templates; `typecheck` OK; renderowanie 4 sekcji zweryfikowane w
> `preview:web` (bez błędów konsoli). **Społeczność:** `docs/guides/PACKAGES.md`, szablony issue
> (submission + report), `docs/guides/registry.example.json`. Szczegóły per-zadanie niżej.

---

## 0. Decyzje przekrojowe
- **Zależność od M14:** bez skilli/komend/MCP nie ma czym się dzielić. M16 to warstwa dystrybucji nad M14.
- **Zero infrastruktury (etos BYO-key):** registry oparte o **git/GitHub** (manifesty + linki),
  nie hostowana platforma — brak kosztów i kont po Twojej stronie. (Hostowana usługa = lepsze UX,
  ale koszt/utrzymanie — patrz pytania.)
- **Bezpieczeństwo to fundament, nie dodatek.** Pakiet od obcych (zwł. konfiguracja MCP lub komenda z
  akcją) = potencjalnie wykonywalny kod/komendy → **ten sam reżim co M14**: jawne uprawnienia, zgoda,
  sandbox, brak auto-uruchamiania. Marketplace nie może obniżać tej poprzeczki.
- **itch.io-style** udostępnianie pasuje do Twojego tła VN: pojedynczy pobieralny pakiet, który ktoś importuje.
- **UI po angielsku** — konwencja repo.

---

## 1. Format i bezpieczeństwo pakietów

### ✅ M16-1 [P0] Manifest i format pakietu  — M  — **DONE**
- **Cel:** jeden, wersjonowany format dla wszystkiego, co dzielone.
- **Zakres:** format pakietu dla skilli/komend/konfiguracji-MCP/szablonów: manifest (name, version,
  author, type, requires, **declared permissions / tool-scope**, source) + integralność (hash/podpis).
- **DoD:** skill/komenda eksportowane jako samodzielny pakiet z manifestem; importowalne.
- **Selfcheck:** round-trip pakietu (export→import), manifest walidowany, za duży/niepoprawny odrzucony.
- **Status (2026-06-06):** `caelo_core/packages/manifest.py` — `validate_manifest` (typ/id/wersja/
  schemat z przyszłości odrzucone), `compute_integrity` (sha256 payloadu, deterministyczne),
  `parse_version`/`version_compare`/`requirement_satisfied`, `normalize_permissions`/`risk_level`,
  `is_safe_payload_name` (anty Zip-Slip). Format **`.caelopkg` = ZIP**: `manifest.json` na korzeniu +
  `payload/` (typ→zawartość: skill `SKILL.md`+zasoby, command `command.json`, mcp `server.json` bez
  sekretów, template `template.json`+`files/`). `PackageManager.build_package` liczy integralność i
  waliduje. Limity w `config.py` (`MAX_PACKAGE_BYTES`/`_UNPACKED_BYTES`/`_FILES`). `config.PACKAGES_FILE`
  (rejestr) + `TEMPLATES_DIR`. Leniwy `backend.packages`. **Selfcheck:** `packages_check.py`
  (round-trip skill/command/template, walidacja manifestu, integralność).

### ✅ M16-2 [P0] Bezpieczna instalacja pakietów społecznościowych  — M  — **DONE**
- **Cel:** import obcego pakietu nie może być cichym wykonaniem kodu.
- **Zakres:** import pakietu (zwł. konfiguracji MCP / komendy z akcją) za **jawną zgodą**, z pokazaniem
  zadeklarowanych uprawnień / zakresu narzędzi; sandbox; brak auto-run. Reuse bramki M14 + zgody na
  start serwera.
- **DoD:** import pokazuje zadeklarowane uprawnienia i wymaga zgody; nic nie startuje bez zatwierdzenia.
- **Selfcheck:** zaimportowany pakiet nie wykona/nie wystartuje bez wyraźnej akcji usera; zadeklarowany
  zakres egzekwowany.
- **Status (2026-06-06):** `PackageManager.inspect()` = **karta zgody** (manifest + deklarowane
  uprawnienia + `risk` + integralność + kompatybilność + ostrzeżenia, **BEZ instalacji**).
  `install(consent=True)` instaluje TYLKO za jawną zgodą i przy poprawnej integralności (modyfikacja
  payloadu → odmowa). **Nic nie startuje:** skille instalują się WYŁĄCZONE (brak wstrzyknięcia do
  agenta), serwery MCP `enabled=False` (autostart ich nie tknie; start to osobna bramkowana akcja),
  komendy to szablony, szablony piszą pliki dopiero przez „New project". Sandbox: anty Zip-Slip/`..`,
  limity rozmiaru/plików (anty zip-bomba). Trasy `/packages/inspect`+`/install` (consent wymagany).
  Renderer: **ConsentCard** (uprawnienia, ryzyko, ostrzeżenia, checkbox „I trust this" dla high-risk).
  **Selfcheck:** `packages_check.py` (brak-zgody odrzucony, MCP zaimportowany WYŁĄCZONY, tamper/Zip-Slip/
  limity odrzucone), `api_smoke` `_unit_packages` (install bez consent → 400).

---

## 2. Dystrybucja

### ✅ M16-3 [P1] Registry oparte o git/GitHub  — M  — **DONE**
- **Cel:** przeglądaj i instaluj pakiety bez hostowanej usługi.
- **Zakres:** lekki indeks (repo git / temat GitHub) pakietów z manifestami + linkami do źródeł;
  w aplikacji przeglądanie/instalacja z URL-a lub registry.
- **DoD:** przeglądam registry, instaluję pakiet po referencji.
- **Selfcheck:** parsowanie registry, instalacja z URL-a manifestu.
- **Status (2026-06-06):** `PackageManager.parse_registry` (obiekt `{packages:[...]}` lub goła lista;
  pomija niepełne/złe wpisy), `fetch_registry(url)` (https-only + cap, jak `_download_media`; flaguje
  per-wpis `installed`/`has_update`/`compatible`), `fetch_package`/`install_from_url`/`inspect_from_url`.
  Domyślny `config.PACKAGES_REGISTRY_URL` (nadpisywalny w UI). Trasy `/packages/registry`. Renderer:
  **Browse** (pole „Registry URL", lista wpisów z badge installed/update/incompatible, Install → karta
  zgody → instalacja z URL-a). Przykład `docs/guides/registry.example.json`. **Selfcheck:** `packages_check.py`
  (parse pomija niepełne), `api_smoke` (parse in-process bez sieci). Realny fetch sieciowy weryfikuje
  user na swojej maszynie (sandbox blokuje sieć).

### ✅ M16-4 [P1] Eksport / udostępnianie  — S/M  — **DONE**
- **Cel:** łatwo oddać własny pakiet innym.
- **Zakres:** w aplikacji „Export skill/command/template" → pakiet/plik do udostępnienia; instrukcja
  „Publish" (PR do registry / wysłanie pliku). itch.io-style: jeden pobieralny bundle.
- **DoD:** eksportuję pakiet, który ktoś inny importuje.
- **Selfcheck:** eksport produkuje poprawny manifest + payload.
- **Status (2026-06-06):** `PackageManager.export(type, ref)` → `(filename, bytes)` dla skill (folder +
  zasoby; builtin też), command (`command.json`), mcp (`public_config` — **sekrety zdjęte**), template
  (drzewo). Trasa `/packages/export` (zwraca base64). Renderer: przyciski **Share** w panelach Skills/
  Commands/MCP + Marketplace→Templates; `lib/packages.ts` `downloadBase64` pobiera `<id>-<ver>.caelopkg`
  (jeden bundle, itch.io-style). Instrukcja „Publish" w `docs/guides/PACKAGES.md`. **Selfcheck:** `packages_check.py`
  (export→inspect→install round-trip command/template), `api_smoke` `_unit_packages` (export → `.caelopkg`
  + base64, ponowny import działa).

### ✅ M16-5 [P1] Szablony projektów  — S  — **DONE**
- **Cel:** szybki start z gotowych układów.
- **Zakres:** szablony projektów (np. starter VN Ren'Py, pipeline DAZ) jako pakiety; „New project from
  template" (spina się z projektem z M9-B5).
- **DoD:** tworzę projekt z szablonu.
- **Selfcheck:** szablon instancjonuje oczekiwaną strukturę.
- **Status (2026-06-06):** wbudowane szablony `caelo_core/packages/templates/builtin/`
  **`renpy-vn-starter`** (game/script.rpy+options.rpy, README) i **`daz-render-pipeline`** (renders/
  output/scripts/encode.sh, README) — `template.json` (meta) + `files/` (drzewo), pakowane przez
  `caelo_core.spec` (`collect_data_files`). `list_templates` (builtin + user nadpisuje), `instantiate_template`
  (sandbox dest, **nie nadpisuje** istniejących → `skipped`), eksport/import jako `type:template`.
  Trasy `/packages/templates` + `/templates/{id}/new-project` (materializuje → `set_workspace` →
  projekt M9-B5). Renderer: Marketplace→**Templates** (lista, „New project" z `selectFolder`, Export).
  **Selfcheck:** `packages_check.py` (builtin odkryte, instancjonuje, re-instancja pomija istniejące,
  export round-trip), `api_smoke` (`/packages/templates` listuje builtiny).

---

## 3. Współrzędne społeczności

### ✅ M16-6 [P2] Infrastruktura społeczności  — S  — **DONE**
- **Cel:** jasny proces wkładu i zgłoszeń.
- **Zakres:** szablony issue, Discussions, przewodnik wkładu pakietów, lista „featured"/kuracja,
  zgłaszanie złośliwych pakietów.
- **DoD:** kontrybutorzy mogą zgłaszać/raportować pakiety wg jasnego procesu.
- **Weryfikacja:** przykładowe zgłoszenie przechodzi przez proces.
- **Status (2026-06-06):** `.github/ISSUE_TEMPLATE/package-submission.md` (zgłoszenie pakietu do registry
  + checklist bezpieczeństwa), `package-report.md` (raport złośliwego/zepsutego pakietu; kieruje
  security-issues Caelo do SECURITY.md), `config.yml` (linki: przewodnik, Discussions, prywatne
  zgłoszenie luki). **Przewodnik** `docs/guides/PACKAGES.md` (format, model bezpieczeństwa, registry,
  publish, **featured/kuracja**, reporting + „złośliwy pakiet nie wystartuje cicho" via audyt M14-B5).
  Sekcja w `CONTRIBUTING.md`. `docs/guides/registry.example.json`.

### ✅ M16-7 [P2] Wersjonowanie i aktualizacje pakietów  — S/M  — **DONE**
- **Cel:** zainstalowane pakiety da się aktualizować, niekompatybilne — oznaczać.
- **Zakres:** powiadomienia o aktualizacjach zainstalowanych pakietów; kompatybilność (requires wersja
  aplikacji / model).
- **DoD:** zainstalowany pakiet pokazuje dostępną aktualizację; niekompatybilny oznaczony.
- **Selfcheck:** porównanie wersji + sprawdzenie kompatybilności.
- **Status (2026-06-06):** `version_compare`/`requirement_satisfied` (operatory `>=`/`>`/`<=`/`<`/`==`,
  prefiks `1`→`1.x`, `*`; porównanie LICZBOWE, nie leksykalne). `check_updates(registry)` porównuje
  zainstalowane vs registry → `has_update` + `compatible` (requires app vs `resolve_app_version`).
  Trasa `/packages/updates`; inspekcja/registry też flagują kompatybilność i ostrzegają o niezgodnej
  wersji. Renderer: badge **update → vX** + **incompatible** w Browse/Installed, „Check for updates".
  **Selfcheck:** `packages_check.py` (compare numeryczne, has_update wykryte, niekompatybilny flagowany),
  `api_smoke` `_unit_packages` (has_update).

---

## 4. Kolejność i zależności

```
M16-1 (format) ──► M16-2 (bezpieczna instalacja) ──► M16-3 (registry), M16-4 (eksport)
                                                  ──► M16-5 (szablony)
M16-6, M16-7 (ops społeczności) — później
```

- **Fundament:** `M16-1` + `M16-2` — format pakietu i bezpieczna instalacja. Bezpieczeństwo musi wejść
  RAZEM z formatem, nie po.
- **Pierwszy „wow" (dogfooding, zero infra): `M16-1→M16-4→M16-5`** — pakujesz własne skille Ren'Py/DAZ
  i szablon projektu VN, i udostępniasz plik, który ktoś importuje. Sprawdzasz to na własnym dorobku,
  bez stawiania żadnej platformy.
- `M16-3` (registry) gdy jest już kilka pakietów wartych indeksowania.
- `M16-6/M16-7` (ops) dopiero przy realnym ruchu społeczności.

## 5. Definicja ukończenia M16 (całość)  — ✅ SPEŁNIONE (1–5)
1. ✅ Skille/komendy/konfiguracje-MCP/szablony pakowalne z manifestem + integralnością (`.caelopkg`).
2. ✅ Import obcych pakietów jest za zgodą, z zadeklarowanym zakresem, w sandboxie (brak cichego
   wykonania — skille/MCP WYŁĄCZONE, integralność weryfikowana, Zip-Slip/limity).
3. ✅ Registry oparte o git/GitHub pozwala przeglądać/instalować; bez hostowanej infrastruktury/kosztu.
4. ✅ Eksport/udostępnianie + szablony projektów działają (Ren'Py VN + DAZ jako pierwsze).
5. ✅ Istnieje proces zgłaszania/raportowania/aktualizacji pakietów (szablony issue + `docs/guides/PACKAGES.md`).

## 6. Otwarte pytania
- **Registry:** czysto git/GitHub (zero infra, etos BYO-key) vs lekka hostowana usługa (lepsze UX,
  koszt/utrzymanie). Rekomendacja: git-based na start.
- **Zaufanie do pakietów:** jak sygnalizować ryzyko pakietów z akcjami/MCP od obcych? Podpisy autorów?
  Lista „verified"? Minimum: jawne uprawnienia + zgoda + sandbox (z M14).
- **Interop z ekosystemem xAI:** xAI ma wbudowane skille + connectors/BYO-MCP. Twój format skilli
  kompatybilny/mostkowalny z tym, czy świadomie osobny (lokalny)?
- **Moderacja/odpowiedzialność:** OSS marketplace = treści społeczności; proces na złośliwe pakiety
  (zwł. MCP uruchamiające komendy) — kto i jak reaguje?
