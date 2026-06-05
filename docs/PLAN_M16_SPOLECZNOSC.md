# PLAN_M16_SPOLECZNOSC.md — Społeczność / marketplace (rozpis zadań)

> Rozpis milestone'u **M16** z `PLAN_ROZBUDOWY.md` — „gdy rdzeń stabilny". Cel: dystrybucja i
> dzielenie się artefaktami rozszerzalności z M14 (**skille, komendy, konfiguracje serwerów MCP,
> szablony projektów**) — w duchu „Cheap, Accessible, Shareable", przy zerowej infrastrukturze.
>
> **Zakłada gotowe:** M14 (skille/komendy/MCP). Sekcje tematyczne. Tagi: **[P0]** krytyczne,
> **[P1]** ważne, **[P2]** później.

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

### M16-1 [P0] Manifest i format pakietu  — M
- **Cel:** jeden, wersjonowany format dla wszystkiego, co dzielone.
- **Zakres:** format pakietu dla skilli/komend/konfiguracji-MCP/szablonów: manifest (name, version,
  author, type, requires, **declared permissions / tool-scope**, source) + integralność (hash/podpis).
- **DoD:** skill/komenda eksportowane jako samodzielny pakiet z manifestem; importowalne.
- **Selfcheck:** round-trip pakietu (export→import), manifest walidowany, za duży/niepoprawny odrzucony.

### M16-2 [P0] Bezpieczna instalacja pakietów społecznościowych  — M
- **Cel:** import obcego pakietu nie może być cichym wykonaniem kodu.
- **Zakres:** import pakietu (zwł. konfiguracji MCP / komendy z akcją) za **jawną zgodą**, z pokazaniem
  zadeklarowanych uprawnień / zakresu narzędzi; sandbox; brak auto-run. Reuse bramki M14 + zgody na
  start serwera.
- **DoD:** import pokazuje zadeklarowane uprawnienia i wymaga zgody; nic nie startuje bez zatwierdzenia.
- **Selfcheck:** zaimportowany pakiet nie wykona/nie wystartuje bez wyraźnej akcji usera; zadeklarowany
  zakres egzekwowany.

---

## 2. Dystrybucja

### M16-3 [P1] Registry oparte o git/GitHub  — M
- **Cel:** przeglądaj i instaluj pakiety bez hostowanej usługi.
- **Zakres:** lekki indeks (repo git / temat GitHub) pakietów z manifestami + linkami do źródeł;
  w aplikacji przeglądanie/instalacja z URL-a lub registry.
- **DoD:** przeglądam registry, instaluję pakiet po referencji.
- **Selfcheck:** parsowanie registry, instalacja z URL-a manifestu.

### M16-4 [P1] Eksport / udostępnianie  — S/M
- **Cel:** łatwo oddać własny pakiet innym.
- **Zakres:** w aplikacji „Export skill/command/template" → pakiet/plik do udostępnienia; instrukcja
  „Publish" (PR do registry / wysłanie pliku). itch.io-style: jeden pobieralny bundle.
- **DoD:** eksportuję pakiet, który ktoś inny importuje.
- **Selfcheck:** eksport produkuje poprawny manifest + payload.

### M16-5 [P1] Szablony projektów  — S
- **Cel:** szybki start z gotowych układów.
- **Zakres:** szablony projektów (np. starter VN Ren'Py, pipeline DAZ) jako pakiety; „New project from
  template" (spina się z projektem z M9-B5).
- **DoD:** tworzę projekt z szablonu.
- **Selfcheck:** szablon instancjonuje oczekiwaną strukturę.

---

## 3. Współrzędne społeczności

### M16-6 [P2] Infrastruktura społeczności  — S
- **Cel:** jasny proces wkładu i zgłoszeń.
- **Zakres:** szablony issue, Discussions, przewodnik wkładu pakietów, lista „featured"/kuracja,
  zgłaszanie złośliwych pakietów.
- **DoD:** kontrybutorzy mogą zgłaszać/raportować pakiety wg jasnego procesu.
- **Weryfikacja:** przykładowe zgłoszenie przechodzi przez proces.

### M16-7 [P2] Wersjonowanie i aktualizacje pakietów  — S/M
- **Cel:** zainstalowane pakiety da się aktualizować, niekompatybilne — oznaczać.
- **Zakres:** powiadomienia o aktualizacjach zainstalowanych pakietów; kompatybilność (requires wersja
  aplikacji / model).
- **DoD:** zainstalowany pakiet pokazuje dostępną aktualizację; niekompatybilny oznaczony.
- **Selfcheck:** porównanie wersji + sprawdzenie kompatybilności.

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

## 5. Definicja ukończenia M16 (całość)
1. Skille/komendy/konfiguracje-MCP/szablony pakowalne z manifestem + integralnością.
2. Import obcych pakietów jest za zgodą, z zadeklarowanym zakresem, w sandboxie (brak cichego wykonania).
3. Registry oparte o git/GitHub pozwala przeglądać/instalować; bez hostowanej infrastruktury/kosztu.
4. Eksport/udostępnianie + szablony projektów działają (Ren'Py/DAZ jako pierwsze).
5. Istnieje proces zgłaszania/raportowania/aktualizacji pakietów.

## 6. Otwarte pytania
- **Registry:** czysto git/GitHub (zero infra, etos BYO-key) vs lekka hostowana usługa (lepsze UX,
  koszt/utrzymanie). Rekomendacja: git-based na start.
- **Zaufanie do pakietów:** jak sygnalizować ryzyko pakietów z akcjami/MCP od obcych? Podpisy autorów?
  Lista „verified"? Minimum: jawne uprawnienia + zgoda + sandbox (z M14).
- **Interop z ekosystemem xAI:** xAI ma wbudowane skille + connectors/BYO-MCP. Twój format skilli
  kompatybilny/mostkowalny z tym, czy świadomie osobny (lokalny)?
- **Moderacja/odpowiedzialność:** OSS marketplace = treści społeczności; proces na złośliwe pakiety
  (zwł. MCP uruchamiające komendy) — kto i jak reaguje?
