// Faza-G: heurystyka, które modele Grok wspierają parametr `reasoning_effort`.
// To TYLKO wskazówka UI — źródłem prawdy jest API, a backend i tak gracefully ponawia
// żądanie BEZ effortu, gdy serwer je odrzuci (4xx) — patrz `caelo_core/agent/llm.py` i
// `responses_client.py`. Dlatego zwracamy `false` JEDYNIE dla modeli, o których wiemy na
// pewno, że NIE wspierają effortu (xAI zwraca błąd); nowe/nieznane → `true` (brak fałszywych
// ostrzeżeń; realną niezgodność wychwyci fallback backendu).
//
// Wsparcie (docs.x.ai, VI 2026): grok-4.3, grok-4.20-*-reasoning, grok-4.20-multi-agent,
// rodzina grok-3-mini. Brak wsparcia (4xx): grok-4, grok-build-*, grok-3 (nie-mini),
// warianty *-non-reasoning.
export function modelSupportsEffort(model: string): boolean {
  const m = (model || '').toLowerCase().trim()
  if (!m) return true
  if (m.includes('non-reasoning')) return false // np. grok-4.20-0309-non-reasoning
  if (m.startsWith('grok-build')) return false // grok-build-0.1
  if (m === 'grok-4' || m.startsWith('grok-4-')) return false // grok-4 family (NIE grok-4.x)
  if (m.startsWith('grok-3') && !m.includes('mini')) return false // grok-3 (tylko -mini wspiera)
  return true // grok-4.3 / grok-4.20-*-reasoning / multi-agent / grok-3-mini / nieznane
}
