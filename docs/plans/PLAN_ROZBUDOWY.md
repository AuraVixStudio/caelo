# PLAN_ROZBUDOWY.md — Grok Desktop (v2)

> **Kierunek (ustalony):** open-source **all-in-one hub Grok** (czat + image + video +
> voice + code w jednym), Windows teraz → macOS/Linux docelowo, model **BYO-key**.
> Rozszerza `REBUILD_PLAN.md` (ten sam folder). Numeracja milestone'ów od M9.
>
> **Zmiana vs v1:** agent kodujący NIE jest już rdzeniem — jest jednym z pięciu trybów.
> Środek ciężkości przesunięty na **spójność między trybami** i **jakość każdego trybu**.
>
> **Postęp (2026-06-07):** ✅ **M9** (szkielet huba) · ✅ **M10** (czat: Responses API + live search) ·
> ✅ **M11** (twórczość: Image/Video — jednolita kolejka `GenJob` + galeria + koszt) ·
> ✅ **M12** (głos: dyktowanie + Talk-pipeline + read-aloud + koszt) ·
> ✅ **M13** (agent: zaufanie — diffy/plan/checkpointy/GROK.md; ⬜ tylko per-hunk F5) ·
> ✅ **M14** (rozszerzalność: klient MCP stdio + komendy + hooki + skille — B1–B6 + F1–F5) ·
> ✅ **M15** (OSS + cross-platform: rebranding „Caelo" + Apache-2.0/CLA + PTY/tree-kill cross-platform +
> gitleaks + CI + auto-update + pakowanie mac/Linux — M15-1/1b/2–9).
> ✅ **M16** (społeczność: marketplace `.caelopkg`) · ✅ **M17** (subagenci: role + worktree + `TeamManager`) ·
> ✅ **M18** (runda jakości / SWOT: dekompozycja `state.py`, pytest, testy frontu).
> ✅ **M19** (parytet z oficjalnym Grok CLI — z analizy dystrybucji Grok CLI) — **Tier-1/2/3 KOMPLETNE** (kod
> w drzewie roboczym, selfchecki zielone; zostają weryfikacje LIVE u usera):
> **Tier-1** (§0 `AgentRunner` · B1 headless/CLI · B2 ACP stdio · B3 LSP · B4 reguły glob) ·
> **Tier-2** (B5 interop AGENTS/CLAUDE.md + `.mcp.json`/`~/.claude` · B6 skille-orkiestratory · B7 sandbox OS
> seatbelt/bwrap · B8 pamięć hybrydowa embeddings+kNN) · **Tier-3** (B9 effort · B10 eksport-md/auto-compact ·
> B11 persony+I/O · B12 realne git-worktree · B13 web_fetch · B14 config hierarchiczny). Selfchecki:
> `agent_selfcheck` 184+, nowe `headless_check`/`acp_check`/`lsp_check`/`sandbox_check`/`embeddings_check`,
> `mcp_check` 36. **Zostają weryfikacje LIVE u usera** (xAI/exec blokowane w sandboxie) + spike
> **B0 `cli-chat-proxy` NIEZACZĘTY**. Rozpisy:
> `PLAN_M9_SZKIELET.md`, `PLAN_M10_CZAT.md`, `PLAN_M11_TWORCZOSC.md`, `PLAN_M12_GLOS.md`,
> `PLAN_M13_AGENT_ZAUFANIE.md`, `PLAN_M14_ROZSZERZALNOSC.md`, `PLAN_M16_SPOLECZNOSC.md`,
> `PLAN_M17_SUBAGENCI.md`, `PLAN_M19_PARYTET_GROK_CLI.md` + `PLAN_M19_TIER1.md` + `PLAN_M19_TIER2.md` +
> `PLAN_M19_TIER3.md`.

---

## 0. Co już ustalone / zweryfikowane

- **Odbiorca:** open source (power-userzy + społeczność). Model **BYO-key** (user wnosi
  własny klucz xAI) — zero kosztów inferencji i infrastruktury po Twojej stronie.
- **Zakład wartości:** all-in-one hub, nie wyspecjalizowany agent.
- **Platformy:** Windows teraz, macOS/Linux docelowo → **nie kop sobie dołka Windows-only już teraz**.
- **Tryb Code:** wchodzą **subagenci** (zespół wyspecjalizowanych agentów), nie tylko pojedynczy agent — patrz M17.
- **Tylko Grok:** brak innych providerów/modeli → **bez warstwy provider-agnostic**. Rdzeń projektowany pod xAI;
  jedyna abstrakcja to cienka warstwa endpoint/auth (hedge na zmiany `auth.x.ai`), nie multi-provider.
