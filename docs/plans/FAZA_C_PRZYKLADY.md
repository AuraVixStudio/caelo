# FAZA_C_PRZYKLADY.md — cookbook weryfikacji LIVE (co konkretnie zrobić)

> **Po co:** [`PLAN_WERYFIKACJI_LIVE.md`](PLAN_WERYFIKACJI_LIVE.md) mówi *co* sprawdzić; ten plik daje
> **gotowe przykłady** — dokładne prompty, komendy, configi i kryteria „✅ zaliczone". Wykonuj na
> SWOJEJ maszynie (sandbox blokuje xAI/exec). Po każdym punkcie odhacz `[ ]` w `PLAN_WERYFIKACJI_LIVE.md`.
>
> **Kolejność (rekomendacja):** najpierw **E-reszta + D** (rdzeń), potem **F/G**, na końcu **H/I/J/K**.
> **Legenda „✅ gdy":** warunek zaliczenia. ⚠️ = pułapka. Każdy przykład jest niezależny.

---

## 0. Przygotowanie wspólne (raz)

```powershell
# z korzenia repo
# 1) auth: NAJPROSTSZE = klucz w .env (korzeń):  XAI_API_KEY=xai-...   (albo zaloguj OAuth w apce)
# 2) odpal apkę
cd desktop; npm run dev          # okno Electrona; brak błędów w DevTools
```
- **Testuj na KOPII repo**, nie na oryginale — agent pisze pliki:
  `Copy-Item -Recurse G:\jakies\repo G:\test\repo-kopia`
- **Modele (z `config.py`):** czat `grok-4.3` · obraz `grok-imagine-image` · wideo
  `grok-imagine-video-1.5-preview` · głos `grok-voice-latest` · embeddingi `embedding-beta-3-small`.
  Wizja/dokumenty wymagają rodziny **grok-4**.
- **⚠️ Backend NIE hot-reloaduje** — po każdej zmianie pliku `.caelo/*.json`, `lsp.json`, env (`$env:CAELO_*`)
  zrób **pełny restart `npm run dev`** (Ctrl+C + ponownie). Vite HMR odświeża tylko renderer.

---

## E — Agent kodowania (reszta: E5, E6, E9, E10)  🟠 P1

> Otwórz zakładkę **Code**, wybierz folder roboczy (kopię repo). E1–E4, E7–E8 już ✅.

### E5 — Checkpointy + undo
- **Przykład promptu (1 tura, ≥3 pliki):**
  > „Create three files in the workspace: `notes/a.txt`, `notes/b.txt`, `notes/c.txt`, each with one line of text."
