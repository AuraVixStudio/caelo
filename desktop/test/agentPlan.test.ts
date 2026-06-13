// Faza-G/TOP3: live checklist agenta — parsowanie ramki `plan` (granica WS) + helper widżetu.
import { describe, it, expect } from 'vitest'
import { parseAgentEvent } from '../src/renderer/src/lib/agentClient'
import { planCounts } from '../src/renderer/src/lib/agentPlan'

describe('TOP3 — parseAgentEvent(plan)', () => {
  it('zachowuje content, klamruje nieznany status do pending, dopełnia brakujący', () => {
    const e = parseAgentEvent({
      type: 'plan',
      items: [
        { content: 'A', status: 'completed' },
        { content: 'B', status: 'in_progress' },
        { content: 'C', status: 'weird' },
        { content: 'D' }
      ]
    })
    expect(e).toEqual({
      type: 'plan',
      items: [
        { content: 'A', status: 'completed' },
        { content: 'B', status: 'in_progress' },
        { content: 'C', status: 'pending' },
        { content: 'D', status: 'pending' }
      ]
    })
  })

  it('pomija pozycje bez treści i toleruje nie-tablicę', () => {
    expect(parseAgentEvent({ type: 'plan', items: [{ status: 'completed' }, { content: 'X' }] })).toEqual({
      type: 'plan',
      items: [{ content: 'X', status: 'pending' }]
    })
    expect(parseAgentEvent({ type: 'plan', items: 'nope' })).toEqual({ type: 'plan', items: [] })
  })
})

describe('TOP3 — planCounts', () => {
  it('liczy total/done/active', () => {
    expect(
      planCounts([
        { content: 'a', status: 'completed' },
        { content: 'b', status: 'in_progress' },
        { content: 'c', status: 'pending' },
        { content: 'd', status: 'completed' }
      ])
    ).toEqual({ total: 4, done: 2, active: 1 })
  })

  it('obsługuje pustą listę', () => {
    expect(planCounts([])).toEqual({ total: 0, done: 0, active: 0 })
  })
})