- **API xAI (sprawdzone w docs):**
  - ✅ Function calling (kompatybilne z SDK OpenAI/Anthropic, `tool_choice`, równoległe wywołania).
  - ✅ Wbudowane narzędzia serwerowe: `web_search()`, **`x_search()` (live X)**, wykonywanie kodu.
  - ✅ Rozumienie dokumentów (PDF/arkusze/prezentacje) i wizja.
  - 💲 Narzędzia serwerowe ~$5 / 1000 wywołań + tokeny → **wbuduj licznik/limit kosztów**.
  - ⚠️ Zweryfikuj, czy tool-use działa na tokenie OAuth (`auth.x.ai`), czy wymaga klucza API.

---

## 1. Punkt wyjścia (fundament)

| Warstwa | Stan | Atut |
|---|---|---|
| Architektura | Electron + sidecar FastAPI, handshake, /health, auto-restart | Stabilny most |
| Czat | Streaming SSE (UTF-8), wybór modelu | Baza pod tryby |
| Multimodal | Image / Video / Voice — moduły działają | **Rdzeń produktu „hub"** |
| Agent | `session.py`, `tools.py`, podział READONLY/MUTATING | Jeden z trybów (Code) |
| Bezpieczeństwo | `PermissionGate`, sandbox `Workspace.resolve`, scrubbed env, `WsStream`, fail-closed | Rzadkość — to fosa |
| Jakość | `agent_selfcheck.py` (81 asercji), typecheck, ESLint, Vitest | Harness regresji |

**Wniosek:** masz pięć działających trybów, ale prawdopodobnie jako **pięć osobnych zakładek**.
Produktem „all-in-one" stają się dopiero wtedy, gdy zaczną **dzielić jeden szkielet**.

---

## 2. Wizja / North Star

> **Najlepszy otwarty desktop do wszystkiego, co Grok** — rozmawiaj, widź, słuchaj,
> twórz i koduj — gdzie tryby dzielą **jeden kręgosłup** (kontekst, historia, załączniki,
> workspace), a nie są pięcioma niezależnymi kartami w jednym oknie.

Konkurenci to teraz nie tylko Claude Code/Codex (tryb Code), ale też desktopy typu
ChatGPT/Grok i lokalne huby (LM Studio, Jan, Cherry Studio, Open WebUI). Twoja przewaga:
**jedno spójne miejsce + natywne supermoce Groka (live X search, wizja) + open source/BYO-key**.

---

## 3. Trzy filary (rebalans pod hub)

- **Filar 1 — Spójny szkielet huba (~30%).** Tkanka łącząca tryby: współdzielony kontekst,
  jedna przeszukiwalna historia, pipeline załączników (image→czat→agent), wspólny workspace,
  paleta komend. **To czyni z aplikacji „all-in-one", a nie zakładkowy wrapper.**
- **Filar 2 — Doskonałość każdego trybu (~45%).** Każdy tryb na tyle dobry, by być daily-driverem:
  czat (live search + wizja + Q&A nad dokumentami), image (gen+edycja+warianty), video, voice
  (tryb czasu rzeczywistego sterujący resztą), code (zaufanie do agenta: diffy/plan/checkpoint).
- **Filar 3 — Otwarta platforma (~25%).** Higiena open source (LICENSE, docs dla kontrybutorów,
  onboarding BYO-key), fundament cross-platform kładziony OD TERAZ, MCP/rozszerzalność, auto-update.

---

## 4. Analiza luki (tryb Code) vs Claude Code / Codex

Dla zakładki Code chcesz „table stakes", nie pełnego parytetu platformowego:

| Funkcja | Status u konkurencji | Twój priorytet w hubie |
|---|---|---|
| Pamięć projektu (`GROK.md`) | CLAUDE.md / AGENTS.md | WYSOKI (tanie) |
| Tryb planowania (read-only → exec) | tak | WYSOKI (masz podział tooli) |
| Przeglądalne diffy (accept/reject) | tak | **KRYTYCZNY** dla zakładki Code |
| Checkpointy / undo | tak | WYSOKI |
| Klient MCP | tak | **WYSOKI** (mnożnik dla całego huba, nie tylko Code) |
| Komendy / hooki / skills | tak | ŚREDNI |
| Subagenci / zespoły | tak | **W ZAKRESIE** (decyzja podjęta — M17, po MCP) |
| Multi-surface (IDE/chmura/telefon) | tak | **POMIŃ** |

