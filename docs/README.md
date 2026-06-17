# Dokumentacja — Caelo

Indeks dokumentów projektu, pogrupowany w foldery. Główny opis i szybki start:
[`../README.md`](../README.md). Instrukcje dla asystenta / architektura w pigułce:
[`../CLAUDE.md`](../CLAUDE.md).

```
docs/
├── README.md            ← ten indeks
├── guides/              ← dla użytkownika / integratora (EN)
└── plans/               ← plany i rozpisy (PL)
    ├── (aktywne)        ← mapa drogowa + otwarte punkty + runda w toku
    └── zrealizowane/    ← archiwum ukończonych milestone'ów i rund napraw
```

> **Porządek (2026-06-17):** ukończone rozpisy milestone'ów (M9–M22) i domknięte rundy napraw
> (1–3) przeniesiono do [`plans/zrealizowane/`](plans/zrealizowane/). W `plans/` zostają tylko
> dokumenty z **otwartymi** punktami. Wszystkie nieukończone zadania zebrano w jednym miejscu:
> [`plans/PLAN_OTWARTE.md`](plans/PLAN_OTWARTE.md).

## `guides/` — dla użytkownika i integratora

| Dokument | Co zawiera | Status |
|---|---|---|
| [`guides/USER_GUIDE.md`](guides/USER_GUIDE.md) | **Przewodnik użytkownika (EN)** — krok po kroku przez wszystkie 9 modułów (Chat, Code/agent, Image, Video, Gallery, Voice, History, Extensions, Settings) + kluczowe koncepcje (projekty, send-to, koszty, prywatność) i troubleshooting. Pierwszy przystanek dla użytkownika końcowego. | ✅ |
| [`guides/API.md`](guides/API.md) | **Referencja API backendu (EN)** — pełna lista **96 tras REST + 6 WS** pogrupowana po domenach, model autoryzacji (Bearer/token w query, fail-closed), handshake, protokoły ramek WS + snippet do regeneracji listy. Dla deweloperów/integratorów. | ✅ |
| [`guides/PACKAGES.md`](guides/PACKAGES.md) | **Przewodnik po pakietach społeczności (M16, EN)** — format `.caelopkg`, model bezpieczeństwa (zgoda, integralność sha256, brak auto-uruchamiania), registry git-based, publikacja, kuracja i zgłaszanie złośliwych pakietów. | ✅ |
| [`guides/registry.example.json`](guides/registry.example.json) | **Przykładowy indeks registry** (M16-3) — wzór pliku do hostowania w repo git, na który wskazuje Marketplace → Browse → Registry URL. | ✅ |

## `plans/` — plany i rozpisy

### Aktywne — otwarte punkty (czytaj te najpierw)

