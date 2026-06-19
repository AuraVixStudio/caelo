# PLAN_OTWARTE.md — zbiorczy plan niezrealizowanych punktów

> **Cel:** jedno źródło prawdy „**co jeszcze zostało**". Zebrane z audytu dokumentacji
> planowania (2026-06-17) — pozostałe otwarte pozycje z [`PLAN_NAPRAWY_4.md`](PLAN_NAPRAWY_4.md),
> [`PLAN_FAZA_B_RUNBOOK.md`](PLAN_FAZA_B_RUNBOOK.md), [`PLAN_WERYFIKACJI_LIVE.md`](PLAN_WERYFIKACJI_LIVE.md)
> oraz odłożone punkty z ukończonych milestone'ów (archiwum w [`zrealizowane/`](zrealizowane/)).
> **Gałąź robocza:** `m15-oss-crossplatform` (nie `main`).
>
> **Stan ogólny (kontekst):** budowa funkcjonalna jest **kompletna** — M9–M22 ✅, rundy napraw
> 1–3 ✅, runda 4 Fazy **A/D/E/F ✅** (P1 + współbieżność/odzysk/limity + frontend P2/P3).
> Dominujące ryzyko to **NIE brak kodu**, lecz: (1) **brak publikacji/remote** („OSS bez repo",
> jedyna kopia na jednym dysku) i (2) **nawis niezweryfikowanej powierzchni LIVE** (self-checki
> są zielone, ale na mockach — sandbox dewelopera blokuje `api.x.ai` i exec OS).
>
> **Legenda:** ⬜ do zrobienia · 🟡 częściowe · 👤 = wymaga maszyny użytkownika (sieć/credentiale/
> realny OS) · 🤖 = wykonalne przez asystenta (kod/config). Priorytety: **P1** przed publikacją ·
> **P2** rdzeń/jakość · **P3** nisza/quick-win.

---

## 0. Streszczenie — co zostało, w pigułce

| # | Blok | Priorytet | Kto | Skrót |
|---|---|---|---|---|
| 1 | **Publikacja (Faza B)** | P1 | 👤+🤖 | ✅ **DOMKNIĘTA 2026-06-17** — remote+CI+gitleaks+pytest+podpisany release `v0.1.0`; zostaje tylko public repo → auto-update end-user |
| 2 | **Weryfikacja LIVE** | P1/P2 | 👤 | ✅ A/B/C/E/F · zostają: D (głos), G (MCP/headless/ACP/LSP), H (funkcje-widma — decyzja), I (pakiety), J (cross-platform), K (terminal) |
| 3 | **Nowe funkcje TOP-10** | P2/P3 | 🤖 | TOP7 rewind czatu, TOP8 inline Ctrl-K, TOP9 auto-pamięć usera, TOP10 background-agents |
| 4 | **Motywy inżynierskie 4.1** | P2/P3 | 🤖 | odporność (4.1-c), wydajność (4.1-b), API total/cost (4.1-e), /genjobs WS-push (4.1-f) |
| 5 | **Strategiczne / długoterminowe** | P2/P3 | 🤖+👤 | ROAD-4.2-a (inni dostawcy LLM), spike B0 (`cli-chat-proxy`), ROAD-4.2-b |
| 6 | **Odłożone z milestone'ów** | P3 | 🤖 | M13-F5 (diff per-hunk), TOP5 mermaid |

---

## 1. Publikacja — Faza B  ✅ DOMKNIĘTA 2026-06-17 (poza public/auto-update)

> **Pełny runbook:** [`PLAN_FAZA_B_RUNBOOK.md`](PLAN_FAZA_B_RUNBOOK.md). Kolejność jest
> **własnością bezpieczeństwa** — `scan-before-public` nieprzekraczalny.
> **Decyzje (2026-06-12):** repo `AuraVixStudio/caelo` (organizacja); code signing = Asseco
> **SimplySign** (cert w chmurze → podpis **lokalny**, nie w CI).
>
> **Stan 2026-06-17: B-1…B-4 ✅** — remote + CI zielone + gitleaks czysty + pytest zielony +
> **podpisany release `v0.1.0`** opublikowany. **Jedyna pozostałość:** upublicznienie repo
> (świadomie odłożone) → od tego zależy auto-update dla end-userów. Repo **prywatne**.

