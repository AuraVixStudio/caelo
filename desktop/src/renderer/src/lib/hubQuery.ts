// Czyste utile kręgosłupa huba (M9-F1/F3) — budowa zapytania historii, mapowanie
// trybu→moduł, tytuł zdarzenia. Bez React/DOM → testowalne w Vitest (node env).

import type { HistoryQuery } from './api'

/** Moduły huba (zgodne z nawigacją w App.tsx). */
export type HubModule =
  | 'Chat'
  | 'Code'
  | 'Image'
  | 'Video'
  | 'Voice'
  | 'Gallery'
  | 'History'
  | 'Settings'

/** Tryb zdarzenia/artefaktu → moduł UJŚCIA (do skoku z History / Send-to). */
export const MODE_TO_MODULE: Record<string, HubModule> = {
  chat: 'Chat',
  code: 'Code',
  image: 'Image',
  video: 'Video',
  voice: 'Voice'
}

export function modeToModule(mode: string): HubModule | null {
  return MODE_TO_MODULE[mode] ?? null
}

/** Ton Badge per tryb (kolory z components/ui/Badge). */
export type BadgeTone = 'neutral' | 'accent' | 'success' | 'error' | 'warn' | 'info'

export const MODE_TONE: Record<string, BadgeTone> = {
  chat: 'info',
  image: 'success',
  video: 'accent',
  voice: 'warn',
  code: 'neutral'
}

export function modeTone(mode: string): BadgeTone {
  return MODE_TONE[mode] ?? 'neutral'
}

export interface HistoryFilters {
  q: string
  mode: string // '' lub 'all' = wszystkie tryby
  projectId?: string | null
}

/** Znormalizuj stan filtrów UI do zapytania `GET /history` (trim, drop 'all', limit). */
export function buildHistoryQuery(f: HistoryFilters, limit = 100): HistoryQuery {
  const out: HistoryQuery = { limit }
  const q = f.q.trim()
  if (q) out.q = q
  if (f.mode && f.mode !== 'all') out.mode = f.mode
  if (f.projectId) out.project_id = f.projectId
  return out
}

/** Tytuł zdarzenia do listy — treść albo fallback z trybu (puste media bez promptu). */
export function eventTitle(e: { text: string; mode: string }): string {
  const t = (e.text || '').trim()
  return t || `(${e.mode})`
}

/** Ostatni segment ścieżki (nazwa folderu) — do etykiety projektu z `recent_workspaces`.
 *  Obsługuje separatory `/` i `\` (Windows). */
export function basename(path: string): string {
  const trimmed = path.replace(/[\\/]+$/, '')
  const parts = trimmed.split(/[\\/]/)
  return parts[parts.length - 1] || trimmed || path
}

/** Czy zdarzenie ma podglądalny artefakt-obraz (miniatura w History, M9-F4). */
export function isImageEvent(e: { mode: string; artifact_id: string | null }): boolean {
  return e.mode === 'image' && !!e.artifact_id
}
