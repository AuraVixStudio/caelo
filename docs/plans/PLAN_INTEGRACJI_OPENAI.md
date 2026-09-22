# Caelo 2.0 — plan integracji OpenAI jako trzeciego dostawcy

**Data analizy:** 2026-08-31  
**Status:** Chat, Code/Agent i Images zweryfikowane na żywo 2026-09-01; koszty obrazów i kontrakt błędów zakończone; instalator pozostaje odroczony  
**Zakres pierwszego wydania:** Chat + Code/Agent + Image  
**Poza zakresem pierwszego wydania:** wideo OpenAI, Realtime/Voice i logowanie kontem konsumenckim ChatGPT

---

## 1. Cel i nazewnictwo

Celem jest dodanie `openai` jako trzeciego równorzędnego dostawcy obok `xai` i
`google`, bez tworzenia osobnej aplikacji ani osobnych zakładek. Dostawca ma być
dostępny w istniejących modułach:

1. **Chat** — rozmowa, streaming, załączniki, reasoning, użycie tokenów i opcjonalne
   wyszukiwanie w sieci.
2. **Code/Agent** — lokalne narzędzia Caelo, permission gate, tryb planu, checkpointy,
   undo, sesje i subagenty.

W interfejsie nazwa dostawcy brzmi **OpenAI**, a modele są opisane jako modele GPT.
Określenie „modele ChatGPT” jest zrozumiałe użytkowo, ale integracja techniczna nie
korzysta z aplikacji ani subskrypcji ChatGPT. Caelo łączy się z **OpenAI API** przy
użyciu klucza API i rozliczenia projektu API.

---

## 2. Ustalenia wynikające z dokumentacji OpenAI