| Dokument | Co zawiera | Status |
|---|---|---|
| [`plans/PLAN_OTWARTE.md`](plans/PLAN_OTWARTE.md) | **★ Zbiorczy plan wszystkich niezrealizowanych punktów** (2026-06-17) — publikacja (Faza B), weryfikacja LIVE (D/F/G/H/I/J/K + reszta E), TOP-10 (TOP7–10), motywy inżynierskie 4.1, spike B0, ROAD-4.2 (inni dostawcy LLM), per-hunk diff (M13-F5). Jedno źródło prawdy „co zostało". | 🔧 w toku |
| [`plans/REBUILD_PLAN.md`](plans/REBUILD_PLAN.md) | Plan przebudowy customtkinter → Electron + Python sidecar: decyzje, architektura, **Fazy 0–8** (datowane statusy) oraz **§13 „Faza 9"** rekonsolidująca stan (moduły, stack, pełna lista endpointów). Źródło prawdy architektury. | Fazy 0–8 ✅ |
| [`plans/PLAN_ROZBUDOWY.md`](plans/PLAN_ROZBUDOWY.md) | **Mapa drogowa „all-in-one hub" (v2)** — rozszerza REBUILD_PLAN od M9: trzy filary (szkielet huba / doskonałość trybów / otwarta platforma), kolejność, ryzyka. Blok „Postęp" = jednolinijkowy status M9–M22. | M9–M22 ✅ |
| [`plans/PLAN_NAPRAWY_4.md`](plans/PLAN_NAPRAWY_4.md) | **Runda napraw #4** (84 znaleziska z analizy 2026-06-10) — Fazy **A/D/E/F ✅** (P1 + P2/P3 współbieżność/odzysk/limity + frontend). **Otwarte:** Faza B (publikacja), C (LIVE), G (TOP7–10) + motywy 4.1. | 🟡 A/D/E/F ✅ |
| [`plans/PLAN_FAZA_B_RUNBOOK.md`](plans/PLAN_FAZA_B_RUNBOOK.md) | **Runbook publikacji** — remote (`AuraVixStudio/caelo`) → CI → gitleaks pełnej historii → public → podpisany release (SimplySign) z auto-update. Krok 0 ✅, 6 🟡 (część asystenta), reszta 👤. | 🟡 |
| [`plans/PLAN_WERYFIKACJI_LIVE.md`](plans/PLAN_WERYFIKACJI_LIVE.md) | **Runbook weryfikacji LIVE** (sandbox blokuje xAI/exec — robi user): A–C ✅, E 🟡; **otwarte D/F/G/H/I/J/K**. Tabela wyników na górze. | 🟡 A–C ✅ |
| [`plans/ANALIZA_PROGRAMU_2026-06-10.md`](plans/ANALIZA_PROGRAMU_2026-06-10.md) | **Gruntowny przegląd programu (2026-06-10)** — rewizja wieloagentowa 5 obszarów + testy, 10×P1, katalog P2/P3, **porównanie z konkurencją (TOP-10)**. Źródło `PLAN_NAPRAWY_4.md`. | 📋 analiza |

### Archiwum — zrealizowane rundy napraw

| Dokument | Co zawiera | Status |
|---|---|---|
| [`plans/zrealizowane/MODYFIKACJE.md`](plans/zrealizowane/MODYFIKACJE.md) | **Żywa specyfikacja** nadbudowy na Fazach 0–8: scalenie Generator+Edit → **Image**, **Video** edit/extend, moduł **Voice** (TTS/STT/realtime), załączniki w Chat/Code, poprawki UI. Tu szukaj kontraktów tych modułów. | ✅ |
| [`plans/zrealizowane/PLAN_NAPRAWY.md`](plans/zrealizowane/PLAN_NAPRAWY.md) | Hardening do jakości produkcyjnej (**runda 1**, M1–M4) — **P0** (bezpieczeństwo agenta) · **P1** (stabilność/dane) · **P2** (front) · **P3** (testy/CI/pakowanie/dok.). Każdy punkt `[x]` + datowana notatka. | ✅ ZREALIZOWANY |
| [`plans/zrealizowane/PLAN_NAPRAWY_2.md`](plans/zrealizowane/PLAN_NAPRAWY_2.md) | Naprawy/rozwój (**runda 2**, M5–M8) z niezależnego przeglądu — luki rezydualne: kolejka WS agenta (P0-9), metaznaki POSIX (P0-10), env terminala (P0-11), REST fail-open (P1-10), atomic write (P1-11), perystencja rozmów (P2-8), ESLint/testy tras (P3-7…P3-9). | ✅ ZREALIZOWANY (M5–M8) |
| [`plans/zrealizowane/PLAN_NAPRAWY_3.md`](plans/zrealizowane/PLAN_NAPRAWY_3.md) | Naprawa słabych stron (**runda 3 / M18**) z **analizy SWOT** po M9–M17 — **dług utrzymaniowy, bez P0**: logowanie cichych `except` (P1-15), dekompozycja `state.py` (P2-13), `sandbox: true`/log no-token (P2-14), devDeps→lockfile (P3-10), testy komponentów+E2E (P3-11), cross-platform CI (P3-12), pytest + rozbicie `api_smoke.py` (P3-13), dokumentacja użytkownika (P3-14). | ✅ ZREALIZOWANY (8/8) |