---

## 5. Roadmapa (kolejność pod all-in-one)

Plaster pionowy = UI + backend + asercje w `agent_selfcheck.py`. S≈dni, M≈1–2 tyg., L≈3–4 tyg. (solo).

### FILAR 1 — najpierw kręgosłup

**✅ M9 — Szkielet huba**  *(KAMIEŃ WĘGIELNY — to definiuje „all-in-one")* — **KOMPLETNY**
- **Magistrala kontekstu (M).** Wynik jednego trybu staje się wejściem innego: wygenerowany
  obraz → „opisz w czacie" / „użyj w agencie"; fragment kodu → „wygeneruj diagram". (Na screenie
  już robisz „Opisz obraz" z załącznikiem — usystematyzuj to jako wzorzec „Wyślij do…").
- **Jedna historia + wyszukiwanie (M).** Wszystkie tryby w jednej, przeszukiwalnej historii
  (dziś osobny moduł History — rozszerz na pełnotekstowe szukanie po treści i typie).
- **Pipeline załączników (M).** Spójny model „artefaktu" (obraz/wideo/audio/plik) przepływającego
  między trybami; podgląd, drag&drop, „użyj jako wejście".
- **Wspólny workspace/projekt (S).** Pojęcie projektu współdzielone przez tryby (masz
  `recent_workspaces` w ustawieniach — podnieś je do obywatela pierwszej kategorii).
- **Paleta komend (S).** Ctrl/Cmd-K: skok do dowolnego trybu/akcji — szybka spójność UX.

### FILAR 2 — doskonałość trybów

**✅ M10 — Czat na poziomie**  *(KOMPLETNY 2026-06-05 — `PLAN_M10_CZAT.md`, B1–B6 + F1–F6)*
- ✅ **Live search (S/M).** `web_search()` + `x_search()` przez Responses API; klikalne cytowania +
  licznik kosztów w UI. **Potwierdzone na realnym API.** Wyróżnik huba.
- ✅ **Wizja na wejściu (S).** Obraz w czacie → vision (rodzina grok-4); reuse pipeline załączników M9.
- ✅ **Q&A nad dokumentami (M).** PDF/arkusz jako `input_file` → odpowiedź z treści. **Potwierdzone na realnym API.**
- ✅ **Wiedza projektu.** ⚠️ xAI **nie ma** serwerowych vector stores (`/v1/vector_stores` → 404), więc
  zamiast `file_search`: dokumenty lokalnie w projekcie + „Attach all" na żądanie (na bazie `input_file`).

**✅ M11 — Twórczość (Image / Video)**  *(KOMPLETNY 2026-06-05 — `PLAN_M11_TWORCZOSC.md`, B1–B5 + F1–F6)*
- ✅ **Edycja i warianty obrazu (M).** Edycja przez referencję (do 3) + „Make variations" + „Wyślij do…".
  (inpainting/upscale odpuszczone — API ich nie wystawia.)
- ✅ **Pętla wideo (M).** Async kolejka `GenJob` (text→video / image→video): status, anuluj/ponów, galeria wyników.

**✅ M12 — Głos**  *(KOMPLETNY 2026-06-05 — `PLAN_M12_GLOS.md`, B1–B5 + F1–F5)*
- ✅ **Dyktowanie (F1).** Mikrofon (STT) wstrzykiwany do czatu i agenta (≥2 tryby).
- ✅ **Rozmowa „Talk" (B3/F2).** Pipeline STT-stream → Responses (M10: live search + historia M9) →
  TTS; stany listening/thinking/speaking + barge-in. Niskolatencyjny **realtime** (B4) jako tryb Live.
- ✅ **Read-aloud (F3)** + **ustawienia głosu/języka (F4)** + **licznik kosztu audio (B5/F5)**.

