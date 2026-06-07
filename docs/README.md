# Dokumentacja — Caelo

Indeks dokumentów projektu, pogrupowany w foldery. Główny opis i szybki start:
[`../README.md`](../README.md). Instrukcje dla asystenta / architektura w pigułce:
[`../CLAUDE.md`](../CLAUDE.md).

```
docs/
├── README.md          ← ten indeks
├── guides/            ← dla użytkownika / integratora (EN)
└── plans/             ← plany, rozpisy milestone'ów i rundy napraw (PL)
```

## `guides/` — dla użytkownika i integratora

| Dokument | Co zawiera | Status |
|---|---|---|
| [`guides/USER_GUIDE.md`](guides/USER_GUIDE.md) | **Przewodnik użytkownika (EN)** — krok po kroku przez wszystkie 9 modułów (Chat, Code/agent, Image, Video, Gallery, Voice, History, Extensions, Settings) + kluczowe koncepcje (projekty, send-to, koszty, prywatność) i troubleshooting. Pierwszy przystanek dla użytkownika końcowego. | ✅ |
| [`guides/API.md`](guides/API.md) | **Referencja API backendu (EN)** — pełna lista **96 tras REST + 6 WS** pogrupowana po domenach, model autoryzacji (Bearer/token w query, fail-closed), handshake, protokoły ramek WS + snippet do regeneracji listy. Dla deweloperów/integratorów. | ✅ |
| [`guides/PACKAGES.md`](guides/PACKAGES.md) | **Przewodnik po pakietach społeczności (M16, EN)** — format `.caelopkg`, model bezpieczeństwa (zgoda, integralność sha256, brak auto-uruchamiania), registry git-based, publikacja, kuracja i zgłaszanie złośliwych pakietów. | ✅ |
| [`guides/registry.example.json`](guides/registry.example.json) | **Przykładowy indeks registry** (M16-3) — wzór pliku do hostowania w repo git, na który wskazuje Marketplace → Browse → Registry URL. | ✅ |

## `plans/` — plany i rozpisy

### Plany nadrzędne (mapa drogowa)

| Dokument | Co zawiera | Status |
|---|---|---|
| [`plans/REBUILD_PLAN.md`](plans/REBUILD_PLAN.md) | Plan przebudowy customtkinter → Electron + Python sidecar: decyzje, architektura, **Fazy 0–8** (datowane statusy) oraz **§13 „Faza 9"** rekonsolidująca stan (moduły, stack, pełna lista endpointów). | Fazy 0–8 ✅ |
| [`plans/PLAN_ROZBUDOWY.md`](plans/PLAN_ROZBUDOWY.md) | **Mapa drogowa „all-in-one hub" (v2)** — rozszerza REBUILD_PLAN od M9: trzy filary (szkielet huba / doskonałość trybów / otwarta platforma), kolejność, ryzyka. Blok „Postęp" = jednolinijkowy status M9–M19. | M9–M19 ✅ |
| [`plans/MODYFIKACJE.md`](plans/MODYFIKACJE.md) | **Żywa specyfikacja** nadbudowy na Fazach 0–8: scalenie Generator+Edit → **Image**, **Video** edit/extend, moduł **Voice** (TTS/STT/realtime), załączniki w Chat/Code, poprawki UI. Tu szukaj kontraktów tych modułów. | ✅ |

### Rundy napraw / hardening

| Dokument | Co zawiera | Status |
|---|---|---|
| [`plans/PLAN_NAPRAWY.md`](plans/PLAN_NAPRAWY.md) | Hardening do jakości produkcyjnej (**runda 1**, M1–M4) — **P0** (bezpieczeństwo agenta) · **P1** (stabilność/dane) · **P2** (front) · **P3** (testy/CI/pakowanie/dok.). Każdy punkt `[x]` + datowana notatka. | ✅ ZREALIZOWANY |
| [`plans/PLAN_NAPRAWY_2.md`](plans/PLAN_NAPRAWY_2.md) | Naprawy/rozwój (**runda 2**, M5–M8) z niezależnego przeglądu — luki rezydualne: kolejka WS agenta (P0-9), metaznaki POSIX (P0-10), env terminala (P0-11), REST fail-open (P1-10), atomic write (P1-11), perystencja rozmów (P2-8), ESLint/testy tras (P3-7…P3-9). | ✅ ZREALIZOWANY (M5–M8) |
| [`plans/PLAN_NAPRAWY_3.md`](plans/PLAN_NAPRAWY_3.md) | Naprawa słabych stron (**runda 3 / M18**) z **analizy SWOT** po M9–M17 — **dług utrzymaniowy, bez P0**: logowanie cichych `except` (P1-15), dekompozycja `state.py` (P2-13), `sandbox: true`/log no-token (P2-14), devDeps→lockfile (P3-10), testy komponentów+E2E (P3-11), cross-platform CI (P3-12), pytest + rozbicie `api_smoke.py` (P3-13), dokumentacja użytkownika (P3-14). | ✅ ZREALIZOWANY (8/8) |

### Rozpisy milestone'ów (hub v2 — M9–M19)