- [x] **B-1 · ROAD-3.6-a — remote + push + 1. bieg CI** `[S]` 👤 — **✅ ZROBIONE 2026-06-17**
  - Remote `AuraVixStudio/caelo` (prywatne); wypchnięto `m15-oss-crossplatform` (1743 obiekty, 1.82 MiB) + `main`;
    **CI na `main` zielone** (job „CI" 1m 29s + Dependency Graph). Gitleaks org-license nie był potrzebny.
  - **+ przepisanie historii git:** `git-filter-repo` 2.47.0 — 74 commity, autor → `AuraVix Studio <auravix@auravixstudio.com>`, usunięte trailery `Co-authored-by:`, force-push. (Szczegóły: `PLAN_FAZA_B_RUNBOOK.md`.)
- [x] **B-2 · ROAD-3.6-b — gitleaks na PEŁNEJ historii** `[S]` 👤 — **✅ SKAN CZYSTY 2026-06-17** · ⏸️ public odłożone
  - gitleaks 8.30.1: `74 commits scanned, no leaks found`. **Repo pozostaje PRYWATNE** (decyzja usera —
    upublicznienie to osobna, świadoma decyzja na później; bramka „scan-before-public" spełniona).
- [x] **B-3 · ROAD-3.6-f — dev-deps + pytest lokalnie** `[S]` 👤 — **✅ ZROBIONE 2026-06-17**
  - pytest 9.1.0 → `13 passed in 17.16s`. Domyka `0.4` z `PLAN_WERYFIKACJI_LIVE`. ⚠️ pułapka: `Scripts\pip.exe`
    rzucał `Fatal error in launcher` → użyć `python.exe -m pip` (zepsuty shim po odtworzeniu venv).
- [x] **B-4 · ROAD-TOP2 / ROAD-3.6-c — podpis SimplySign + auto-update + release** `[S/M]` 👤+🤖 — **✅ ZROBIONE 2026-06-17**
  - Cert SimplySign `AuraVix Studio` (thumbprint `B6DB11F7…4393C67`, do 2027-03-04) → `certificateSha1`
    w `electron-builder.yml`; `electron-updater` w locku. Release **`v0.1.0`**: podpisany
    `Caelo-Setup-0.1.0.exe` (129 MB) + `.blockmap` + `latest.yml`; sidecar podpisany osobno.
  - ⏸️ **Auto-update dla end-userów** wymaga **publicznego** repo (electron-updater nie czyta `latest.yml`
    z prywatnego repo bez auth). Mechanizm gotowy — czeka na decyzję o public (patrz B-2).
  - 🤖 zrobione (2026-06-13): guard `release.yml` (`--publish never` + artifact), szablon podpisu
    SimplySign w `electron-builder.yml`, bramkowany podpis sidecara w `build_sidecar.ps1`.
  - 👤 zostaje: `npm install electron-updater` (utrwalenie w locku), setup SimplySign Desktop,
    odczyt CN/Thumbprint → odkomentowanie w `electron-builder.yml`, lokalny podpisany `dist:full` + tag.
  - **DoD:** w GitHub Releases podpisany `Caelo-Setup-0.1.0.exe` + `latest.yml`; starsza wersja oferuje
    aktualizację; SmartScreen nie ostrzega (zależnie od typu certu).

---

## 2. Weryfikacja LIVE — Faza C  🟠 P1/P2 (robi user — sandbox blokuje xAI/exec)

> **Gotowe przykłady „co zrobić":** [`FAZA_C_PRZYKLADY.md`](FAZA_C_PRZYKLADY.md) — konkretne prompty,
> komendy, configi (`.caelo/permissions.json`, `lsp.json`) i kryteria „✅ zaliczone" dla każdego punktu.
> **Pełny runbook z krokami/pułapkami:** [`PLAN_WERYFIKACJI_LIVE.md`](PLAN_WERYFIKACJI_LIVE.md)
> (tabela wyników na górze). Status zaliczone: **A** (auth) · **B** (czat) · **C** (Image/Video).
> Po każdym teście: zaktualizuj tabelę wyników i skoryguj „zrobione (mock)" → realny status w docs.

- [x] **E — Agent kodowania** P1 ✅ **CAŁA SEKCJA (2026-06-17)** — E1–E10 zaliczone na żywo (E5 checkpointy/undo,
  E6 CAELO.md, E9 reguły glob deny>allow, E10 LSP diagnostyka pyright). Po drodze naprawiono m.in. loop guard
  (zapętlenie na edit_file), URI-match LSP na Windows, sesja przeżywa zmianę zakładki. Szczegóły: `PLAN_WERYFIKACJI_LIVE.md` rundy 8–11.
- [ ] **D — Głos** P2 🟡 — **D1 TTS ✅ + D2 STT batch ✅ 2026-06-19.** D1: 5 głosów + EN/PL, read-aloud + Speak,
  badge kosztu. D2: dyktowanie czat/Code + Transcribe (transkrypt PL poprawny, koszt z czasu). **2 bugi naprawione:**
  feedback Settings → toast (`17c2caa`); **CSP `script-src` bez `blob:` blokował AudioWorklet → Talk/Live/STT-stream
  padały „Audio capture is unavailable" — dodano `blob:` (`a02e67f`, +test).** ⚠️ koszt TTS = SZACUNEK (faktura).
  **D5 Live ✅** (dwukierunkowa rozmowa głos↔głos). **D3 ROZSTRZYGNIĘTE: streaming `/v1/stt` niekompatybilny** —
  log mostu pokazał, że xAI odrzuca `input_audio_buffer.append` (`expected audio.done`), oczekuje innego/binarnego
  formatu; partiale na żywo odłożone do dokumentacji endpointu. **D4 Talk przepięty na batch-STT + VAD** (auto-stop
  na ciszy, `497cbb2`) — czeka na retest na żywo. **Zostają: retest D4, D6/D7 (read-aloud z ustawień + badge kosztu sesji).**
- [x] **F — Subagenci / zespoły** P2 ✅ **2026-06-18 — CAŁA SEKCJA** (F1 delegacja end-to-end; F2 review-modal +
  merge→workspace + checkpoint cofalny + wykrycie konfliktu; F3 cascade stop → tree-kill potwierdzony;
  F4 skill `implement` steruje delegate+rolami). Po drodze naprawione 3 bugi UX: review-modal, zwijanie
  panelu Team, `shrink-0`/scroll.
- [ ] **G — Rozszerzalność** P2 🟡 — **G1+G2+G3+G5+G6 ✅ 2026-06-19** (realny MCP stdio + w agencie + w czacie;
  interop `.mcp.json`/`AGENTS.md`/`~/.claude/skills` niedestrukcyjnie; headless CLI plain/json/streaming-json
  + fail-closed + allow + sesje; LSP ✅ w E10). Po drodze **4 realne bugi backendu**: cwd serwera (`3a004ef`),
  `start_enabled` martwy kod (`0376351`), warm-start (`24d4a4a`), **MCP-provider — agent gubił narzędzia po
  rebuildzie** (`dc8da65`). Zostają: G4 remote MCP (xAI-side), G7 ACP (Zed/Neovim/Emacs).
- [ ] **H — Funkcje-widma OFF-by-default** P3 ⬜ — **DECYZJA: włączyć po teście ALBO usunąć** (martwy kod = SWOT W3):
  - [ ] **H1 ⭐ embeddings spike** (`embeddings_check.py --live`) — **gate dla całego B8**; 404/400 → odłóż/usuń B8 (NIE wprowadzać torch).
  - [ ] **H2** pamięć hybrydowa (zależy od H1) · **H3** sandbox OS (bwrap/seatbelt na Linux/mac) · **H4** web_fetch (SSRF-guard) · **H5** git worktree · **H6** auto-compact.
- [ ] **I — Pakiety / marketplace** P3 ⬜ — I1 fetch registry, I2 instalacja `.caelopkg` (zgoda + integralność; install disabled), I3 export/share (sekrety zdjęte).
- [ ] **J — Cross-platform** P3 ⬜ (gdy dostęp do mac/Linux) — J1 build dmg/AppImage/deb, J2 PTY, J3 tree-kill POSIX.
- [ ] **K — Terminal** P3 ⬜ — K1 pywinpty + potwierdzenie scrubbed env (`echo $env:XAI_API_KEY` puste).

---

## 3. Nowe funkcje wg TOP-10 — Faza G (reszta)  🟢 P2/P3

> Zaliczone: **TOP1** (web_search agenta) · **TOP3** (widżet planu) · **TOP4** (katalog MCP one-click) ·
> **TOP5** (artefakty HTML/SVG; mermaid odłożony) · **TOP6** (recenzja PR przez `gh`). **TOP2** = Faza B (B-4 wyżej).

- [ ] **TOP7 — Rewind / edycja wiadomości czatu** `[M]` 🤖 — lokalny `useConversations`. **Odblokowane** (P1-H/P1-I zrobione).
- [ ] **TOP8 — Inline Ctrl-K w CodeMirror** `[M]` 🤖 — CM6 decoration API; przy okazji `langFor` useMemo (już w S35-k).
- [ ] **TOP9 — Auto-pamięć użytkownika** `[M]` 🤖 — infra M19-B8 (`embeddings`/`memory.py`) istnieje; brak ekstrakcji + UI. **Opt-in!** Zależne od H1 (embeddings live).
- [ ] **TOP10 — Lokalne background-agents + powiadomienia** `[M+S]` 🤖 — headless B1 + kolejka genjobs + worktree M17 + Notification API (powiadomienia = szybki sub-win).

---

## 4. Motywy inżynierskie przekrojowe (4.1)  🟢 P2/P3 🤖

> Z [`PLAN_NAPRAWY_4.md`](PLAN_NAPRAWY_4.md) §„Motywy 4.1". 4.1-a (współbieżność) i 4.1-d
> (kanał błędów) **zrobione** w Fazach D/E.

- [ ] **4.1-c — odporność** `[M]` — retry `poll_video_status` (1 timeout = utrata płatnego wideo); `fsync`
  przed `os.replace` dla `caelo_auth.json`/`caelo_settings.json`; `Backend.shutdown()` domyka
  genjobs/history_store (checkpoint WAL); tolerancja wieloliniowych `data:` w SSE.
- [ ] **4.1-b — wydajność gorących ścieżek** `[M]` — cache `_resolve_auth` (inwalidacja na zapis settings);
  kNN poza lockiem; `compute_changes` przez `os.stat`; prune `dirnames` w `glob`; memo `EntryView`.
- [ ] **4.1-e — API** `[S]` — realne `total` (COUNT), `total_cost` przez SUM, rozróżnienie 4xx w `packages._err`.
- [ ] **4.1-f — `/genjobs` przez WS-push** `[M]` — hook `on_update` istnieje, nieużyty (po P1-D, który jest zrobiony).

---

## 5. Strategiczne / długoterminowe  🔵 P2/P3

- [ ] **ROAD-4.2-a — inni dostawcy LLM / modele lokalne** `[M/L]` 🤖 — `base_url`-override w cienkim
  `responses_client` (mitygacja ryzyka single-provider xAI: 410/404 bez ostrzeżenia). **NIE** restrukturyzować
  root `api_manager.py` (reguła CLAUDE.md). **Strategicznie #1 długoterminowo.**
- [ ] **Spike B0 — `cli-chat-proxy.grok.com`** `[?]` 👤 (wysokie ryzyko / wysoki zwrot) —
  z [`zrealizowane/PLAN_M19_PARYTET_GROK_CLI.md`](zrealizowane/PLAN_M19_PARYTET_GROK_CLI.md) §7. **NIE ZACZĘTY.**
  Pytanie: czy token z `auth.x.ai` (Caelo) przejdzie na `cli-chat-proxy.grok.com/v1/chat/completions`
  (subskrypcja grok.com/SuperGrok zamiast płatnego API)? Audience tokenu `auth.x.ai` vs `accounts.x.ai` — do sprawdzenia na maszynie usera.
- [ ] **ROAD-4.2-b — tuż za podium** `[M]` 🤖 — pętla test-and-fix (`post_tool`), `.caeloignore`, onboarding.
- **Świadomie NIE teraz:** tab-autocomplete (brak FIM u xAI), multi-root (serce sandboxa P0),
  chmurowe agent-runnery (sprzeczne z local-first).

---

## 6. Odłożone z milestone'ów  ⚪ P3 🤖

- [ ] **M13-F5 — diff per-hunk** — z [`zrealizowane/PLAN_M13_AGENT_ZAUFANIE.md`](zrealizowane/PLAN_M13_AGENT_ZAUFANIE.md).
  Obecnie accept/reject per **plik**; per-hunk odłożone.
- [ ] **TOP5 — mermaid w artefaktach** — z [`PLAN_NAPRAWY_4.md`](PLAN_NAPRAWY_4.md) Faza G. CSP blokuje skrypt
  z CDN; bundlowanie wymaga `npm install mermaid` (psułoby `npm ci`/typecheck bez instalacji) — decyzja świadoma.

### 6a. Higiena po publikacji v0.1.0 (z sesji 2026-06-17)  🤖

- [x] **`author` w `desktop/package.json`** `grooverpty` → `AuraVix Studio` — **✅ ZROBIONE 2026-06-17**
  (NSIS `COMPANY_NAME` wyciekał starą nazwę w logach buildu; wpływa na metadane przyszłych instalatorów,
  nie na już wydany `v0.1.0`).
- [ ] **CI `release.yml` — deprecation Node** `[S]` — ⚠️ input `node-version` jest już `"22"`; ostrzeżenie
  „Node.js 20 deprecated" dotyczy najpewniej **runtime'u akcji** (`actions/*@v4` działają na Node20), nie inputu.
  Realna naprawa = bump akcji (`actions/setup-node@v5`, `actions/checkout@v5`, itd.), nie `node-version`.
  Zweryfikować z logiem CI (która akcja emituje warning) przed zmianą.
- [ ] **CI `release.yml` — 3× job „Build (UNSIGNED)" czerwone** `[S]` — wg sesji to **brak zależności na
  runnerach**, nie problem architektury (`--publish never` w CI jest zamierzony — patrz `PLAN_FAZA_B_RUNBOOK.md`
  Krok 6.4). Wymaga logu nieudanego joba, by zidentyfikować brakującą zależność (np. PyInstaller/venv kroku
  `pack:sidecar` na ubuntu/macos). Niski priorytet — podpisane wydania i tak robione lokalnie.

---

## 7. Rekomendowana kolejność

1. ~~**Faza B — publikacja**~~ ✅ **DOMKNIĘTA 2026-06-17** (B-1…B-4: remote+CI+gitleaks+pytest+podpisany
   release `v0.1.0`). Pozostaje tylko decyzja o upublicznieniu repo → odblokowuje auto-update end-user.
2. **Faza C — weryfikacja LIVE** w kolejności priorytetu: **E-reszta → D/F/G** (rdzeń) → **H** (decyzja
   włącz/usuń, zaczynając od H1 embeddings = gate B8) → **I/J/K**. Po każdej sekcji: skoryguj docs
   („mock" → realny status), to domyka dług „dokumentacja przecenia kompletność" (SWOT W2).
3. **ROAD-4.2-a** (inni dostawcy LLM) — najważniejsza mitygacja strategiczna; równolegle **spike B0** (user).
4. **Faza G — TOP7–10** (od pozycji odblokowanych: TOP7 po P1-H/I) + **motywy 4.1** (b/c/e/f).
5. **P3 odłożone** (M13-F5, mermaid) — gdy reszta stabilna.

---

*Audyt + konsolidacja: 2026-06-17. Szczegóły kroków/pułapek/`plik:linia` — w dokumentach źródłowych
(linkowane wyżej). Pozycje `⬜` = do zrobienia; po wykonaniu odhacz i zaktualizuj status w dokumencie źródłowym.*
