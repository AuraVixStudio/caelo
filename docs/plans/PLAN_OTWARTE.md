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
| 1 | **Publikacja (Faza B)** | P1 | 👤+🤖 | 🟡 remote+CI+gitleaks+pytest ✅ (2026-06-17, repo prywatne); **zostaje B-4** podpisany release + auto-update (cert SimplySign) |
| 2 | **Weryfikacja LIVE** | P1/P2 | 👤 | sekcje D (głos), E-reszta, F (subagenci), G (MCP/headless/ACP/LSP), H (funkcje-widma — decyzja), I (pakiety), J (cross-platform), K (terminal) |
| 3 | **Nowe funkcje TOP-10** | P2/P3 | 🤖 | TOP7 rewind czatu, TOP8 inline Ctrl-K, TOP9 auto-pamięć usera, TOP10 background-agents |
| 4 | **Motywy inżynierskie 4.1** | P2/P3 | 🤖 | odporność (4.1-c), wydajność (4.1-b), API total/cost (4.1-e), /genjobs WS-push (4.1-f) |
| 5 | **Strategiczne / długoterminowe** | P2/P3 | 🤖+👤 | ROAD-4.2-a (inni dostawcy LLM), spike B0 (`cli-chat-proxy`), ROAD-4.2-b |
| 6 | **Odłożone z milestone'ów** | P3 | 🤖 | M13-F5 (diff per-hunk), TOP5 mermaid |

---

## 1. Publikacja — Faza B  🟡 P1 (w większości DOMKNIĘTA 2026-06-17)

> **Pełny runbook:** [`PLAN_FAZA_B_RUNBOOK.md`](PLAN_FAZA_B_RUNBOOK.md). Kolejność jest
> **własnością bezpieczeństwa** — `scan-before-public` nieprzekraczalny.
> **Decyzje (2026-06-12):** repo `AuraVixStudio/caelo` (organizacja); code signing = Asseco
> **SimplySign** (cert w chmurze → podpis **lokalny**, nie w CI).
>
> **Stan 2026-06-17:** B-1/B-2/B-3 ✅ — **remote istnieje, CI zielone, gitleaks czysty, pytest zielony**
> (ryzyko „jedyna kopia / OSS bez repo" zdjęte). Repo **prywatne** (public świadomie odłożone).
> Zostaje **tylko B-4** (podpisany release — wymaga certu SimplySign).

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
- [ ] **B-4 · ROAD-TOP2 / ROAD-3.6-c — podpis SimplySign + auto-update + release** `[S/M]` 🟡 👤+🤖 — **jedyny otwarty krok Fazy B (wymaga certu SimplySign)**
  - 🤖 zrobione (2026-06-13): guard `release.yml` (`--publish never` + artifact), szablon podpisu
    SimplySign w `electron-builder.yml`, bramkowany podpis sidecara w `build_sidecar.ps1`.
  - 👤 zostaje: `npm install electron-updater` (utrwalenie w locku), setup SimplySign Desktop,
    odczyt CN/Thumbprint → odkomentowanie w `electron-builder.yml`, lokalny podpisany `dist:full` + tag.
  - **DoD:** w GitHub Releases podpisany `Caelo-Setup-0.1.0.exe` + `latest.yml`; starsza wersja oferuje
    aktualizację; SmartScreen nie ostrzega (zależnie od typu certu).

---

## 2. Weryfikacja LIVE — Faza C  🟠 P1/P2 (robi user — sandbox blokuje xAI/exec)

> **Pełny runbook z krokami/pułapkami:** [`PLAN_WERYFIKACJI_LIVE.md`](PLAN_WERYFIKACJI_LIVE.md)
> (tabela wyników na górze). Status zaliczone: **A** (auth) · **B** (czat) · **C** (Image/Video).
> Po każdym teście: zaktualizuj tabelę wyników i skoryguj „zrobione (mock)" → realny status w docs.

- [ ] **E — Agent kodowania (reszta)** P1 🟡 — zaliczone E1–E4, E7–E8. Zostają:
  - [ ] **E5** checkpointy + undo (wiele plików, „Undo to here/all", baner partial undo po `run_command`).
  - [ ] **E6** `CAELO.md` wpływa na zachowanie agenta (+ edytor reguł w nagłówku Code).
  - [ ] **E9** reguły glob (M19-B4): `--deny Bash(rm*)` / `--allow Edit(src/**)`; deny>allow; P0-1 zachowane.
  - [ ] **E10** LSP diagnostyka (M19-B3): realny pyright/tsserver → ramka `diagnostics`; narzędzie `lsp` tylko gdy skonfigurowane.
- [ ] **D — Głos** P2 ⬜ — D1 TTS (5 głosów, koszt = szacunek!), D2 STT batch, **D3 STT-stream**
  (⚠️ protokół/sample-rate `wss://api.x.ai/v1/stt` NIEPOTWIERDZONY — główny znak zapytania), D4 Talk +
  barge-in, D5 Realtime (Live), D6/D7 read-aloud + koszt sesji.
- [ ] **F — Subagenci / zespoły** P2 ⬜ — F1 delegacja end-to-end, F2 merge review (worktree + konflikt),
  F3 cascade stop (tree-kill), F4 skille-orkiestratory (implement/review/design/best-of-n).
- [ ] **G — Rozszerzalność** P2 ⬜ — G1 realny MCP stdio, G2 MCP w agencie (gate), G3 MCP w czacie
  (allowlista), G4 remote MCP (xAI-side), G5 interop (`~/.claude.json`/`.mcp.json`/`AGENTS.md`/skille — NIEDESTRUKCYJNIE),
  G6 headless CLI (`run -p` plain/json/streaming-json, fail-closed), G7 ACP (Zed/Neovim/Emacs).
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

---

## 7. Rekomendowana kolejność

1. **Faza B — publikacja** (B-1 → B-2 → B-3 → B-4). Remote sam zdejmuje ryzyko #1 (jedyna kopia);
   gitleaks pełnej historii **przed** public jest nieprzekraczalny.
2. **Faza C — weryfikacja LIVE** w kolejności priorytetu: **E-reszta → D/F/G** (rdzeń) → **H** (decyzja
   włącz/usuń, zaczynając od H1 embeddings = gate B8) → **I/J/K**. Po każdej sekcji: skoryguj docs
   („mock" → realny status), to domyka dług „dokumentacja przecenia kompletność" (SWOT W2).
3. **ROAD-4.2-a** (inni dostawcy LLM) — najważniejsza mitygacja strategiczna; równolegle **spike B0** (user).
4. **Faza G — TOP7–10** (od pozycji odblokowanych: TOP7 po P1-H/I) + **motywy 4.1** (b/c/e/f).
5. **P3 odłożone** (M13-F5, mermaid) — gdy reszta stabilna.

---

*Audyt + konsolidacja: 2026-06-17. Szczegóły kroków/pułapek/`plik:linia` — w dokumentach źródłowych
(linkowane wyżej). Pozycje `⬜` = do zrobienia; po wykonaniu odhacz i zaktualizuj status w dokumencie źródłowym.*
