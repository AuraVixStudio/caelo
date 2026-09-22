# Spike'i Fazy 0 — weryfikacja ADR-1 i ADR-8

Dwa skrypty rozstrzygające założenia, na których stoi cały plan integracji
([`docs/plans/PLAN_INTEGRACJI.md`](../../docs/plans/PLAN_INTEGRACJI.md)).

| Skrypt | Weryfikuje | Blokuje |
|---|---|---|
| `spike1_google_wire.py` | **ADR-1** — Google przez surowy REST, bez SDK | Fazę 2 (Google jako provider mediów) |
| `spike2_google_tools.py` | **ADR-8** — adapter tool-callingu | Fazę 6 (Gemini jako silnik agenta) |

Oba używają **wyłącznie `requests`**. To celowe: jeśli działają, ADR-1 jest potwierdzone
empirycznie, bo dokładnie w ten sposób Caelo rozmawia dziś z xAI.

---

## Ustalone bez klucza API — analiza statyczna SDK

Zanim uruchomisz cokolwiek: **główna niewiadoma ADR-1 jest już rozbrojona.** Ścieżki REST
wydobyto ze źródeł `@google/genai@2.17.1` (`dist/index.cjs`) leżących w `node_modules`
projektu `gemini-desktop-studio`. SDK nie robi żadnej magii — składa zwykłe ścieżki HTTP.

```
AI Studio         https://generativelanguage.googleapis.com/v1beta/...
Vertex Gemini     https://{location}-aiplatform.googleapis.com/v1beta1/...
Agent Platform    https://aiplatform.googleapis.com/v1beta1/.../locations/global/interactions
Vertex Veo        https://{region}-aiplatform.googleapis.com/v1/.../models/{model}:...

Uwierzytelnienie  AI Studio: x-goog-api-key
                  GCP: Authorization: Bearer <token ADC>
                  (NIGDY parametr w query — dotyczy też pobierania mediów)
```

| Powierzchnia | Operacja | Metoda i ścieżka |
|---|---|---|
| AI Studio | Utworzenie interakcji | `POST /v1beta/interactions` |
| AI Studio | Odczyt interakcji | `GET /v1beta/interactions/{id}` — parametry `stream`, `last_event_id`, `include_input` |
| AI Studio | Usunięcie / anulowanie | `DELETE /v1beta/interactions/{id}` · `POST /v1beta/interactions/{id}/cancel` |
| AI Studio | generateContent | `POST /v1beta/models/{model}:generateContent` |
| AI Studio | Veo — zgłoszenie / polling LRO | `POST /v1beta/models/{model}:predictLongRunning` · `GET /v1beta/{operation.name}` |
| AI Studio | Upload pliku | `POST /upload/v1beta/files` (protokół resumable) |
| Vertex AI | generateContent | `POST /v1beta1/projects/{project}/locations/{location}/publishers/google/models/{model}:generateContent` |
| Agent Platform | Omni — utworzenie / odczyt | `POST /v1beta1/projects/{project}/locations/global/interactions` · `GET .../interactions/{id}` |
| Vertex AI | Veo — zgłoszenie LRO | `POST /v1/projects/{project}/locations/{region}/publishers/google/models/{model}:predictLongRunning` |
| Vertex AI | Veo — polling LRO | `POST /v1/projects/{project}/locations/{region}/publishers/google/models/{model}:fetchPredictOperation` |

**Wniosek:** nie ma powodu wciągać `google-genai` (z `google-auth`, `httpx`, protobuf)
do bundla PyInstallera. Wszystko powyżej to `requests`.

Dwie rzeczy warte odnotowania przy okazji:

- `GET /interactions/{id}` przyjmuje `stream` **i `last_event_id`** — czyli wznawialny
  strumień SSE. To ma bezpośrednie znaczenie dla projektu kolejki w Fazie 3: polling
  po restarcie może podjąć strumień, a nie tylko odpytać o stan.
- Anulowanie interakcji ma własny endpoint. Dziś `JobQueue.cancel` w Gemini Studio
  zatrzymuje tylko polling lokalny — mając `:cancel` możemy w Caelo 2.0 zrobić to
  uczciwiej i faktycznie przerwać zdalną pracę.

---

## Ustalenia z uruchomień na żywo

**`--check` PASS** (2026-08-22, `gemini-3.5-flash-lite`). Kształt odpowiedzi:

```
candidates[].content.parts[].text · finishReason · modelVersion · responseId
usageMetadata.promptTokenCount / totalTokenCount
usageMetadata.promptTokensDetails[].modality   ← tokeny w rozbiciu na modalność
```

`promptTokensDetails[].modality` jest **bogatsze niż to, co daje xAI** — Google rozlicza
tokeny osobno dla tekstu, obrazu i audio. Realnie ułatwia `models/pricing.py` i tabelę
`usage_records` (ADR-3): kosztu multimodalnego nie trzeba szacować, dostajemy go rozbity.

**Vertex AI / ADC PASS** (2026-08-28, lokalizacja `global`). Spike pobrał krótko żyjący
token z istniejącej sesji `gcloud auth application-default login` i wykonał surowym REST-em:

- `gemini-3.5-flash-lite:generateContent` — test połączenia, 1 token;
- `gemini-3.1-flash-image:generateContent` — obraz 1:1 / 1K, poprawny PNG 957 283 B.

Odpowiedź obrazu ma kształt `candidates[].content.parts[].inlineData.{mimeType,data}`.
Rozliczenie zwróciło 12 tokenów tekstowych i 1120 tokenów obrazu. To empirycznie potwierdza
ADR-1 dla wymaganej przez użytkownika ścieżki GCP: generacja obrazu działa bez `google-genai`.

**Wideo przez GCP/ADC również PASS** (2026-08-28):

| Test | Model / powierzchnia | Wynik |
|---|---|---|
| Text-to-video Omni | `gemini-omni-flash-preview` · Agent Platform Interactions API · `global` | **PASS** — 4,011 s, MP4 1 197 579 B, około 31 s oczekiwania. |
| Text-to-video Veo | `veo-3.1-fast-generate-001` · Vertex AI · `us-central1` | **PASS** — 4,000 s, MP4 1 964 731 B, około 48 s oczekiwania. |
| Extend Veo | ten sam model i endpoint; wejście: poprzedni klip 4 s | **PASS** — wynik 11,000 s (oryginał 4 s + kontynuacja 7 s), MP4 5 092 957 B, około 48 s oczekiwania. |

Wyniki potwierdzają rzeczywisty kształt drutu dla wymaganej ścieżki projektu:

- Omni przyjmuje `POST .../locations/global/interactions`, zwraca trwałe `interaction_id`,
  a wynik w trybie `delivery: "inline"` znajduje się w elemencie `type: "video"` jako base64.
- `delivery: "uri"` bez `gcs_uri` jest odrzucane błędem `invalid_request`. Bez wskazanego
  bucketa GCS provider musi żądać `inline`; tryb URI wymaga osobnego ustawienia GCS.
- Veo używa regionalnego API `v1`, payloadu `instances[]` / `parameters{}` i modelu GA
  `veo-3.1-fast-generate-001`; po zgłoszeniu zapisujemy `operation.name`, a polling wykonujemy
  przez `:fetchPredictOperation`.
- Odpowiedź Veo zwróciła `response.videos[].bytesBase64Encoded`. Rozszerzenie zwraca cały
  sklejony klip, nie sam siedmiosekundowy fragment kontynuacji.

To ujawniło rozjazd z kodem dawcy: jego `OmniVideoProvider.ts` blokuje GCP jako niewspierane,
lecz aktualne Agent Platform Interactions API oraz próba na żywo potwierdzają, że tryb GCP/ADC działa.
Blokady tej nie wolno przenosić do Caelo 2.0.

**Kształt błędu różni się między powierzchniami — ważne dla taksonomii błędów w Fazie 2:**

| Endpoint | Kształt błędu |
|---|---|
| `:generateContent` | goły obiekt — `{"error": {...}}` |
| `/interactions` | **tablica** — `[{"error": {...}}]` |

Obie niosą `error.details[].reason` w kształcie `google.rpc.ErrorInfo` (np. `API_KEY_INVALID`).
`_common._error_reason()` obsługuje oba warianty — port do `providers/google/errors.py` musi też.

**Rozróżnienie auth vs kształt.** `SpikeError.is_auth_problem` oddziela błąd klucza/uprawnień
(401/403, `API_KEY_INVALID`, `PERMISSION_DENIED`, …) od błędu kształtu żądania. Tylko ten drugi
mówi cokolwiek o ADR-1 — pierwszy oznacza po prostu, że trzeba naprawić klucz i powtórzyć.

---

## Stan spike'ów

**SPIKE-1 jest zakończony PASS dla podstawowej ścieżki GCP/ADC:** połączenie, obraz,
Omni text-to-video, Veo text-to-video oraz Veo extend działają surowym REST-em bez
`google-genai`. Alternatywna powierzchnia AI Studio z kluczem nie jest warunkiem wejścia
do Fazy 2 i może zostać zweryfikowana później.

**SPIKE-2 jest również zakończony PASS dla GCP/ADC** (`gemini-3.5-flash`, `global`).
Oba techniczne spike'i oraz decyzje O-1…O-5 są zamknięte. **Faza 0 jest zakończona;**
następnym krokiem jest Faza 1 — neutralna warstwa providerów z adapterem xAI.

### Wyniki SPIKE-2 — tool-calling

| Test | Wynik na żywo |
|---|---|
| `functionCall` | Dwa równoległe wywołania: `get_weather` i `get_time`, części `[0, 1]`. |
| Identyfikatory | Każde wywołanie miało natywne `id` (`call_*`). Gemini 3.5 wymaga tego samego `id` w `functionResponse`. |
| Podpis myślenia | Pierwsza część grupy równoległej miała `thoughtSignature`; pełna część została odesłana bez modyfikacji. |
| Runda zwrotna | Dwa dopasowane `functionResponse` zamknęły turę poprawną odpowiedzią tekstową. |
| Streaming | 5 zdarzeń SSE, 3 fragmenty `functionCall`; `name`/`id`/podpis w pierwszej części, argumenty jako przyrostowe `partialArgs[]` z `jsonPath` i `willContinue`. |

