// M13: czyste utile „zaufania" agenta — maszyna stanów trybu planowania (F2),
// podsumowanie undo i etykiety checkpointów (F3). Bez Reacta → łatwe do testów.

import type { CheckpointInfo, UndoResp } from './api'

/** Tryby agenta (jak „Mode" w Claude Code) — sterują bramką zatwierdzania. */
export type AgentMode = 'ask' | 'accept-edits' | 'plan' | 'bypass'

export interface AgentModeInfo {
  id: AgentMode
  label: string
  short: string
  desc: string
}

/** Lista trybów w kolejności prezentacji (i cyklowania Shift+Tab / klawisze 1-4). */
export const AGENT_MODES: AgentModeInfo[] = [
  { id: 'ask', label: 'Ask permissions', short: 'Ask', desc: 'Approve each file change and command.' },
  {
    id: 'accept-edits',
    label: 'Accept edits',
    short: 'Edits',
    desc: 'Auto-apply file edits (undoable); still ask before running commands.'
  },
  { id: 'plan', label: 'Plan mode', short: 'Plan', desc: 'Read-only — propose a plan, change nothing.' },
  {
    id: 'bypass',
    label: 'Bypass permissions',
    short: 'Bypass',
    desc: 'Run every change and command without asking. Use with care.'
  }
]

export function modeInfo(id: AgentMode): AgentModeInfo {
  return AGENT_MODES.find((m) => m.id === id) ?? AGENT_MODES[0]
}

/** Następny tryb w cyklu (do Shift+Tab). */
export function nextMode(id: AgentMode): AgentMode {
  const i = AGENT_MODES.findIndex((m) => m.id === id)
  return AGENT_MODES[(i + 1) % AGENT_MODES.length].id
}

/** Baner stanu trybu nad composerem (null dla domyślnego „ask"). */
export function modeBanner(id: AgentMode): { text: string; tone: 'info' | 'warn' } | null {
  switch (id) {
    case 'plan':
      return {
        text: 'Plan first — the agent only reads and proposes a plan; file changes and commands are disabled until you approve.',
        tone: 'info'
      }
    case 'accept-edits':
      return {
        text: 'Accept edits — file edits apply automatically (undoable via checkpoints); commands still ask.',
        tone: 'info'
      }
    case 'bypass':
      return {
        text: 'Bypass permissions — every change and command runs without asking. Use with care.',
        tone: 'warn'
      }
    default:
      return null
  }
}

/** Faza tury w cyklu plan → review → execute (F2). */
export type PlanPhase = 'idle' | 'planning' | 'review' | 'executing'

export type PlanAction =
  | { type: 'send'; plan: boolean } // wysłano wiadomość (plan lub zwykłą)
  | { type: 'done' } // tura się zakończyła
  | { type: 'approveRun' } // „Approve & run" po planie
  | { type: 'reset' }

/** Czysta tranzycja maszyny stanów planu. */
export function planReducer(phase: PlanPhase, a: PlanAction): PlanPhase {
  switch (a.type) {
    case 'send':
      return a.plan ? 'planning' : 'executing'
    case 'done':
      // plan się skończył → czekamy na akceptację; wykonanie → wracamy do idle
      return phase === 'planning' ? 'review' : 'idle'
    case 'approveRun':
      return phase === 'review' ? 'executing' : phase
    case 'reset':
      return 'idle'
    default:
      return phase
  }
}

/** Czy pokazać przycisk „Approve & run" (po zakończonym planie, gdy nie zajęty). */
export function canApproveRun(phase: PlanPhase, busy: boolean): boolean {
  return phase === 'review' && !busy
}

/** Tytuł checkpointu na osi (etykieta = prompt usera lub fallback). */
export function checkpointTitle(c: CheckpointInfo): string {
  const label = (c.label || '').trim()
  const base = label || 'Checkpoint'
  return base.length > 64 ? base.slice(0, 63) + '…' : base
}

/** Podtytuł: liczba plików + ewentualne „ran command". */
export function checkpointSubtitle(c: CheckpointInfo): string {
  const parts = [`${c.files} file${c.files === 1 ? '' : 's'}`]
  if (c.has_command) parts.push('ran command')
  return parts.join(' · ')
}

/** Krótkie podsumowanie wyniku undo do wyświetlenia użytkownikowi. */
export function undoSummary(r: UndoResp): string {
  if (r.checkpoints_undone === 0) return 'Nothing to undo.'
  const bits: string[] = []
  if (r.restored.length) bits.push(`restored ${r.restored.length}`)
  if (r.deleted.length) bits.push(`removed ${r.deleted.length}`)
  if (r.missing.length) bits.push(`${r.missing.length} skipped`)
  const detail = bits.length ? ` — ${bits.join(', ')}` : ''
  const cps = `${r.checkpoints_undone} checkpoint${r.checkpoints_undone === 1 ? '' : 's'}`
  return `Undid ${cps}${detail}.`
}

/** Baner „partial undo" — zmiany komend nie są cofane. null, gdy niepotrzebny. */
export function partialUndoNote(partial: boolean): string | null {
  return partial
    ? 'Some changes came from a command (e.g. npm install) and were not reverted — undo is partial.'
    : null
}
