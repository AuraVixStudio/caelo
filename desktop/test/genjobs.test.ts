// M11-F5/F6: testy czystych utili kolejki generacji (status, koszt, reduktory).
import { describe, it, expect } from 'vitest'
import {
  activeCount,
  formatCost,
  isActive,
  isTerminal,
  jobPrompt,
  mergeJob,
  mergeJobs,
  opLabel,
  statusTone,
  sumCost
} from '../src/renderer/src/lib/genjobs'
import type { GenJob } from '../src/renderer/src/lib/api'

function job(over: Partial<GenJob>): GenJob {
  return {
    id: 'j1',
    kind: 'image',
    op: 'text2img',
    params: {},
    status: 'queued',
    artifact_ids: [],
    error: '',
    cost: 0,
    project_id: null,
    created_at: 0,
    updated_at: 0,
    ...over
  }
}

describe('status helpers', () => {
  it('classifies terminal vs active', () => {
    expect(isTerminal('done')).toBe(true)
    expect(isTerminal('failed')).toBe(true)
    expect(isTerminal('cancelled')).toBe(true)
    expect(isTerminal('queued')).toBe(false)
    expect(isActive('queued')).toBe(true)
    expect(isActive('running')).toBe(true)
    expect(isActive('done')).toBe(false)
  })

  it('counts active jobs', () => {
    expect(
      activeCount([job({ status: 'queued' }), job({ status: 'running' }), job({ status: 'done' })])
    ).toBe(2)
  })

  it('maps status to a badge tone', () => {
    expect(statusTone('done')).toBe('success')
    expect(statusTone('failed')).toBe('error')
    expect(statusTone('running')).toBe('accent')
    expect(statusTone('queued')).toBe('warn')
  })

  it('labels ops for the UI', () => {
    expect(opLabel('text2img')).toBe('Generate')
    expect(opLabel('variation')).toBe('Variations')
    expect(opLabel('img2video')).toBe('Image → video')
  })
})

describe('formatCost', () => {
  it('formats normal costs with two decimals', () => {
    expect(formatCost(0.06)).toBe('$0.06')
    expect(formatCost(1)).toBe('$1.00')
  })
  it('uses three decimals for tiny costs', () => {
    expect(formatCost(0.005)).toBe('$0.005')
  })
  it('prefixes ~ when approximate', () => {
    expect(formatCost(0.1, { approx: true })).toBe('~$0.10')
  })
  it('returns empty for zero or negative', () => {
    expect(formatCost(0)).toBe('')
    expect(formatCost(-1)).toBe('')
  })
})

describe('sumCost', () => {
  it('sums only done jobs by default', () => {
    const jobs = [
      job({ id: 'a', status: 'done', cost: 0.06 }),
      job({ id: 'b', status: 'running', cost: 1 }),
      job({ id: 'c', status: 'done', cost: 0.04 })
    ]
    expect(sumCost(jobs)).toBe(0.1)
  })
  it('sums all when onlyDone is false', () => {
    const jobs = [job({ id: 'a', status: 'queued', cost: 0.02 }), job({ id: 'b', status: 'done', cost: 0.02 })]
    expect(sumCost(jobs, { onlyDone: false })).toBe(0.04)
  })
})

describe('jobPrompt', () => {
  it('reads the prompt from params', () => {
    expect(jobPrompt(job({ params: { prompt: 'a cat' } }))).toBe('a cat')
  })
  it('falls back to empty string', () => {
    expect(jobPrompt(job({ params: { n: 2 } }))).toBe('')
  })
})

describe('mergeJob / mergeJobs', () => {
  it('upserts by id and sorts newest-first', () => {
    const list = [job({ id: 'a', created_at: 10 }), job({ id: 'b', created_at: 20 })]
    const out = mergeJob(list, job({ id: 'a', created_at: 30, status: 'done' }))
    expect(out.map((j) => j.id)).toEqual(['a', 'b'])
    expect(out[0].status).toBe('done')
  })

  it('inserts a new job', () => {
    const out = mergeJob([job({ id: 'a', created_at: 5 })], job({ id: 'c', created_at: 99 }))
    expect(out.map((j) => j.id)).toEqual(['c', 'a'])
  })

  it('mergeJobs lets the server list win and keeps local-only jobs', () => {
    const existing = [job({ id: 'a', created_at: 1, status: 'queued' }), job({ id: 'local', created_at: 50, status: 'queued' })]
    const fetched = [job({ id: 'a', created_at: 1, status: 'done' })]
    const out = mergeJobs(existing, fetched)
    expect(out.find((j) => j.id === 'a')?.status).toBe('done') // server wins
    expect(out.find((j) => j.id === 'local')).toBeTruthy() // local-only kept
    expect(out.map((j) => j.id)).toEqual(['local', 'a']) // newest-first
  })
})
