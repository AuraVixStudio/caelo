// M13-F2/F3: testy czystych utili „zaufania" agenta (plan state machine, undo, checkpointy).
import { describe, it, expect } from 'vitest'
import {
  planReducer,
  canApproveRun,
  checkpointTitle,
  checkpointSubtitle,
  undoSummary,
  partialUndoNote,
  AGENT_MODES,
  modeInfo,
  nextMode,
  modeBanner,
  type PlanPhase
} from '../src/renderer/src/lib/agentTrust'
import type { CheckpointInfo, UndoResp } from '../src/renderer/src/lib/api'

describe('planReducer (plan → review → execute)', () => {
  it('plan send goes to planning, then review on done', () => {
    let p: PlanPhase = 'idle'
    p = planReducer(p, { type: 'send', plan: true })
    expect(p).toBe('planning')
    p = planReducer(p, { type: 'done' })
    expect(p).toBe('review')
  })

  it('approveRun moves review → executing, then done → idle', () => {
    let p: PlanPhase = 'review'
    p = planReducer(p, { type: 'approveRun' })
    expect(p).toBe('executing')
    p = planReducer(p, { type: 'done' })
    expect(p).toBe('idle')
  })

  it('a non-plan send goes straight to executing (no review)', () => {
    let p: PlanPhase = 'idle'
    p = planReducer(p, { type: 'send', plan: false })
    expect(p).toBe('executing')
    p = planReducer(p, { type: 'done' })
    expect(p).toBe('idle')
  })

  it('approveRun is a no-op outside review', () => {
    expect(planReducer('idle', { type: 'approveRun' })).toBe('idle')
    expect(planReducer('planning', { type: 'approveRun' })).toBe('planning')
  })

  it('canApproveRun only in review and not busy', () => {
    expect(canApproveRun('review', false)).toBe(true)
    expect(canApproveRun('review', true)).toBe(false)
    expect(canApproveRun('planning', false)).toBe(false)
  })
})

describe('checkpoint labels', () => {
  const base: CheckpointInfo = {
    id: 'abc123',
    label: 'fix the login bug',
    created_at: 1000,
    files: 2,
    has_command: false
  }

  it('uses the label as title', () => {
    expect(checkpointTitle(base)).toBe('fix the login bug')
  })

  it('falls back to a generic title when label is empty', () => {
    expect(checkpointTitle({ ...base, label: '' })).toBe('Checkpoint')
  })

  it('truncates very long labels', () => {
    const long = 'x'.repeat(100)
    expect(checkpointTitle({ ...base, label: long }).endsWith('…')).toBe(true)
  })

  it('subtitle shows file count and command flag', () => {
    expect(checkpointSubtitle(base)).toBe('2 files')
    expect(checkpointSubtitle({ ...base, files: 1 })).toBe('1 file')
    expect(checkpointSubtitle({ ...base, has_command: true })).toBe('2 files · ran command')
  })
})

describe('undoSummary / partialUndoNote', () => {
  const r: UndoResp = {
    ok: true,
    restored: ['a.txt', 'b.txt'],
    deleted: ['c.txt'],
    missing: [],
    partial: false,
    checkpoints_undone: 1
  }

  it('summarizes restored/removed counts', () => {
    expect(undoSummary(r)).toBe('Undid 1 checkpoint — restored 2, removed 1.')
  })

  it('handles nothing-to-undo', () => {
    expect(undoSummary({ ...r, checkpoints_undone: 0 })).toBe('Nothing to undo.')
  })

  it('pluralizes checkpoints and reports skipped', () => {
    expect(undoSummary({ ...r, checkpoints_undone: 2, missing: ['x'] })).toBe(
      'Undid 2 checkpoints — restored 2, removed 1, 1 skipped.'
    )
  })

  it('partial note appears only when partial', () => {
    expect(partialUndoNote(false)).toBeNull()
    expect(partialUndoNote(true)).toContain('partial')
  })
})

describe('agent modes', () => {
  it('exposes the four Claude-Code-style modes', () => {
    expect(AGENT_MODES.map((m) => m.id)).toEqual(['ask', 'accept-edits', 'plan', 'bypass'])
  })

  it('modeInfo resolves and falls back to ask', () => {
    expect(modeInfo('plan').label).toBe('Plan mode')
    // @ts-expect-error invalid id falls back
    expect(modeInfo('nope').id).toBe('ask')
  })

  it('nextMode cycles through all modes', () => {
    expect(nextMode('ask')).toBe('accept-edits')
    expect(nextMode('accept-edits')).toBe('plan')
    expect(nextMode('plan')).toBe('bypass')
    expect(nextMode('bypass')).toBe('ask')
  })

  it('modeBanner is null for ask, warn for bypass', () => {
    expect(modeBanner('ask')).toBeNull()
    expect(modeBanner('bypass')?.tone).toBe('warn')
    expect(modeBanner('plan')?.tone).toBe('info')
    expect(modeBanner('accept-edits')?.text).toContain('Accept edits')
  })
})
