# Dokumentacja — Grok Desktop

Indeks dokumentów projektu. Główny opis i szybki start: [`../README.md`](../README.md).
Instrukcje dla asystenta/architektura w pigułce: [`../CLAUDE.md`](../CLAUDE.md).

| Dokument | Co zawiera | Status |
|---|---|---|
| [`REBUILD_PLAN.md`](REBUILD_PLAN.md) | Plan przebudowy customtkinter → Electron + Python sidecar: decyzje, architektura, **Fazy 0–8** (datowane statusy) oraz **§13 „Faza 9"** rekonsolidująca aktualny stan (moduły, stack, pełna lista endpointów). | Fazy 0–8 ✅ |
| [`MODYFIKACJE.md`](MODYFIKACJE.md) | **Żywa specyfikacja** nadbudowy na Fazach 0–8: scalenie Generator+Edit → **Image**, **Video** edit/extend, moduł **Voice** (TTS/STT/realtime), załączniki w Chat/Code, poprawki UI. Tu szukaj kontraktów tych modułów. | ✅ |
| [`PLAN_NAPRAWY.md`](PLAN_NAPRAWY.md) | Plan napraw/hardeningu do jakości produkcyjnej (**runda 1**) — **P0** (bezpieczeństwo agenta) · **P1** (stabilność/dane) · **P2** (jakość/wydajność frontu) · **P3** (testy/CI/pakowanie/dok.). Każdy punkt ma `[x]` + datowaną notatkę. | ✅ ZREALIZOWANY |
| [`PLAN_NAPRAWY_2.md`](PLAN_NAPRAWY_2.md) | Plan napraw/rozwoju (**runda 2**) z niezależnego przeglądu kodu — luki rezydualne nieprzeniesione w rundzie 1: kolejka WS agenta (P0-9), skaner metaznaków na POSIX (P0-10), env terminala (P0-11), REST fail-open (P1-10), wybiórczy atomic write (P1-11), perystencja rozmów (P2-8), brak ESLinta/testów tras (P3-7…P3-9). ID i kamienie (M5–M8) kontynuują rundę 1. | ✅ ZREALIZOWANY (M5–M8) |

## Jak czytać

1. **Nowy w projekcie?** → [`../README.md`](../README.md) (architektura, moduły, szybki start), potem [`../CLAUDE.md`](../CLAUDE.md) (zasady i pułapki — m.in. dlaczego rdzeń xAI zostaje w korzeniu repo).
2. **Co to za moduł / endpoint?** → `REBUILD_PLAN.md` §13 (skrót) lub `MODYFIKACJE.md` (szczegóły media/głos).
3. **Stan napraw / co już utwardzone?** → `PLAN_NAPRAWY.md` (runda 1, zrealizowana), a następne kroki/luki rezydualne → `PLAN_NAPRAWY_2.md` (runda 2, propozycja).

## Powiązane README (poza `docs/`)

- [`../grok_core/README.md`](../grok_core/README.md) — backend: instalacja venv, **lista endpointów**, self-checki.
- [`../desktop/README.md`](../desktop/README.md) — frontend: skrypty, struktura, wybór interpretera Pythona.

> Legacy customtkinter (dawniej `archive/`) został usunięty z repo (kopia zewnętrzna) — domknięcie Fazy 8.