| Dokument | Milestone | Status |
|---|---|---|
| [`plans/PLAN_M9_SZKIELET.md`](plans/PLAN_M9_SZKIELET.md) | **M9** — szkielet huba: magazyn SQLite/FTS5, magistrala kontekstu „send-to", pipeline załączników, projekty, paleta komend. | ✅ |
| [`plans/PLAN_M10_CZAT.md`](plans/PLAN_M10_CZAT.md) | **M10** — czat: Responses API (streaming), live web/X search, wizja, Q&A nad dokumentami, cytowania + licznik kosztów. | ✅ |
| [`plans/PLAN_M11_TWORCZOSC.md`](plans/PLAN_M11_TWORCZOSC.md) | **M11** — twórczość: jednolita kolejka `GenJob` (Image/Video), edycja/warianty, galeria, koszt. | ✅ |
| [`plans/PLAN_M12_GLOS.md`](plans/PLAN_M12_GLOS.md) | **M12** — głos: dyktowanie (STT), pipeline „Talk", realtime „Live", read-aloud (TTS), licznik kosztu audio. | ✅ |
| [`plans/PLAN_M13_AGENT_ZAUFANIE.md`](plans/PLAN_M13_AGENT_ZAUFANIE.md) | **M13** — agent (zaufanie): przeglądalne diffy, 4 tryby (ask/accept-edits/plan/bypass), checkpointy/undo, `CAELO.md`. ⬜ tylko per-hunk (F5). | ✅ |
| [`plans/PLAN_M14_ROZSZERZALNOSC.md`](plans/PLAN_M14_ROZSZERZALNOSC.md) | **M14** — rozszerzalność: klient MCP (stdio), komendy, hooki, skille; moduł Extensions. | ✅ |
| [`plans/PLAN_M15_OSS_CROSSPLATFORM.md`](plans/PLAN_M15_OSS_CROSSPLATFORM.md) | **M15** — OSS + cross-platform: rebranding „Caelo", Apache-2.0/CLA, PTY/tree-kill cross-platform, gitleaks, CI, auto-update, pakowanie mac/Linux. | ✅ |
| [`plans/PLAN_M16_SPOLECZNOSC.md`](plans/PLAN_M16_SPOLECZNOSC.md) | **M16** — społeczność: marketplace `.caelopkg`, bezpieczny import (zgoda + integralność), registry git, szablony projektów. | ✅ |
| [`plans/PLAN_M17_SUBAGENCI.md`](plans/PLAN_M17_SUBAGENCI.md) | **M17** — subagenci/zespoły: `delegate`, role, izolowane worktree, `TeamManager`, merge review. | ✅ |
| [`plans/PLAN_M19_PARYTET_GROK_CLI.md`](plans/PLAN_M19_PARYTET_GROK_CLI.md) | **M19 (analiza)** — parytet z oficjalnym Grok CLI: co adoptujemy, podział na Tier-1/2/3 + spike B0. | analiza |
| [`plans/PLAN_M19_TIER1.md`](plans/PLAN_M19_TIER1.md) | **M19 Tier-1** — §0 `AgentRunner`, B1 headless/CLI, B2 ACP, B3 LSP, B4 reguły glob. | ✅ |
| [`plans/PLAN_M19_TIER2.md`](plans/PLAN_M19_TIER2.md) | **M19 Tier-2** — B5 interop ekosystemu, B6 skille-orkiestratory, B7 sandbox OS, B8 pamięć hybrydowa. | ✅ |
| [`plans/PLAN_M19_TIER3.md`](plans/PLAN_M19_TIER3.md) | **M19 Tier-3** (quick-winy) — B9 effort, B10 eksport-md/auto-compact, B11 persony+I/O, B12 git-worktree, B13 web_fetch, B14 config hierarchiczny. | ✅ |

> **Uwaga:** brak osobnego `PLAN_M18` — runda jakości M18 jest opisana w `plans/PLAN_NAPRAWY_3.md`.
> Weryfikacje **LIVE** zależne od xAI (realny agent, ACP w Zed/Neovim, LSP/embeddings/sandbox, `web_fetch`)
> oraz spike **B0 (`cli-chat-proxy`)** pozostają do potwierdzenia na maszynie użytkownika (sandbox blokuje sieć/exec).

## Jak czytać

1. **Nowy w projekcie?** → [`../README.md`](../README.md) (architektura, moduły, szybki start), potem [`../CLAUDE.md`](../CLAUDE.md) (zasady i pułapki — m.in. dlaczego rdzeń xAI zostaje w korzeniu repo).
2. **Użytkownik — jak korzystać z modułu?** → `guides/USER_GUIDE.md` (krok po kroku, EN).
3. **Deweloper — jaka trasa / endpoint?** → `guides/API.md` (96 REST + 6 WS); kontekst projektowy → `plans/REBUILD_PLAN.md` §13 lub `plans/MODYFIKACJE.md`.
4. **Co już zrobione / gdzie jesteśmy?** → `plans/PLAN_ROZBUDOWY.md` (blok „Postęp") + rozpisy `plans/PLAN_M*.md`.
5. **Stan napraw / co utwardzone?** → `plans/PLAN_NAPRAWY.md` (runda 1 ✅), `plans/PLAN_NAPRAWY_2.md` (runda 2 ✅), `plans/PLAN_NAPRAWY_3.md` (runda 3 / M18 ✅).

## Powiązane README (poza `docs/`)

- [`../caelo_core/README.md`](../caelo_core/README.md) — backend: instalacja venv, **lista endpointów**, self-checki.
- [`../desktop/README.md`](../desktop/README.md) — frontend: skrypty, struktura, wybór interpretera Pythona.

> Legacy customtkinter (dawniej `archive/`) został usunięty z repo (kopia zewnętrzna) — domknięcie Fazy 8.
