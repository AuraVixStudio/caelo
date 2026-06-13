// Faza-G/TOP3: czysta logika live checklist agenta (widżet planu). Trzymana osobno od
// AgentPanel (jak teamView/agentTrust) — testowalna bez renderu.
import type { PlanItem } from './agentClient'

export type { PlanItem }

/** Zliczenie pozycji planu wg statusu — nagłówek widżetu („done/total") + odznaki. */
export function planCounts(items: PlanItem[]): { total: number; done: number; active: number } {
  let done = 0
  let active = 0
  for (const it of items) {
    if (it.status === 'completed') done += 1
    else if (it.status === 'in_progress') active += 1
  }
  return { total: items.length, done, active }
}
