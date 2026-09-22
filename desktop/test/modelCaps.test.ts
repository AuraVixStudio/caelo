// Faza-G: heurystyka wsparcia reasoning_effort per model (wskazówka UI; backend i tak
// gracefully ponawia bez effortu na 4xx). `false` tylko dla pewnych modeli; nieznane → true.
import { describe, it, expect } from 'vitest'
import { modelSupportsEffort, modelSupportsXhighEffort } from '../src/renderer/src/lib/modelCaps'
import { effortOptionsFor } from '../src/renderer/src/components/ui/EffortSelect'

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

  it('grok-4.6 wspiera effort', () => {
    expect(modelSupportsEffort('grok-4.6')).toBe(true)
  })
})

// `xhigh` jest udokumentowany dla grok-4.7/4.6, multi-agent i rodzin OpenAI gpt-5.6/gpt-6;
// przeciwna polityka niż wyżej — pokazujemy tylko tam, gdzie wiemy, że działa (inaczej wybór
// cicho degraduje się do domyślnego).
describe('modelSupportsXhighEffort', () => {
  it('rodziny 4.7/4.6, multi-agent i OpenAI → true', () => {
    expect(modelSupportsXhighEffort('grok-4.7')).toBe(true)
    expect(modelSupportsXhighEffort('grok-4.6')).toBe(true)
    expect(modelSupportsXhighEffort('  GROK-4.6 ')).toBe(true)
    expect(modelSupportsXhighEffort('grok-4.20-multi-agent-0309')).toBe(true)
    expect(modelSupportsXhighEffort('gpt-5.6-terra')).toBe(true)
    expect(modelSupportsXhighEffort('gpt-6-astra')).toBe(true)
  })

  it('starsze/nieznane modele → false', () => {
    for (const m of ['grok-4.5', 'grok-4.3', 'grok-4', 'some-future-grok', '']) {
      expect(modelSupportsXhighEffort(m)).toBe(false)
    }
  })
})

describe('effortOptionsFor', () => {
  it('pokazuje xHigh tylko dla modeli, które je dokumentują', () => {
    expect(effortOptionsFor('grok-4.7').map((o) => o.id)).toContain('xhigh')
    expect(effortOptionsFor('grok-4.6').map((o) => o.id)).toContain('xhigh')
    expect(effortOptionsFor('grok-4.20-multi-agent-0309').map((o) => o.id)).toContain('xhigh')
    expect(effortOptionsFor('grok-4.5').map((o) => o.id)).not.toContain('xhigh')
    expect(effortOptionsFor(undefined).map((o) => o.id)).not.toContain('xhigh')
  })

  it('Auto/Low/Medium/High są zawsze dostępne', () => {
    expect(effortOptionsFor('grok-4.5').map((o) => o.id)).toEqual(['', 'low', 'medium', 'high'])
  })
})
