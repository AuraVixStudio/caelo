// Faza-G: heurystyka wsparcia reasoning_effort per model (wskazówka UI; backend i tak
// gracefully ponawia bez effortu na 4xx). `false` tylko dla pewnych modeli; nieznane → true.
import { describe, it, expect } from 'vitest'
import { modelSupportsEffort } from '../src/renderer/src/lib/modelCaps'

describe('modelSupportsEffort', () => {
  it('modele wspierające reasoning_effort → true', () => {
    for (const m of [
      'grok-4.3',
      'grok-4.20-0309-reasoning',
      'grok-4.20-multi-agent-0309',
      'grok-3-mini',
      'grok-3-mini-fast'
    ]) {
      expect(modelSupportsEffort(m)).toBe(true)
    }
  })

  it('modele BEZ wsparcia (xAI zwraca 4xx) → false', () => {
    for (const m of [
      'grok-4',
      'grok-4-fast',
      'grok-build-0.1',
      'grok-3',
      'grok-4.20-0309-non-reasoning'
    ]) {
      expect(modelSupportsEffort(m)).toBe(false)
    }
  })

  it('nieznany/pusty model → true (brak fałszywych ostrzeżeń)', () => {
    expect(modelSupportsEffort('some-future-grok')).toBe(true)
    expect(modelSupportsEffort('')).toBe(true)
  })

  it('jest niewrażliwa na wielkość liter i białe znaki', () => {
    expect(modelSupportsEffort('  GROK-BUILD-0.1 ')).toBe(false)
    expect(modelSupportsEffort('Grok-4.3')).toBe(true)
  })
})