**✅ M13 — Agent: zaufanie**  *(table stakes dla zakładki Code)* — **KOMPLETNY** (poza per-hunk; commit `e8956bf`)
- ✅ **Przeglądalne diffy (L).** Każda mutacja → diff w karcie zatwierdzenia: accept/reject per plik
  (binarny → znacznik „binary"). ⬜ **per hunk = F5** (odłożone).
- ✅ **Tryb planowania (M).** Tylko narzędzia READONLY → plan → akceptacja → wykonanie. Rozszerzone do
  **4 trybów** (ask/accept-edits/plan/bypass) — selektor „Mode" jak w Claude Code.
- ✅ **Checkpointy / undo (M).** Snapshot kopii plików do `.grok/checkpoints/<sid>/` (bez zależności od
  gita) + „Undo to checkpoint" / „Undo all"; `run_command` → „partial undo".
- ✅ **`GROK.md` (S).** Auto-pamięć projektu (workspace + global) w system prompcie agenta + edytor w UI.

### FILAR 3 — otwarta platforma

**✅ M14 — Rozszerzalność (mnożnik dla całego huba)**  *(KOMPLETNY 2026-06-05 — `PLAN_M14_ROZSZERZALNOSC.md`, B1–B6 + F1–F5)*
- ✅ **Klient MCP (L).** `grok_core` jako klient MCP (własna cienka warstwa synchroniczna stdio,
  newline JSON-RPC 2.0 — nie SDK, hybryda; transport abstrakcyjny pod HTTP/remote) → narzędzia
  zewnętrzne dostępne dla czatu i agenta, bramkowane przez `PermissionGate`. Native remote MCP (B3)
  jako passthrough do xAI.
- ✅ **Komendy + hooki + skills (M).** `/plan` `/review` `/commit` `/test` `/mcp` + własne (composer
  `/` + paleta); hooki = uogólniony `PermissionGate` (pre/post-tool + audyt); skille jako pakiety
  (Ren'Py/DAZ jako pierwsze, wstrzykiwane do agenta). Moduł UI **Extensions**.

**✅ M15 — Open source & fundament cross-platform**  *(KOMPLETNY 2026-06-05 — `PLAN_M15_OSS_CROSSPLATFORM.md`, M15-1/1b/2–9)*
- ✅ **Rebranding → „Caelo" (M15-1b).** Pełny, też wewnętrzny: `grok_core`→`caelo_core`, `grok_*`→`caelo_*`,
  `GROK_CORE_*`→`CAELO_CORE_*`, `window.grok`→`window.caelo`, `GROK.md`→`CAELO.md`; migracja danych bez utraty.
- ✅ **Higiena OSS (M15-1/2/4).** Apache-2.0 + NOTICE + CLA(+bot) + CONTRIBUTING + CODE_OF_CONDUCT + SECURITY +
  README (BYO-key); gitleaks (config+pre-commit+CI); historia czysta z sekretów; **telemetrii brak**.
- ✅ **Abstrakcja platformowa (M15-5/6/7).** PTY cross-platform (`pty_compat`: pywinpty/Windows, stdlib `pty`/Unix),
  tree-kill SIGTERM→SIGKILL na POSIX, `DATA_DIR` per-OS, audyt Windows-only czysty (selfcheck `crossplatform_check`).
- ✅ **CI + auto-update + pakowanie (M15-3/8/9).** CI: 7 self-checków + lint + vitest + gitleaks; electron-updater;
  cele mac/Linux (dmg/AppImage/deb) + `build_sidecar.sh` + matryca `release.yml`. ⚠️ 3 kroki sieciowe do dopięcia
  przez utrzymującego (devDeps lint/test, electron-updater, owner/repo+sekrety GitHub) — patrz rozpis M15.

**M16 — Społeczność (gdy rdzeń stabilny)**
- Marketplace skills/komend/szablonów; szablony projektów; itch.io-style udostępnianie (Twój etos „Shareable").

**M17 — Agent: zespoły (subagenci)**  *(głębia trybu Code; wykonać PO M14/MCP — subagenci żywią się narzędziami)*
- **Subagenci (L).** Pod-sesje z własnym oknem kontekstu i zawężonym zestawem narzędzi (np. reviewer,
  tester, researcher), orkiestrowane przez głównego agenta. Budujesz na `session.py` — ta sama pętla,
  izolowany stan; każdy subagent dostaje własny `PermissionGate`/sandbox, wynik wraca streszczony do nadrzędnego.
- **Worktrees / równoległość (M).** Praca równoległa w osobnych katalogach roboczych (osobne snapshoty/checkpointy).
- **Uwaga zakresowa:** to jedyny element „przerostu" względem czystego huba — uzasadniony, bo świadomie
  chcesz, by zakładka Code dorównywała Claude Code/Codex. Trzymaj go ZA MCP i diffami, nie przed.

---

## 6. Strategia rozwoju

### Zasady
1. **Kręgosłup przed funkcjami.** M9 (szkielet) pierwsze — bez niego masz pięć zakładek, nie hub.
2. **Najtańsze duże skoki najpierw.** Live search/wizja (M10) to ogromny efekt za mały koszt, bo
   narzędzia są wbudowane w API. Zrób je wcześnie — to też demo, które się sprzedaje.
3. **Buduj na prymitywach.** `PermissionGate`, `WsStream`, `Workspace.resolve`, podział tooli —
   każda nowość wpina się w nie, nie obok.
4. **Plastry pionowe (UI+backend+selfcheck).** Jedna funkcja end-to-end zanim następna.
5. **Cross-platform jako higiena, nie projekt.** Decyzje architektoniczne neutralne platformowo
   od teraz; właściwe buildy mac/Linux dopiero przy realnym popycie.
6. **Hedge na kruchość xAI (bez multi-providera).** Narzędzie jest TYLKO pod Grok — nie budujesz
   warstwy provider-agnostic. CLAUDE.md ostrzega jednak o `auth.x.ai`, więc trzymaj **cienką warstwę
   endpoint/auth** (jeden punkt zmiany URL/precedencji klucza) + fallback na klucz API. To wszystko —
   żadnego abstrahowania pod Ollamę/inne modele.
7. **Koszt jako obywatel pierwszej kategorii.** Tiering modeli (szybki Grok do tanich operacji),
   licznik wywołań narzędzi serwerowych (~$5/1000), cache kontekstu/indeksu. Spójne z BYO-key:
   user widzi i kontroluje własne wydatki.
8. **Selfcheck-driven.** Każde narzędzie/hook dorzuca asercje; nie regresuj hardeningu M1/M5–M6.

### Kolejność (rekomendacja)
**M9 → M10 → M13(diffy) → M14(MCP)** to ścieżka, po której masz spójny, sprzedawalny hub z
mocnym czatem (live search), działającą twórczością i godnym zaufania agentem. M11/M12 wplataj
równolegle (osobne moduły). M15 prowadź ciągle w tle. M16 dopiero przy stabilnym rdzeniu.
**M17 (subagenci) na końcu** — to pogłębienie Code, sensowne dopiero gdy agent ma już diffy (M13)
i narzędzia z MCP (M14).

### Model dystrybucji (open source — opcje, nie porada finansowa)
- **BYO-key (wybrane):** zero kosztów inferencji; najniższe tarcie; idealne dla OSS.
- **Wsparcie:** GitHub Sponsors / donacje; ewentualnie płatne dodatki (sync, chmura zadań) później.
- **Licencja:** decyzja do podjęcia — permisywna (MIT/Apache-2.0) maksymalizuje adopcję;
  copyleft (GPL/AGPL) chroni przed zamkniętymi forkami. To wybór strategiczny, nie techniczny.

### Ryzyka i mitigacje
| Ryzyko | Mitigacja |
|---|---|
| xAI psuje OAuth/endpointy | Abstrakcja modelu; fallback na klucz; tool-use przez klucz API |
| Tool-use niedostępny na OAuth | Zweryfikuj wcześnie; wymuś ścieżkę klucza API dla agenta jeśli trzeba |
| Koszty narzędzi serwerowych zaskakują usera | Licznik + limit + jasne UI (model BYO-key = jego pieniądze) |
| Scope creep (5 trybów, solo) | Twarda kolejność; plastry pionowe; „table stakes" w Code, nie parytet |
| Dług Windows-only | Abstrakcja pty/kill od teraz |

---

## 7. Status decyzji

- ✅ **Subagenci** — w zakresie (M17, po MCP/diffach). Świadomy „przerost" dla parytetu Code z Claude Code/Codex.
- ✅ **Tylko Grok** — brak warstwy provider-agnostic; cienka warstwa endpoint/auth jako jedyny hedge.
- ⏳ **Licencja** — do podjęcia. Permisywna (Apache-2.0) = maksymalna adopcja + ochrona patentowa;
  copyleft (GPL-3.0 / AGPL-3.0 dla sieci) = ochrona przed zamkniętym forkiem. Przy modelu BYO-key
  ryzyko komercyjne i tak jest niskie — Apache-2.0 jeśli priorytetem jest adopcja, GPL-3.0 jeśli
  ochrona przed forkiem „Pro".