1. Podstawowym interfejsem będzie **Responses API** (`POST /v1/responses`). Obsługuje
   tekst, obrazy, streaming, reasoning, narzędzia wbudowane i function calling:
   [Responses API reference](https://developers.openai.com/api/reference/typescript/resources/beta/subresources/responses/methods/create).
2. Integracja użyje klucza API przesyłanego wyłącznie z backendu. Klucz nie trafi do
   renderera, logów, bazy rozmów ani plików konfiguracyjnych w postaci jawnej.
3. Na dzień analizy katalog OpenAI wskazuje rodzinę GPT-5.6 jako bieżący zestaw modeli:
   `gpt-5.6-sol`, `gpt-5.6-terra` i `gpt-5.6-luna`. Jest to jednak informacja zmienna,
   dlatego registry Caelo będzie łączyć testowaną listę bazową z wynikiem `/v1/models`,
   zamiast zakładać, że lista pozostanie stała:
   [katalog modeli OpenAI](https://developers.openai.com/api/docs/models).
4. W pierwszym wydaniu każde żądanie będzie miało `store: false`. Caelo zachowa
   historię lokalnie i wyśle potrzebny kontekst w następnym żądaniu. Nie używamy
   jeszcze Conversations API. Dokumentacja OpenAI mówi, że dane API nie są używane
   do trenowania modeli bez zgody, ale domyślne logi monitorowania nadużyć mogą być
   przechowywane do 30 dni; UI i dokumentacja Caelo muszą przedstawiać to uczciwie:
   [OpenAI — Your data](https://developers.openai.com/api/docs/guides/your-data).
5. Nie dokładamy oficjalnego SDK do sidecara. Obecny backend używa `requests`, a
   `responses_client.py` już parsuje strumień SSE o kształcie Responses API. Surowy
   REST ograniczy rozmiar PyInstallera i pozwoli współdzielić przetestowany transport.

---

## 3. Stan obecny i miejsca integracji

| Obszar | Stan obecny | Wymagana zmiana |
|---|---|---|
| Abstrakcje providerów | `ChatProvider`, neutralne wyniki i modele są gotowe | dodać adapter OpenAI, nie omijać abstrakcji |
| Registry | dostawcy `xai`, `google`, `mock` | dodać `openai` i katalog modeli GPT |
| Chat route | jawnie dopuszcza tylko `xai` i `google`; dwie osobne ścieżki | wprowadzić dispatch per provider |
| Responses transport | parser SSE istnieje, lecz jest nazwany i konfigurowany pod xAI | wydzielić neutralny transport, zachowując zgodność xAI |
| Agent | neutralny `ToolCall`/`AssistantTurn`, lecz runner rozgałęzia tylko xAI/Google | dodać adapter OpenAI i trzeci dispatch |
| Sekrety | schema v1: `xai_api_key`, `google_api_key`, OAuth xAI | schema v2 z `openai_api_key` i migracją v1 → v2 |
| Settings | panele xAI → Google → ogólne | dodać pełny panel OpenAI przed ustawieniami ogólnymi |
| Frontend Chat/Code | typy providerów są unią `'xai' | 'google'` | rozszerzyć o `'openai'`, model z registry |
| Koszt | pełniej obsłużone media, brak jednolitego kosztu tokenów | liczyć koszt z `usage`, wersjonowany cennik |
| Testy | parytet xAI/Google dla agenta | rozszerzyć macierz o OpenAI |

### Potwierdzony dług techniczny do usunięcia przed integracją

`Backend._resolve_auth()` w `caelo_core/state.py` nadal odczytuje `api_key` ze starego
pliku ustawień, chociaż `_stored_key()` poprawnie pobiera go z pamięciowego sejfu.
Faza 0 musi naprawić tę ścieżkę i dodać test regresji. W przeciwnym razie trzeci
dostawca utrwaliłby dwa konkurencyjne wzorce obsługi sekretów.

---

## 4. Architektura docelowa

```text
Renderer (Chat / Code / Settings)
          │ provider=openai, model=...
          ▼
FastAPI routes ── Provider dispatcher ── ChatProvider / Agent LLM adapter
                                            │
                                    shared Responses transport
                                      │                 │
                                  xAI policy       OpenAI policy
                                      │                 │
                                api.x.ai/v1     api.openai.com/v1
```

Transport odpowiada wyłącznie za HTTP, SSE, anulowanie i normalizację błędów.
Adapter dostawcy odpowiada za adres bazowy, auth, możliwości modelu, dozwolone
narzędzia i mapowanie odpowiedzi. Narzędzia specyficzne dla xAI, np. wyszukiwanie X,
nie mogą przeniknąć do payloadów OpenAI.

### Nowe moduły

```text
caelo_core/providers/openai/
├── __init__.py
├── client.py          # auth, REST, timeout, retry headers, test connection
├── chat.py            # ChatProvider i mapowanie wejść/wyjść
└── tools.py           # Responses function calls ↔ neutralny kontrakt agenta

caelo_core/models/openai_models.py
```

Wspólny parser Responses należy wydzielić z `caelo_core/responses_client.py` do
neutralnego modułu, np. `caelo_core/providers/responses_transport.py`. Istniejący
adapter xAI pozostaje warstwą zgodności — refaktor nie może zmienić jego zachowania.

---

## 5. Decyzje implementacyjne

### D1 — uwierzytelnianie

- MVP: klucz OpenAI API zapisany przez Electron `safeStorage`.
- Snapshot sekretów przechodzi z wersji 1 do 2 i otrzymuje opcjonalne
  `openai_api_key`.
- Migracja jest wstecznie zgodna: stary sejf otwiera się bez klucza OpenAI.
- Sidecar otrzymuje sekret wyłącznie przez istniejący uwierzytelniony kanał pamięciowy.
- Opcjonalny fallback deweloperski: `OPENAI_API_KEY`; nie jest zapisywany przez UI.
- Przycisk „Test connection” wykonuje tani, niegenerujący treści test uwierzytelnienia
  i zwraca status **OpenAI**, nie ogólny status aplikacji.
- Nie kopiujemy cookies, sesji ani tokenów z aplikacji ChatGPT.

### D2 — modele i capabilities

- `ProviderDescriptor(id='openai', label='OpenAI', modalities=['chat'],
  auth_modes=['api_key'])` w MVP.
- Startowa, testowana lista: `gpt-5.6-terra` jako domyślny Chat,
  `gpt-5.6-sol` jako domyślny Code/Agent oraz `gpt-5.6-luna` jako wariant ekonomiczny.
- Lista z `/v1/models` jest filtrowana do modeli zgodnych z Responses API i scalana z
  lokalnym registry capabilities. Sam fakt zwrócenia ID przez `/v1/models` nie oznacza,
  że UI może zgadywać jego obsługę narzędzi lub parametrów.
- Gdy discovery nie działa, aplikacja korzysta z ostatniego cache albo z testowanej
  listy bazowej.
- `reasoning_effort`, `temperature`, obrazy wejściowe i narzędzia są pokazywane tylko
  wtedy, gdy capability wybranego modelu je dopuszcza.

### D3 — czat i stan rozmowy

- Stream: obsługa co najmniej `response.output_text.delta`, zdarzeń narzędzi,
  `response.completed`, błędów i końca przerwanego połączenia.
- Każde żądanie: `store: false`.
- Historia jest źródłem lokalnym; nie zapisujemy zdalnego `conversation_id` w MVP.
- Załączniki obrazowe mapujemy do `input_image`; dokumenty przechodzą przez obecną
  warstwę załączników, z walidacją typów i limitów przed siecią.
- Cytowania i `usage` trafiają do istniejącego neutralnego formatu `ChatMessage`.
- Stop/anulowanie zamyka aktywny stream i zawsze sprząta stan UI `busy`.
- Retry po zerwanym streamie nie może podwoić lokalnej wiadomości użytkownika.

### D4 — wyszukiwanie i narzędzia czatu

- W MVP OpenAI może użyć natywnego `web_search`, gdy model i konto je obsługują.
- Źródła `x` i `news` specyficzne dla xAI są wyłączone dla OpenAI w UI.
- Tryb `auto/on/off` pozostaje wspólny, ale adapter buduje payload właściwy dla
  dostawcy.
- Koszt narzędzia i cytowania są prezentowane na podstawie odpowiedzi API, nie
  heurystyki rendererowej.

### D5 — Code/Agent

- `providers/openai/tools.py` mapuje `function_call` na neutralny `ToolCall`, zachowując
  `call_id`, nazwę i argumenty JSON.
- Wynik lokalnego narzędzia wraca jako odpowiedź przypisana do tego samego `call_id`.
- Równoległe wywołania nie mogą zgubić kolejności ani wyników.
- Approval gate, sandbox, hooki, checkpointy, undo, MCP, skills i subagenty pozostają
  po stronie Caelo i mają identyczne reguły dla wszystkich dostawców.
- Runner nie może używać konstrukcji „Google, w przeciwnym razie xAI”. Wybór adaptera
  odbywa się przez mapę/registry; nieznany provider kończy się jawnym błędem.

### D6 — koszty i prywatność

- Zapisujemy rzeczywiste liczniki wejścia, wyjścia, cache i reasoning zwrócone w
  `usage`, o ile dany model je udostępnia.
- Cennik jest wersjonowany i oznaczony datą aktualizacji; nie wpisujemy ceny w kod UI.
- Nieznany model pokazuje tokeny i „koszt niedostępny”, nigdy `$0.00`.
- Settings/README/SECURITY wyjaśniają, że local-first dotyczy historii i plików Caelo,
  a treść wybranych żądań jest wysyłana do wybranego dostawcy.

---

## 6. Plan realizacji

### Faza 0 — przygotowanie i zabezpieczenie architektury

1. Naprawić `_resolve_auth()` tak, aby czytał sekret xAI przez `_stored_key()`.
2. Dodać test, że żaden provider nie czyta klucza z niesekretnego JSON-u ustawień.
3. Wydzielić neutralny transport/parsing Responses API bez zmiany zachowania xAI.
4. Zastąpić dwuwariantowe `if/else` mapą adapterów w Chat i Agent runnerze.
5. Dodać wspólny typ identyfikatora providera w Pythonie i TypeScript, aby uniknąć
   rozproszonych unii tekstowych.

**Brama akceptacyjna:** pełny obecny zestaw testów xAI i Google przechodzi bez zmian;
smoke Chat i Code xAI działa; w repo nie ma nowego sekretu ani logu payloadu.

**Status: ZAKOŃCZONA 2026-08-31.**

- `_resolve_auth()` czyta klucz xAI z pamięciowego `RuntimeSecrets`, a test regresji
  potwierdza, że historyczne pole `api_key` z JSON-u nie jest używane.
- Neutralny `providers/responses_transport.py` przejął HTTP, parser SSE, załączniki i
  pętlę function callingu. `responses_client.py` jest teraz adapterem polityki xAI.
- Chat, Agent runner i `Backend.get_provider()` używają jawnych map adapterów zamiast
  dwudostawczego fallbacku.
- Python i renderer mają wspólne katalogi aktywnych identyfikatorów; selektory Chat i
  Code generują opcje z jednego źródła TypeScript.
- Testy faz 1–7: **74 PASS**; frontend: **333 PASS**, lint i typecheck: **PASS**;
  pełny `api_smoke`: **RESULT OK**.
- Niezależny, istniejący self-check wieloplatformowy nadal przekracza na tym hoście
  limit 10 s przy teście szybkości zatrzymania procesu, choć samo zatrzymanie przechodzi.
  Nie jest to regresja warstwy providerów i pozostaje jawnie odnotowane.

### Faza 1 — sekret, ustawienia i registry OpenAI

1. Migracja `SecretSnapshot` v1 → v2 z `openai_api_key` w:
   `desktop/src/main/secrets.ts`, `desktop/src/main/index.ts`,
   `caelo_core/runtime_secrets.py` i trasach settings/secrets.
2. Panel **OpenAI** po panelach xAI i Google, a przed ustawieniami ogólnymi:
   zapisz, usuń, testuj klucz; pokaż faktyczne źródło (`vault`, `env`, `none`).
3. Dodać `openai_models.py`, descriptor providera i capabilities do registry.
4. Dodać discovery `/v1/models`, cache i bezpieczny fallback.
5. Rozszerzyć typy oraz selektory Chat i Code o `openai`.

**Brama akceptacyjna:** restart aplikacji zachowuje zaszyfrowany klucz; renderer nigdy
go nie otrzymuje; OpenAI i jego modele pojawiają się w Chat/Code; odłączenie klucza
nie zmienia statusu xAI/Google.

**Status: ZAKOŃCZONA 2026-08-31 (testy bez sieci).**

- Sejf v2 migruje snapshot v1 i przechowuje `openai_api_key` przez `safeStorage`.
- Settings pokazuje źródło `vault`/`env`/`none`, obsługuje zapis, usunięcie i test OpenAI.
- Registry zawiera testowane modele GPT-5.6 oraz kontrolowane discovery `/v1/models` z cache.

### Faza 2 — OpenAI Chat

1. Zaimplementować `OpenAIClient` i `OpenAIChatProvider` na `/v1/responses`.
2. Streaming tekstu, UTF-8, użycie tokenów, reasoning, anulowanie i błędy.
3. Obsłużyć historię lokalną z `store: false` oraz załączniki obrazowe/dokumentowe.
4. Dodać opcjonalny web search i cytowania zgodnie z capabilities.
5. Utrwalać provider/model przy rozmowie i poprawnie odtwarzać je po restarcie.

**Brama akceptacyjna:** nowy i wznowiony czat działają; polskie znaki nie są
uszkadzane; Stop natychmiast odblokowuje UI; zmiana zakładki nie resetuje modelu;
w payloadzie każdego testu znajduje się `store: false`.

**Status: ZAKOŃCZONA 2026-08-31 (testy kontraktowe bez sieci).**

- OpenAI Chat używa `/v1/responses`, strumieniuje UTF-8, zapisuje usage/cytowania i
  wymusza `store: false`; UI zapamiętuje dostawcę i model per rozmowa.
- Web search jest dostępny bez przenoszenia xAI-owego źródła X do payloadu OpenAI.

### Faza 3 — OpenAI Code/Agent

1. Dodać adapter function calling dla Responses API.
2. Włączyć OpenAI do runnera, sesji, historii, wznawiania i licznika kontekstu.
3. Przeprowadzić tę samą sekwencję testową na xAI, Google i OpenAI:
   odczyt pliku, edycja po zatwierdzeniu, komenda odrzucona, plan → approve & run,
   checkpoint → undo, przerwanie tury i równoległe narzędzia.
4. Zweryfikować MCP, skills, slash commands i subagenta z osobnym worktree.

**Brama akceptacyjna:** sekwencja zdarzeń i reguły uprawnień są równoważne dla trzech
dostawców; żadne narzędzie zmieniające stan nie uruchamia się bez właściwej zgody.

**Status: ZAKOŃCZONA 2026-08-31 (macierz bezpieczeństwa bez sieci).**

- Adapter mapuje function calls/results i zachowuje równoległe `call_id` oraz zaszyfrowany
  stan reasoning potrzebny przy lokalnej historii z `store: false`.
- Macierz approval/checkpoint/loop guard/stop/env scrubbing obejmuje xAI, Google i OpenAI.

### Faza 4 — koszty, błędy, prywatność i wydajność

1. Normalizacja `401`, `403`, `404/model_not_found`, `429`, limitu kontekstu,
   błędnego tool call, timeoutu i zerwanego SSE.
2. Retry wyłącznie dla błędów przejściowych; respektowanie `Retry-After`; brak retry
   po błędzie auth, walidacji lub anulowaniu.
3. Wersjonowany cennik i koszt rozmowy/agenta z rzeczywistego `usage`.
4. Aktualizacja Settings, Diagnostics, README, PRIVACY/SECURITY oraz komunikatów UI.
5. Profilowanie długich rozmów i wielu tool calli; brak blokowania renderera.

**Brama akceptacyjna:** błędy są przypisane do OpenAI i mają działanie naprawcze;
nieznany koszt nie jest zerem; dokumentacja nie obiecuje braku retencji po stronie API.

**Status: ZAKOŃCZONA 2026-08-31 (implementacja i testy bez sieci).**

- Wspólna normalizacja błędów przypisuje awarie do właściwego dostawcy; nieznany provider
  lub model kończy się jawnym błędem zamiast fallbacku do xAI.
- Koszt jest liczony z `usage` według wersjonowanego snapshotu cennika; nieznany model
  zwraca brak kosztu, a dokumentacja opisuje `store: false` i możliwą retencję operacyjną.
- Backend: 14 testów faz OpenAI PASS. Renderer: 24 testy celowane, typecheck i lint PASS.
- 2026-09-01: Images API otrzymało estymację kosztu przed wysłaniem i koszt rzeczywisty
  z `usage` po odpowiedzi. Kontrakt błędów obejmuje `401`, `403`, `404/model_not_found`,
  `429` rate limit/quota, safety/moderation oraz timeout bez ujawniania body dostawcy.
- Test rzeczywistego endpointu potwierdził `401 invalid_api_key` oraz przerwanie żądania
  po timeoutcie. Wymuszanie prawdziwego `429` przez zalewanie API jest celowo pominięte;
  oba warianty `429` są weryfikowane deterministycznym testem odpowiedzi HTTP.

### Faza 5 — test na żywo i wydanie

1. Live test jest ręcznie włączany przez `OPENAI_API_KEY`; automatyczne testy nie
   wykonują płatnych żądań domyślnie.
2. Ograniczyć live smoke do krótkiego promptu, małego budżetu wyjścia i jednego
   bezpiecznego narzędzia tylko do odczytu.
3. Zbudować sidecar PyInstaller i instalator Electron; zweryfikować hidden imports,
   rozmiar paczki, start po czystej instalacji oraz migrację sejfu.
4. Test akceptacyjny Windows: ustawienia → Chat → Code → restart → wznowienie sesji →
   usunięcie klucza.

**Brama akceptacyjna:** brak regresji xAI/Google; OpenAI działa po czystej instalacji i
po aktualizacji istniejącej Caelo; klucz nie występuje w logach, bazie ani crash dumpie.

**Status funkcjonalny 2026-09-01:** użytkownik potwierdził na żywo Chat, odczyt plików
przez Code/Agent, text-to-image oraz edycję z obrazem referencyjnym. Budowa instalatora
pozostaje świadomie odroczona zgodnie z decyzją użytkownika.

### Faza 6 — funkcje opcjonalne, osobna decyzja

Po stabilizacji Chat/Agent można osobno zaplanować:

- generowanie i edycję obrazów przez rodzinę GPT Image — **ZAKOŃCZONE i sprawdzone na żywo:**
  `gpt-image-2`, Images API, wiele referencji, wariacje, rozmiar, jakość,
  PNG/JPEG/WebP, tło, kompresja i moderacja `low`/`auto`,
- Realtime/Voice,
- modele wideo,
- usługowe konta organizacyjne lub workload identity.

Te elementy nie blokują pierwszego wydania i nie powinny poszerzać jego test matrix.

---

## 7. Pliki przewidziane do zmiany

### Backend

- `caelo_core/providers/openai/*` — nowy adapter.
- `caelo_core/providers/responses_transport.py` — wspólny transport/parser.
- `caelo_core/responses_client.py` — zgodnościowa fasada xAI po refaktorze.
- `caelo_core/models/openai_models.py`, `registry.py`, `pricing.py`.
- `caelo_core/routes/chat.py`, `settings.py`, `secrets.py`.
- `caelo_core/agent/runner.py`, ewentualnie `session.py` wyłącznie dla neutralnego
  dispatchu, bez providerowych payloadów.
- `caelo_core/runtime_secrets.py`, `state.py`, `providers/errors.py`.

### Desktop

- `desktop/src/main/secrets.ts`, `desktop/src/main/index.ts`.
- `desktop/src/renderer/src/components/Settings.tsx`, `ChatView.tsx`.
- `desktop/src/renderer/src/components/code/AgentPanel.tsx`, `CodeView.tsx`.
- `desktop/src/renderer/src/lib/agentModels.ts`, typy API i stan ustawień.

### Testy i dokumentacja

- nowe testy kontraktowe OpenAI Chat i Agent,
- rozszerzenie testów faz 6/7 o trzeci provider i migrację sejfu v2,
- testy komponentów selektora providera/modelu,
- README, SECURITY/Privacy, Diagnostics i changelog.

---

## 8. Minimalna macierz testów

| Warstwa | Testy bez sieci | Test na żywo |
|---|---|---|
| Sekret | migracja v1→v2, save/delete, brak wycieku | test auth |
| Registry | merge discovery+fallback, capabilities | modele dostępne dla konta |
| Chat | payload, `store:false`, SSE, UTF-8, stop, usage | krótka odpowiedź + obraz |
| Search | właściwy tool per provider, cytowania | jedno zapytanie web |
| Agent | tool call/result, parallel, approval, undo, resume | read-only tool |
| Błędy | 401/429/timeout/context/bad JSON | kontrolowany zły model |
| UI | provider/model, pamięć wyboru, status per provider | przełączanie zakładek |
| Build | PyInstaller, typecheck, unit/integration | czysta instalacja Windows |

---

## 9. Ryzyka i środki zaradcze

1. **Zmienne aliasy i dostępność modeli.** Registry z capabilities + discovery + cache;
   brak polegania na samej nazwie modelu.
2. **Rozrost wyjątków providerowych.** Dispatch przez adaptery zamiast kolejnych
   `if provider == ...` w trasach i runnerze.
3. **Różnice function callingu.** Neutralny kontrakt i testy równoważności trzech
   providerów, szczególnie `call_id` i wywołań równoległych.
4. **Nieobsługiwane parametry.** Capability guard usuwa `temperature`, reasoning lub
   tool przed wysłaniem, zamiast czekać na błąd API.
5. **Koszt web search/reasoningu.** Funkcje domyślnie kontrolowane przez użytkownika,
   rzeczywiste `usage`, lokalne limity kosztu.
6. **Mylenie ChatGPT z API.** UI mówi „OpenAI API key” i nie sugeruje, że subskrypcja
   ChatGPT automatycznie finansuje lub uwierzytelnia API.
7. **Regresja xAI przy współdzieleniu parsera.** Złote fixture SSE xAI przed refaktorem
   oraz test porównujący wynik starej i nowej ścieżki.
8. **Retencja danych u dostawcy.** `store:false`, brak Conversations API w MVP i jasny
   opis rzeczywistej polityki danych w ustawieniach.

---

## 10. Definicja ukończenia

Integracja jest ukończona dopiero, gdy:

- OpenAI jest równorzędnym, zapamiętywanym wyborem w Chat i Code;
- klucz jest zaszyfrowany, migrowalny i nigdy nie trafia do renderera;
- czat streamuje, przyjmuje załączniki, obsługuje stop, usage i cytowania;
- agent przechodzi tę samą macierz bezpieczeństwa co xAI i Google;
- `store:false` jest wymuszone i pokryte testem;
- koszt nieznanego modelu nie jest przedstawiany jako zero;
- build Windows przechodzi po czystej instalacji i aktualizacji;
- wszystkie testy xAI i Google pozostają zielone.