### Archiwum — rozpisy milestone'ów (hub v2 — M9–M22)

| Dokument | Milestone | Status |
|---|---|---|
| [`plans/zrealizowane/PLAN_M9_SZKIELET.md`](plans/zrealizowane/PLAN_M9_SZKIELET.md) | **M9** — szkielet huba: magazyn SQLite/FTS5, magistrala kontekstu „send-to", pipeline załączników, projekty, paleta komend. | ✅ |
| [`plans/zrealizowane/PLAN_M10_CZAT.md`](plans/zrealizowane/PLAN_M10_CZAT.md) | **M10** — czat: Responses API (streaming), live web/X search, wizja, Q&A nad dokumentami, cytowania + licznik kosztów. | ✅ |
| [`plans/zrealizowane/PLAN_M11_TWORCZOSC.md`](plans/zrealizowane/PLAN_M11_TWORCZOSC.md) | **M11** — twórczość: jednolita kolejka `GenJob` (Image/Video), edycja/warianty, galeria, koszt. | ✅ |
| [`plans/zrealizowane/PLAN_M12_GLOS.md`](plans/zrealizowane/PLAN_M12_GLOS.md) | **M12** — głos: dyktowanie (STT), pipeline „Talk", realtime „Live", read-aloud (TTS), licznik kosztu audio. | ✅ |
| [`plans/zrealizowane/PLAN_M13_AGENT_ZAUFANIE.md`](plans/zrealizowane/PLAN_M13_AGENT_ZAUFANIE.md) | **M13** — agent (zaufanie): przeglądalne diffy, 4 tryby (ask/accept-edits/plan/bypass), checkpointy/undo, `CAELO.md`. ⬜ tylko per-hunk (F5). | ✅ |
| [`plans/zrealizowane/PLAN_M14_ROZSZERZALNOSC.md`](plans/zrealizowane/PLAN_M14_ROZSZERZALNOSC.md) | **M14** — rozszerzalność: klient MCP (stdio), komendy, hooki, skille; moduł Extensions. | ✅ |
| [`plans/zrealizowane/PLAN_M15_OSS_CROSSPLATFORM.md`](plans/zrealizowane/PLAN_M15_OSS_CROSSPLATFORM.md) | **M15** — OSS + cross-platform: rebranding „Caelo", Apache-2.0/CLA, PTY/tree-kill cross-platform, gitleaks, CI, auto-update, pakowanie mac/Linux. | ✅ |
| [`plans/zrealizowane/PLAN_M16_SPOLECZNOSC.md`](plans/zrealizowane/PLAN_M16_SPOLECZNOSC.md) | **M16** — społeczność: marketplace `.caelopkg`, bezpieczny import (zgoda + integralność), registry git, szablony projektów. | ✅ |
| [`plans/zrealizowane/PLAN_M17_SUBAGENCI.md`](plans/zrealizowane/PLAN_M17_SUBAGENCI.md) | **M17** — subagenci/zespoły: `delegate`, role, izolowane worktree, `TeamManager`, merge review. | ✅ |
| [`plans/zrealizowane/PLAN_M19_PARYTET_GROK_CLI.md`](plans/zrealizowane/PLAN_M19_PARYTET_GROK_CLI.md) | **M19 (analiza)** — parytet z oficjalnym Grok CLI: co adoptujemy, podział na Tier-1/2/3 + spike B0. | analiza |
| [`plans/zrealizowane/PLAN_M19_TIER1.md`](plans/zrealizowane/PLAN_M19_TIER1.md) | **M19 Tier-1** — §0 `AgentRunner`, B1 headless/CLI, B2 ACP, B3 LSP, B4 reguły glob. | ✅ |
| [`plans/zrealizowane/PLAN_M19_TIER2.md`](plans/zrealizowane/PLAN_M19_TIER2.md) | **M19 Tier-2** — B5 interop ekosystemu, B6 skille-orkiestratory, B7 sandbox OS, B8 pamięć hybrydowa. | ✅ |
| [`plans/zrealizowane/PLAN_M19_TIER3.md`](plans/zrealizowane/PLAN_M19_TIER3.md) | **M19 Tier-3** (quick-winy) — B9 effort, B10 eksport-md/auto-compact, B11 persony+I/O, B12 git-worktree, B13 web_fetch, B14 config hierarchiczny. | ✅ |
| [`plans/zrealizowane/PLAN_M21_SESJE_KODU.md`](plans/zrealizowane/PLAN_M21_SESJE_KODU.md) | **M21** — zapis i **wznawianie sesji agenta** w trybie Code: wspólny magazyn `agent/sessions.py` (v2), ramka WS `session`, REST `/agent/sessions`, menu „Sessions" + filtr po projekcie/folderze i tekstem. | ✅ |
| [`plans/zrealizowane/PLAN_M22_PROJEKTY_CZATU.md`](plans/zrealizowane/PLAN_M22_PROJEKTY_CZATU.md) | **M22** — **rozdzielenie projektów czatu od workspace'ów Code** (`projects.kind` chat/code) + instrukcje per projekt, rename/delete, wiedza w przełączniku (`ProjectSwitcher` = menedżer), grupowanie rozmów. | ✅ |

