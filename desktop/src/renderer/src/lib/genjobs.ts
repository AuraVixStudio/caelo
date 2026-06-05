// Czyste utile kolejki generacji (M11-F5/F6) — formatowanie kosztu, status zadania,
// reduktory listy. Bez React/DOM → testowalne w Vitest (node env), jak hubQuery.ts.

import type { GenJob, GenJobOp, GenJobStatus } from './api'

export function isTerminal(status: GenJobStatus): boolean {
  return status === 'done' || status === 'failed' || status === 'cancelled'
}

export function isActive(status: GenJobStatus): boolean {
  return status === 'queued' || status === 'running'
}

export function activeCount(jobs: GenJob[]): number {
  return jobs.filter((j) => isActive(j.status)).length
}

/** Czytelna etykieta operacji (do listy/kolejki w UI). */
export function opLabel(op: GenJobOp): string {
  switch (op) {
    case 'text2img':
      return 'Generate'
    case 'edit':
      return 'Edit'
    case 'variation':
      return 'Variations'
    case 'text2video':
      return 'Text → video'
    case 'img2video':
      return 'Image → video'
    default:
      return op
  }
}

/** Krótka etykieta statusu. */
export function statusLabel(status: GenJobStatus): string {
  switch (status) {
    case 'queued':
      return 'Queued'
    case 'running':
      return 'Rendering…'
    case 'done':
      return 'Done'
    case 'failed':
      return 'Failed'
    case 'cancelled':
      return 'Cancelled'
    default:
      return status
  }
}

/** Ton Badge per status (kolory z components/ui/Badge). */
export type CostTone = 'neutral' | 'accent' | 'success' | 'error' | 'warn' | 'info'

export function statusTone(status: GenJobStatus): CostTone {
  switch (status) {
    case 'done':
      return 'success'
    case 'failed':
      return 'error'
    case 'cancelled':
      return 'neutral'
    case 'running':
      return 'accent'
    default:
      return 'warn' // queued
  }
}

/** Sformatuj koszt (USD) do badge'a: `$0.04`, `~$0.10`; 0/ujemny → pusty string. */
export function formatCost(cost: number, opts?: { approx?: boolean }): string {
  if (!cost || cost <= 0) return ''
  const v = cost < 0.01 ? cost.toFixed(3) : cost.toFixed(2)
  return `${opts?.approx ? '~' : ''}$${v}`
}

/** Suma kosztu. Domyślnie tylko zadania `done` (koszt INCURRED, jak backend). */
export function sumCost(jobs: GenJob[], opts?: { onlyDone?: boolean }): number {
  const onlyDone = opts?.onlyDone !== false
  const filt = onlyDone ? jobs.filter((j) => j.status === 'done') : jobs
  const total = filt.reduce((s, j) => s + (j.cost || 0), 0)
  return Math.round(total * 1e4) / 1e4
}

/** Tekst promptu z params (do podglądu w liście). */
export function jobPrompt(job: GenJob): string {
  const p = job.params?.prompt
  return typeof p === 'string' ? p : ''
}

/** Wstaw/zaktualizuj zadanie po id; zwróć listę posortowaną malejąco po created_at. */
export function mergeJob(list: GenJob[], job: GenJob): GenJob[] {
  const without = list.filter((j) => j.id !== job.id)
  return [job, ...without].sort((a, b) => b.created_at - a.created_at)
}

/** Scal świeżo pobraną listę z lokalną (serwer = źródło prawdy, ale zachowaj
 *  optymistyczne zadania jeszcze niezwrócone). Sortowanie: najnowsze pierwsze. */
export function mergeJobs(existing: GenJob[], fetched: GenJob[]): GenJob[] {
  const byId = new Map<string, GenJob>()
  for (const j of existing) byId.set(j.id, j)
  for (const j of fetched) byId.set(j.id, j) // wpisy z serwera nadpisują lokalne
  return [...byId.values()].sort((a, b) => b.created_at - a.created_at)
}
