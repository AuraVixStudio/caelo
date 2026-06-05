// M17-F1/F5: czyste utile widoku zespołu — stan drzewa subagentów (z eventów WS),
// atrybucja zatwierdzeń (F3) i formatowanie kosztu/telemetrii (F5). Bez Reacta → testowalne.

import type { AgentEvent, ApprovalDetail, SubagentStatus } from './agentClient'
import type { TeamReport, TeamTotals } from './api'

/** Pojedyncze wywołanie narzędzia w transkrypcie subagenta. */
export interface SubToolEntry {
  id: string
  name: string
  args: Record<string, unknown>
  status: 'pending' | 'done' | 'error'
  output: string
  summary: string
}

/** Zatwierdzenie oczekujące, przypisane do subagenta (F3). */
export interface SubApproval {
  id: string // znamespace'owany call_id (np. "sa1:call_3")
  name: string
  detail?: ApprovalDetail
}

/** Węzeł subagenta w drzewie zespołu (F1). */
export interface SubAgentNode {
  agent_id: string
  role: string
  task: string
  status: string // queued | running | done | failed | cancelled | timeout
  summary: string
  activity: string // ostatni strumieniowany tekst asystenta
  mergeId: string | null
  filesChanged: number
  turns: number
  toolCalls: number
  tools: SubToolEntry[]
  approvals: SubApproval[]
}

export type SubAgentMap = Record<string, SubAgentNode>

function blankNode(agent_id: string, role: string, task: string): SubAgentNode {
  return {
    agent_id,
    role,
    task,
    status: 'queued',
    summary: '',
    activity: '',
    mergeId: null,
    filesChanged: 0,
    turns: 0,
    toolCalls: 0,
    tools: [],
    approvals: []
  }
}

/** Węzły w kolejności spawnowania (sa1, sa2, … → po numerze, fallback alfabetycznie). */
export function orderedNodes(map: SubAgentMap): SubAgentNode[] {
  const num = (id: string): number => {
    const m = /(\d+)/.exec(id)
    return m ? parseInt(m[1], 10) : 0
  }
  return Object.values(map).sort((a, b) => num(a.agent_id) - num(b.agent_id) || a.agent_id.localeCompare(b.agent_id))
}

/** Czy są jeszcze aktywne (queued/running) subagenty. */
export function hasActive(map: SubAgentMap): boolean {
  return Object.values(map).some((n) => n.status === 'queued' || n.status === 'running')
}

/** Zastosuj ramkę cyklu życia subagenta (status). Zwraca NOWĄ mapę (immutability). */
export function applyStatus(map: SubAgentMap, s: SubagentStatus): SubAgentMap {
  const prev = map[s.agent_id] ?? blankNode(s.agent_id, s.role, s.task)
  return {
    ...map,
    [s.agent_id]: {
      ...prev,
      role: s.role || prev.role,
      task: s.task || prev.task,
      status: s.status,
      summary: s.summary || prev.summary,
      mergeId: s.merge_id ?? prev.mergeId,
      filesChanged: s.files_changed || prev.filesChanged,
      turns: s.turns || prev.turns,
      toolCalls: s.tool_calls || prev.toolCalls
    }
  }
}

/** Zastosuj zagnieżdżoną ramkę subagenta (tekst/narzędzia/wynik). Zwraca NOWĄ mapę. */
export function applyEvent(
  map: SubAgentMap,
  agent_id: string,
  role: string,
  task: string,
  ev: AgentEvent
): SubAgentMap {
  const node = map[agent_id] ?? blankNode(agent_id, role, task)
  let next = node

  switch (ev.type) {
    case 'text':
      next = { ...node, activity: ev.full }
      break
    case 'tool_call':
      next = {
        ...node,
        tools: [
          ...node.tools,
          { id: ev.id, name: ev.name, args: ev.args, status: 'pending', output: '', summary: '' }
        ]
      }
      break
    case 'output':
      next = {
        ...node,
        tools: node.tools.map((t) => (t.id === ev.id ? { ...t, output: t.output + ev.chunk } : t))
      }
      break
    case 'tool_result':
      next = {
        ...node,
        tools: node.tools.map((t) =>
          t.id === ev.id ? { ...t, status: ev.ok ? 'done' : 'error', summary: ev.summary } : t
        )
      }
      break
    case 'assistant_done':
      next = { ...node, activity: ev.content || node.activity }
      break
    default:
      next = node
  }
  return { ...map, [agent_id]: next }
}

/** F3: dorzuć oczekujące zatwierdzenie do węzła subagenta (atrybucja). */
export function addApproval(
  map: SubAgentMap,
  id: string,
  name: string,
  detail: ApprovalDetail | undefined
): SubAgentMap {
  const aid = detail?.agent_id || ''
  if (!aid) return map
  const node = map[aid] ?? blankNode(aid, detail?.role || '', detail?.task || '')
  return { ...map, [aid]: { ...node, approvals: [...node.approvals, { id, name, detail }] } }
}

/** F3: usuń zatwierdzenie po decyzji (po znamespace'owanym id). */
export function clearApproval(map: SubAgentMap, id: string): SubAgentMap {
  const out: SubAgentMap = {}
  for (const [k, n] of Object.entries(map)) {
    out[k] = n.approvals.some((a) => a.id === id)
      ? { ...n, approvals: n.approvals.filter((a) => a.id !== id) }
      : n
  }
  return out
}

// --- formatowanie kosztu / telemetrii (F5) -------------------------------------
export function formatTokens(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  return String(n)
}

/** Krótki badge kosztu zespołu: tury + narzędzia + tokeny (+ kwota, jeśli > 0). */
export function teamCostBadge(t: TeamTotals): string {
  const parts = [`${t.subagents} agents`, `${t.turns} turns`, `${t.tool_calls} tools`]
  const tok = (t.input_tokens || 0) + (t.output_tokens || 0)
  if (tok > 0) parts.push(`${formatTokens(tok)} tok`)
  if (t.est_usd && t.est_usd > 0) parts.push(`$${t.est_usd.toFixed(2)}`)
  return parts.join(' · ')
}

/** Wiersz osi czasu (F5) z raportu — rola, status, czas trwania. */
export interface TimelineRow {
  agent_id: string
  role: string
  status: string
  duration: number
  tokens: number
}

export function timeline(report: TeamReport): TimelineRow[] {
  return (report.subagents || []).map((s) => ({
    agent_id: s.agent_id,
    role: s.role,
    status: s.status,
    duration: s.duration,
    tokens: (s.input_tokens || 0) + (s.output_tokens || 0)
  }))
}

/** Hint tonu statusu (mapowany na klasy w komponencie). */
export function statusTone(status: string): 'ok' | 'warn' | 'error' | 'active' | 'idle' {
  switch (status) {
    case 'done':
      return 'ok'
    case 'failed':
    case 'error':
      return 'error'
    case 'cancelled':
    case 'timeout':
      return 'warn'
    case 'running':
    case 'queued':
      return 'active'
    default:
      return 'idle'
  }
}