> **Uwaga:** brak osobnego `PLAN_M18` — runda jakości M18 jest opisana w `plans/zrealizowane/PLAN_NAPRAWY_3.md`.
> Brak też osobnego `PLAN_M20` — runda feedbacku **M20** (ogólne skille builtin zamiast VN, przełącznik
> projektu w czacie, komendy + @-pliki w composerze Code, generowanie obrazów/wideo w czacie —
> `chat_media_tools`) jest udokumentowana w `../CLAUDE.md` i historii commitów.
> Weryfikacje **LIVE** zależne od xAI (realny agent, ACP w Zed/Neovim, LSP/embeddings/sandbox, `web_fetch`)
> oraz spike **B0 (`cli-chat-proxy`)** pozostają do potwierdzenia na maszynie użytkownika (sandbox blokuje sieć/exec).

## Jak czytać

1. **Nowy w projekcie?** → [`../README.md`](../README.md) (architektura, moduły, szybki start), potem [`../CLAUDE.md`](../CLAUDE.md) (zasady i pułapki — m.in. dlaczego rdzeń xAI zostaje w korzeniu repo).
2. **Użytkownik — jak korzystać z modułu?** → `guides/USER_GUIDE.md` (krok po kroku, EN).
3. **Deweloper — jaka trasa / endpoint?** → `guides/API.md` (96 REST + 6 WS); kontekst projektowy → `plans/REBUILD_PLAN.md` §13 lub `plans/zrealizowane/MODYFIKACJE.md`.
4. **Co już zrobione / gdzie jesteśmy?** → `plans/PLAN_ROZBUDOWY.md` (blok „Postęp") + rozpisy `plans/zrealizowane/PLAN_M*.md`.
5. **Co jeszcze zostało?** → [`plans/PLAN_OTWARTE.md`](plans/PLAN_OTWARTE.md) (zbiorczy plan otwartych punktów).
6. **Stan napraw / co utwardzone?** → `plans/zrealizowane/PLAN_NAPRAWY.md` (runda 1 ✅), `plans/zrealizowane/PLAN_NAPRAWY_2.md` (runda 2 ✅), `plans/zrealizowane/PLAN_NAPRAWY_3.md` (runda 3 / M18 ✅), `plans/PLAN_NAPRAWY_4.md` (runda 4 — w toku).

## Powiązane README (poza `docs/`)

- [`../caelo_core/README.md`](../caelo_core/README.md) — backend: instalacja venv, **lista endpointów**, self-checki.
- [`../desktop/README.md`](../desktop/README.md) — frontend: skrypty, struktura, wybór interpretera Pythona.

> Legacy customtkinter (dawniej `archive/`) został usunięty z repo (kopia zewnętrzna) — domknięcie Fazy 8.
