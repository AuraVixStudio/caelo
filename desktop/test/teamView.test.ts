// M17-F1/F2/F5: testy czystych utili widoku zespołu (drzewo subagentów, atrybucja
// zatwierdzeń, formatowanie kosztu/osi czasu). Bez Reacta → czysta logika.
import { describe, it, expect } from 'vitest'
import {
  addApproval,
  applyEvent,
  applyStatus,
  clearApproval,
  formatTokens,
  hasActive,
  orderedNodes,
  statusTone,
  teamCostBadge,
  timeline,
  type SubAgentMap
} from '../src/renderer/src/lib/teamView'
import type { SubagentStatus } from '../src/renderer/src/lib/agentClient'
import type { TeamReport, TeamTotals } from '../src/renderer/src/lib/api'

function status(p: Partial<SubagentStatus> & { agent_id: string }): SubagentStatus {
  return {
    role: 'researcher',
    task: 't',
    status: 'running',
    summary: '',
    merge_id: null,
    files_changed: 0,
    turns: 0,
    tool_calls: 0,
    ...p
  }
}

describe('subagent tree state (F1)', () => {
  it('applyStatus upserts a node and updates status', () => {
    let m: SubAgentMap = {}
    m = applyStatus(m, status({ agent_id: 'sa1', status: 'running' }))
    expect(m.sa1.status).toBe('running')
    m = applyStatus(m, status({ agent_id: 'sa1', status: 'done', summary: 'ok' }))
    expect(m.sa1.status).toBe('done')
    expect(m.sa1.summary).toBe('ok')
  })

  it('applyEvent records text, tool_call, output and tool_result', () => {
    let m: SubAgentMap = applyStatus({}, status({ agent_id: 'sa1' }))
    m = applyEvent(m, 'sa1', 'researcher', 't', { type: 'text', full: 'thinking…' })
    expect(m.sa1.activity).toBe('thinking…')
    m = applyEvent(m, 'sa1', 'researcher', 't', {
      type: 'tool_call',
      id: 'c1',
      name: 'grep',
      args: { pattern: 'x' }
    })
    expect(m.sa1.tools).toHaveLength(1)
    expect(m.sa1.tools[0].status).toBe('pending')
    m = applyEvent(m, 'sa1', 'researcher', 't', { type: 'output', id: 'c1', chunk: 'hit\n' })
    m = applyEvent(m, 'sa1', 'researcher', 't', {
      type: 'tool_result',
      id: 'c1',
      ok: true,
      summary: 'found'
    })
    expect(m.sa1.tools[0].output).toBe('hit\n')
    expect(m.sa1.tools[0].status).toBe('done')
    expect(m.sa1.tools[0].summary).toBe('found')
  })

  it('orderedNodes sorts by numeric agent id', () => {
    let m: SubAgentMap = {}
    m = applyStatus(m, status({ agent_id: 'sa10' }))
    m = applyStatus(m, status({ agent_id: 'sa2' }))
    m = applyStatus(m, status({ agent_id: 'sa1' }))
    expect(orderedNodes(m).map((n) => n.agent_id)).toEqual(['sa1', 'sa2', 'sa10'])
  })

  it('hasActive reflects queued/running nodes', () => {
    let m: SubAgentMap = applyStatus({}, status({ agent_id: 'sa1', status: 'running' }))
    expect(hasActive(m)).toBe(true)
    m = applyStatus(m, status({ agent_id: 'sa1', status: 'done' }))
    expect(hasActive(m)).toBe(false)
  })

  it('immutability: applyStatus returns a new map', () => {
    const m0: SubAgentMap = {}
    const m1 = applyStatus(m0, status({ agent_id: 'sa1' }))
    expect(m1).not.toBe(m0)
    expect(m0.sa1).toBeUndefined()
  })
})

describe('approval attribution (F3)', () => {
  it('addApproval attaches to the right subagent node', () => {
    let m: SubAgentMap = applyStatus({}, status({ agent_id: 'sa1', role: 'tester' }))
    m = addApproval(m, 'sa1:c3', 'run_command', {
      kind: 'command',
      command: 'pytest',
      agent_id: 'sa1',
      role: 'tester',
      task: 'run tests'
    })
    expect(m.sa1.approvals).toHaveLength(1)
    expect(m.sa1.approvals[0].id).toBe('sa1:c3')
  })

  it('addApproval without agent_id is a no-op', () => {
    const m0: SubAgentMap = {}
    const m1 = addApproval(m0, 'c1', 'write_file', { kind: 'diff' })
    expect(m1).toBe(m0)
  })

  it('clearApproval removes by namespaced id', () => {
    let m: SubAgentMap = applyStatus({}, status({ agent_id: 'sa1', role: 'tester' }))
    m = addApproval(m, 'sa1:c3', 'run_command', { agent_id: 'sa1' })
    m = clearApproval(m, 'sa1:c3')
    expect(m.sa1.approvals).toHaveLength(0)
  })
})

describe('cost / timeline formatting (F5)', () => {
  const totals: TeamTotals = {
    subagents: 2,
    turns: 6,
    tool_calls: 4,
    input_tokens: 1200,
    output_tokens: 300,
    merges: 1,
    est_usd: 0
  }

  it('formatTokens abbreviates thousands/millions', () => {
    expect(formatTokens(500)).toBe('500')
    expect(formatTokens(1500)).toBe('1.5k')
    expect(formatTokens(2_000_000)).toBe('2.0M')
  })

  it('teamCostBadge summarizes agents/turns/tools/tokens', () => {
    const badge = teamCostBadge(totals)
    expect(badge).toContain('2 agents')
    expect(badge).toContain('6 turns')
    expect(badge).toContain('4 tools')
    expect(badge).toContain('1.5k tok')
  })

  it('teamCostBadge omits cost when est_usd is 0', () => {
    expect(teamCostBadge(totals)).not.toContain('$')
  })

  it('timeline maps subagent reports to rows', () => {
    const report: TeamReport = {
      run: 1,
      subagents: [
        {
          agent_id: 'sa1',
          role: 'researcher',
          task: 't',
          status: 'done',
          summary: '',
          error: '',
          turns: 2,
          tool_calls: 1,
          input_tokens: 10,
          output_tokens: 5,
          est_usd: 0,
          duration: 1.5,
          merge_id: null,
          files_changed: 0
        }
      ],
      totals,
      errors: [],
      created_at: 0
    }
    const rows = timeline(report)
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ role: 'researcher', status: 'done', duration: 1.5, tokens: 15 })
  })

  it('statusTone maps statuses to tones', () => {
    expect(statusTone('done')).toBe('ok')
    expect(statusTone('failed')).toBe('error')
    expect(statusTone('cancelled')).toBe('warn')
    expect(statusTone('running')).toBe('active')
  })
})