- **Kroki:** tryb `accept-edits` → wyślij → poczekaj na zakończenie → nagłówek Code → popover
  **„Checkpoints & undo"** → **„Undo all"** (lub „Undo to here" na wcześniejszej turze).
- **✅ gdy:** wszystkie 3 pliki znikają (utworzone → usunięte); przy edycji istniejących wracają do treści
  sprzed tury, w **odwrotnej kolejności**. Jeśli w turze był `run_command` → baner „partial undo".

### E6 — `CAELO.md` wpływa na zachowanie
- **Przygotowanie:** nagłówek Code → **„Project rules (CAELO.md)"** → wpisz regułę:
  ```markdown
  # Project rules
  - ALWAYS add a one-line docstring to every new Python function.
  - Prefer f-strings over .format().
  ```
- **Przykład promptu:**
  > „Add a function `slugify(text)` to `util.py` that lowercases and replaces spaces with dashes."
- **✅ gdy:** wygenerowana funkcja MA docstring i używa f-stringów (agent zastosował regułę z CAELO.md).
  ⚠️ Restart nie jest potrzebny — CAELO.md czytane per tura.

### E9 — Reguły glob (deny > allow, M19-B4)
- **Przygotowanie:** w workspace utwórz `.caelo\permissions.json`:
  ```json
  {
    "deny": ["Bash(rm*)", "Edit(secret/**)"],
    "allow": ["Edit(src/**)"]
  }
  ```
  Utwórz też plik `secret\keys.txt` i katalog `src\`. **Restart `npm run dev`** (reguły ładują się przy wyborze workspace).
- **Przykłady promptów (po kolei, tryb `accept-edits`):**
  1. > „Edit `src/app.py` and add a comment line." → **✅ auto-akceptacja** (allow `Edit(src/**)`).
  2. > „Edit `secret/keys.txt` and append a line." → **✅ twarda odmowa** (deny `Edit(secret/**)`), nawet bez pytania.
  3. > „Run `rm src/app.py`." → **✅ odmowa** (deny `Bash(rm*)`).
- **✅ P0-1 zachowane (osobny test):** dodaj `"allow": ["Bash(git*)"]`, potem poproś:
  > „Run `git status && rm -rf .`" → **musi zostać zablokowane** (metaznaki `&&` łapie P0-1 mimo allow `Bash(git*)`).

### E10 — LSP diagnostyka (Content-Length framing, M19-B3)
- **Instalacja serwera (pyright — Python):** `npm i -g pyright`, potem sprawdź PATH:
  `(Get-Command pyright-langserver).Source` (musi zwrócić ścieżkę; pusto → reopen terminala / PATH).
- **Dodanie serwera — NAJŁATWIEJ przez GUI** (Extensions → **Language Servers** → „Add a language server"):
  Name `pyright` · Command `pyright-langserver --stdio` · Extensions `.py:python` → **Add**. **Bez restartu**
  (`reload_lsp`). Status „stopped" jest OK — serwer startuje **leniwie** przy 1. dotknięciu pliku `.py`.
  *(Alternatywa: `<ws>/.caelo/lsp.json` `{"pyright":{"command":"pyright-langserver","args":["--stdio"],"extensionToLanguage":{".py":"python"}}}` — ale to WYMAGA restartu `npm run dev`.)*
  *(tsserver: `npm i -g typescript-language-server typescript`; Command `typescript-language-server --stdio`; Extensions `.ts:typescript,.tsx:typescriptreact`.)*
- **Wyzwolenie diagnostyki** (pasywna, po UDANEJ edycji `.py`). W Code, tryb `accept-edits`, użyj **write_file**
  (zawsze się powiedzie, w przeciwieństwie do edit_file z dopasowaniem):
  > „Create a file `lsp_test.py` with exactly this content: `x: int = 'hello'`"
- **✅ gdy:** w panelu agenta pojawia się ramka **`diagnostics`** z błędem pyright (np. *Type „str" is not
  assignable to „int"*); status serwera w Extensions zmienia się na **„running"**. Narzędzie `lsp` jest widoczne
  modelowi TYLKO gdy serwer skonfigurowany. ⚠️ LSP = binarny Content-Length (≠ MCP).
  ⚠️ **Zimny start:** 1. edycja może nie pokazać diagnostyk (pyright się inicjuje) → kliknij **Restart** na serwerze,
  poczekaj ~15 s, zrób DRUGI `write_file` (np. `y: int = 'x'`) → diagnostyki powinny dojść.

---

## D — Głos  ✅ P2 (zaliczone 2026-06-19)

> **✅ WYNIK LIVE 2026-06-19 (cała sekcja D):** D1 TTS · D2 STT batch · D4 Talk · D5 Live · D6/D7 ✅.
> ⚠️ **D3 (partiale na żywo) NIE DZIAŁA** — `wss://api.x.ai/v1/stt` odrzuca nasz protokół
> (`input_audio_buffer.append`, `expected audio.done`); streaming odłożony. **Talk (D4) używa teraz
> batch-STT + VAD (auto-stop na ciszy)**, nie streamingu — więc poniższy opis D3/D4 „partiale NA ŻYWO"
> jest nieaktualny (zostaje jako historia). Szczegóły + commity: `PLAN_WERYFIKACJI_LIVE.md` sekcja D.
>
> Settings → **Voice** ustaw głos (Eve/Ara/Leo/Rex/Sal) + język. Mikrofon: Electron poprosi o `media`.

- **D1 TTS:** w czacie najedź na odpowiedź → **Read aloud**.
  **✅ gdy:** słychać mowę, badge kosztu rośnie. ⚠️ `TTS_COST_PER_1K_CHARS` to SZACUNEK — sprawdź realny koszt na fakturze.
- **D2 STT batch (dyktowanie):** ikona mikrofonu w composerze czatu/Code → powiedz „Napisz funkcję dodającą dwie liczby" → stop.
  **✅ gdy:** poprawna transkrypcja ląduje w polu tekstowym; koszt z czasu trwania.
- **D3 STT-stream (partiale):** tryb **Talk** lub live STT → mów dłuższe zdanie.
  **✅ gdy:** widać częściowe transkrypty NA ŻYWO + finalny. ⚠️ **GŁÓWNY ZNAK ZAPYTANIA** — protokół/sample-rate
  `wss://api.x.ai/v1/stt` niepotwierdzony; jeśli śmieci/cisza → zanotuj „NIE DZIAŁA" + zrzut ramek.
- **D4 Talk + barge-in:** tryb **Talk** → zadaj pytanie głosem → **w trakcie odpowiedzi zacznij mówić**.
  **✅ gdy:** stany listening→thinking→speaking; mowa w trakcie = **barge-in** (przerywa TTS); tura zapisana w History.
- **D5 Realtime (Live):** tryb **Live** (`grok-voice-latest`).
  **✅ gdy:** niskolatencyjna rozmowa głos↔głos.
- **D6/D7:** read-aloud z ustawień + badge sumuje koszt audio per sesja.

---

## F — Subagenci / zespoły (M17)  🟡 P2

> Code, tryb `accept-edits`. Subagenci uruchamiają się przez narzędzie `delegate`, więc prompt musi być **złożony, wieloczęściowy**.

- **F1 delegacja end-to-end — przykład promptu:**
  > „Use your team: delegate a researcher to summarize how `config.py` resolves data paths, an implementer
  > to add a `version()` helper to `util.py`, and a reviewer to check the result. Run them in parallel."
  **✅ gdy:** **TeamView** pokazuje subagentów (researcher/implementer/reviewer) równolegle; kontekst rodzica
  czysty (jedna wiadomość `tool` = streszczenia, NIE pełny transkrypt); subagenci NIE mają `delegate` (głębia 1).
- **F2 merge review (worktree):** po zakończeniu mutującego subagenta → **„Review merge"**.
  **✅ gdy:** JEDEN diff; jeśli 2 subagenty ruszyły ten sam plik → wykryty **konflikt**; Apply → checkpoint (cofalny), Reject → discard.
- **F3 cascade stop:** w trakcie pracy zespołu kliknij **Stop** orkiestratora.
  **✅ gdy:** wszystkie subagenty się zatrzymują (a `run_command` w nich = tree-kill).
- **F4 skille-orkiestratory (M19-B6):** Extensions → Skills → włącz `implement` (lub `review`/`design`/`best-of-n`)
  → w Code: > „Use the implement skill to add input validation to `parse_args()`."
  **✅ gdy:** skill steruje `delegate`+rolami; sensowny przebieg wielo-agentowy.

---

## G — Rozszerzalność: MCP / headless / ACP  🟡 P2

### G1 — Realny serwer MCP (stdio)
- **Najprościej (TOP4 katalog):** Extensions → **MCP → Catalog → „filesystem"** → podaj ścieżkę → Install → **Start**.
  (Pod spodem: `npx -y @modelcontextprotocol/server-filesystem <ścieżka>`.)
  **✅ gdy:** narzędzia `mcp__filesystem__*` pojawiają się na liście; subproces hardened (Windows `.cmd`/`npx`→`cmd /c`).
- **G2 MCP w agencie:** w Code: > „Use the filesystem MCP tool to write `hello.txt` with 'hi'."
  **✅ gdy:** mutujące MCP → karta approval `mcp_tool_call` (gate po `readOnlyHint`); READONLY bez pytania.
- **G3 MCP w czacie:** w czacie poproś o akcję narzędzia MCP. **✅ gdy:** mutujące działa TYLKO gdy wcześniej
  dopuszczone na allowliście, inaczej odmowa z komunikatem (czat nie ma modala approval).
- **G4 remote MCP (native):** skonfiguruj serwer z `type: mcp, server_url` → wykonanie po stronie xAI (bez lokalnej bramki).

### G5 — Interop ekosystemu (M19-B5)
- **Przygotowanie:** w workspace utwórz `.mcp.json` i `AGENTS.md`; jeśli masz `~/.claude.json` / `~/.claude/skills` — zostaw.
- **✅ gdy:** serwery z `~/.claude.json`+`.mcp.json` importowane **`enabled=False`** (autostart pomija);
  `AGENTS.md`/`CLAUDE.md` sklejone do promptu agenta; skille z `~/.claude/skills` odkryte (badge źródła).
  ⚠️ **Odczyt NIEDESTRUKCYJNY** — sprawdź, że Twoje pliki `.claude` NIE zostały nadpisane/zbackupowane.

### G6 — Headless CLI (M19-B1)
```powershell
# plain / json / streaming-json; fail-closed bez --permission-mode bypass/accept-edits lub reguły allow
caelo_core\.venv\Scripts\python -m caelo_core run -p "List files and summarize the README" --cwd G:\test\repo-kopia --output-format json
caelo_core\.venv\Scripts\python -m caelo_core run -p "Add a test for foo()" --cwd G:\test\repo-kopia --permission-mode accept-edits --allow "Edit(**)"
```
- **✅ gdy:** `plain`/`json`/`streaming-json` dają poprawny strumień; BEZ `--permission-mode`/`--allow`
  mutacje są **odrzucane** (fail-closed); sesja zapisana w `DATA_DIR\sessions\`.

### G7 — ACP (M19-B2)
- W Zed/Neovim/Emacs skonfiguruj agenta ACP komendą: `python -m caelo_core acp`
  (pełna ścieżka: `caelo_core\.venv\Scripts\python -m caelo_core acp`).
- **✅ gdy:** JSON-RPC po stdio działa, `session/request_permission` poprawnie korelowane, ramki → `session/update`.

---

## H — Funkcje-widma OFF-by-default (DECYZJA: włączyć ALBO usunąć)  ✅ P3 (zdecydowane 2026-06-19)

> **✅ WYNIK LIVE 2026-06-19:** **H1 ⛔** — xAI **404** na `/v1/embeddings` → **B8/pamięć (H1+H2) ODŁOŻONE**
> (uśpione+udok., bez torch). **H4 web_fetch ✅** (https-only+SSRF+allowlista). **H5 git worktree ✅** (realny
> `git worktree` potwierdzony). **H6 auto-compact ✅** (selfcheck; live niepraktyczne, próg 48k). **H3** = Linux/mac
> only (Windows no-op). Wszystkie działające = opt-in (zostaw). Szczegóły: `PLAN_WERYFIKACJI_LIVE.md` sekcja H.
>
> Każda: zweryfikuj → działa = rozważ ON-by-default; nie/niepotrzebna = **usuń martwy kod** (SWOT W3).

- **H1 ⭐ embeddings spike (GATE dla B8):**
  ```powershell
  caelo_core\.venv\Scripts\python caelo_core\tools\embeddings_check.py --live
  ```
  **✅ gdy:** `POST /v1/embeddings` zwraca wektory (~1024 wym.). **❌ 404/400 → xAI nie ma embeddingów →
  odłóż/USUŃ B8 (NIE wprowadzaj torch). Przesądza też TOP9 (auto-pamięć).**
- **H2 pamięć hybrydowa (tylko gdy H1 ✅):** `$env:CAELO_MEMORY="1"; npm run dev` → w sesji #1 podaj fakt
  („mój ulubiony kolor to zielony"), w sesji #2 zapytaj o niego.
  **✅ gdy:** recall wstrzyknięty na 1. turze (kNN∪FTS5).
- **H3 sandbox OS (Linux/mac):** `python -m caelo_core run -p "try to write outside the workspace" --cwd <ws> --sandbox strict`
  **✅ gdy:** bwrap (Linux)/seatbelt (macOS) blokuje zapis poza CWD i sieć. Windows = no-op (oczekiwane).
- **H4 web_fetch:** `$env:CAELO_WEB_FETCH="1"; npm run dev` → w Code: > „Fetch https://example.com and summarize."
  **✅ gdy:** https-only, SSRF-guard blokuje loopback/IP prywatne, narzędzie gated (Always-allow per host); bez flagi ukryte.
- **H5 git worktree:** w repo git: `python -m caelo_core run -p "..." --cwd <repo> --worktree`
  **✅ gdy:** mutujący subagent dostaje realny `git worktree` (start z HEAD), diff vs HEAD, sprzątanie `git worktree remove`.
- **H6 auto-compact:** `$env:CAELO_AUTOCOMPACT="1"` → długa sesja agenta.
  **✅ gdy:** historia przycinana na granicy `user` (balans tool_call↔tool), deterministyczny digest, bez utraty kontraktu xAI.

---

## I — Pakiety / marketplace (M16)  ✅ P3 (zaliczone 2026-06-19)

> **✅ WYNIK LIVE 2026-06-19:** I1–I3 ✅ (round-trip export `plan`→import→ConsentCard→Install; integralność sha256 OK).
> ⚠️ **Domyślny rejestr nieopublikowany** — URL ustawiony na `AuraVixStudio/caelo-packages`, repo trzeba utworzyć
> (startowy plik: `docs/guides/registry.starter.json`); import-only/BYO działa bez rejestru. Tamper/strip-sekretów =
> selfcheck `packages_check` 47/47.
>
- **I1 fetch registry:** Extensions → Marketplace → **Browse**. **✅ gdy:** lista z `PACKAGES_REGISTRY_URL` (https-only).
- **I2 instalacja `.caelopkg`:** Import pliku → **ConsentCard** (uprawnienia/ryzyko) → Install.
  **✅ gdy:** odmowa bez zgody I przy złej integralności (podmień bajt → tamper/sha256); skille install **disabled**, MCP `enabled=False`.
- **I3 export/share:** przycisk **Share/Export** na panelu Skills/Commands/MCP/Templates → plik `.caelopkg`.
  **✅ gdy:** sekrety (`authorization`/`env`) **zdjęte** z eksportu (rozpakuj ZIP i sprawdź `manifest.json`).

---

## J — Cross-platform (M15)  ⚪ P3 (gdy masz mac/Linux)

- **J1 build:** na danym OS `cd desktop; npm run dist:mac` / `dist:linux` (sidecar zbuduj na DOCELOWYM OS: `build_sidecar.sh`).
  **✅ gdy:** powstaje dmg/AppImage/deb.
- **J2 PTY terminal:** Terminal działa (stdlib `pty` na Unix). **J3 tree-kill POSIX:** Stop długiego `run_command`
  zabija drzewo procesów (SIGTERM→SIGKILL). *(Pokrywa się z H3.)*

---

## K — Terminal  ⚪ P3

```powershell
caelo_core\.venv\Scripts\python -m pip install pywinpty   # ⚠️ jeśli "Fatal error in launcher" → python.exe -m pip
# restart npm run dev → otwórz Terminal w apce
```
- **✅ gdy:** interaktywny shell działa; **env scrubbed** — w terminalu apki `echo $env:XAI_API_KEY` = **puste**
  (oraz `echo $env:CAELO_CORE_TOKEN` = puste).

---

## Po weryfikacji

1. Odhacz `[ ]` + wpisz datę/notatkę w [`PLAN_WERYFIKACJI_LIVE.md`](PLAN_WERYFIKACJI_LIVE.md) (tabela wyników na górze).
2. Zamień w docs „zrobione (mock)" → realny status (✅/❌/⏭️) — domyka dług „dokumentacja przecenia kompletność".
3. **Funkcje-widma (H):** po teście włącz domyślnie ALBO usuń martwy kod.
4. Zaktualizuj [`PLAN_OTWARTE.md`](PLAN_OTWARTE.md) §2.

> **Pułapki ogólne:** stare `search_parameters`→410; vector stores→404; cytowania mogą mieć NUMER w `title`;
> STT-stream sample-rate niepotwierdzony; koszt TTS = szacunek; backend NIE hot-reloaduje (restart `npm run dev`).