To koryguje pierwotne założenie ADR-8, że Google nie ma identyfikatorów. Adapter ma
zachować natywne ID, a syntezować je tylko jako fallback dla starszych modeli. Musi też
przechowywać `thoughtSignature`, pilnować zgodności liczby/nazw/ID wywołań i odpowiedzi
oraz składać streamingowe `partialArgs` po pełnym JSONPath.

---

## Uruchomienie

### Google Cloud / Vertex AI (podstawowa ścieżka projektu)

Zaloguj ADC raz w Google Cloud SDK Shell:

```powershell
gcloud auth application-default login
```

Następnie podaj projekt jawnie. Nie polegaj na `gcloud config get project`, bo aktywny projekt
powłoki może być inny niż projekt ustawiony w Gemini Desktop Studio:

```powershell
caelo_core/.venv/Scripts/python.exe scripts/spikes/spike1_google_wire.py `
  --gcp-project TWOJ_PROJEKT --gcp-location global --check
```

Jedna generacja obrazu (koszt):

```powershell
caelo_core/.venv/Scripts/python.exe scripts/spikes/spike1_google_wire.py `
  --gcp-project TWOJ_PROJEKT --gcp-location global --image --yes-i-accept-cost
```

Testy wideo (każde wywołanie kosztuje):

```powershell
caelo_core/.venv/Scripts/python.exe scripts/spikes/spike1_google_wire.py `
  --gcp-project TWOJ_PROJEKT --gcp-location global --omni --yes-i-accept-cost
```

```powershell
caelo_core/.venv/Scripts/python.exe scripts/spikes/spike1_google_wire.py `
  --gcp-project TWOJ_PROJEKT --gcp-video-location us-central1 --veo --yes-i-accept-cost
```

```powershell
caelo_core/.venv/Scripts/python.exe scripts/spikes/spike1_google_wire.py `
  --gcp-project TWOJ_PROJEKT --gcp-video-location us-central1 `
  --veo-extend scripts/spikes/out/04_veo_gcp_sample.mp4 --yes-i-accept-cost
```

Token ADC nie jest logowany ani zapisywany w projekcie. Spike używa `gcloud` tylko do
pobrania tokenu; docelowa aplikacja użyje lekkiego `google-auth` wyłącznie do obsługi ADC.

Tool-calling przez GCP/ADC (kilka tanich wywołań tekstowych):

```powershell
caelo_core/.venv/Scripts/python.exe scripts/spikes/spike2_google_tools.py `
  --gcp-project TWOJ_PROJEKT --gcp-location global
```

### AI Studio (ścieżka alternatywna)

Klucz **wyłącznie ze zmiennej środowiskowej** — skrypty nie przyjmują go argumentem,
bo argumenty wyciekają do listy procesów.

```powershell
$env:GEMINI_API_KEY = "..."
```

Zacznij zawsze od darmowego testu klucza:

```bash
caelo_core/.venv/Scripts/python.exe scripts/spikes/spike1_google_wire.py --check
```

Potem kolejno (rosnący koszt):

```bash
caelo_core/.venv/Scripts/python.exe scripts/spikes/spike1_google_wire.py --image --yes-i-accept-cost
```

```bash
caelo_core/.venv/Scripts/python.exe scripts/spikes/spike1_google_wire.py --omni --yes-i-accept-cost
```

```bash
caelo_core/.venv/Scripts/python.exe scripts/spikes/spike1_google_wire.py --veo --yes-i-accept-cost
```

Tool-calling (tanie, tylko tekst):

```bash
caelo_core/.venv/Scripts/python.exe scripts/spikes/spike2_google_tools.py
```

**Bramka kosztowa:** `--image`, `--omni`, `--veo` i `--veo-extend` obciążają konto Google. Bez
`--yes-i-accept-cost` skrypt odmawia. `--check` to jeden token.

---

## Wynik

Surowe odpowiedzi lądują w `scripts/spikes/out/*.json` (katalog jest w `.gitignore` —
może zawierać treści z Twojego konta). **To jest właściwy produkt spike'u:** na tych
kształtach budujemy port w Fazie 2, zamiast zgadywać z dokumentacji.

Pola base64 są przycinane w dumpach, żeby dały się czytać — klip Veo to dziesiątki MB.

SPIKE-1 i SPIKE-2 przeszły. ADR-1 oraz wykonalność ADR-8 są potwierdzone dla GCP/ADC;
Faza 2 nie jest blokowana przez kształt API mediów, a Faza 6 ma empiryczny kontrakt adaptera.

---

## Ograniczenie środowiskowe

W środowisku z przechwytywaniem TLS te skrypty nie przejdą — dokładnie tak jak cały ruch
do `api.x.ai` (patrz „Verification limits" w `CLAUDE.md`). Spike'i musi uruchomić
użytkownik na swojej maszynie, z ważnym kluczem.
