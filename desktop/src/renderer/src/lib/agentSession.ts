// M21: rekonstrukcja transkryptu panelu agenta z zapisanej historii LLM sesji.
// Surowa historia (role user/assistant/tool) → Entry[] z AgentPanel. Wywołania
// narzędzi stają się zwiniętymi wpisami 'tool' (status 'done'), a wynik z kolejnej
// wiadomości 'tool' (po tool_call_id) trafia do `summary`. Streaming/diffy/checkpointy
// nie są w zapisie — pokazujemy konwersację, nie pełny przebieg na żywo.
//
// Import typu `Entry` jest TYPE-ONLY (kasowany przy buildzie), więc nie tworzy
// cyklu runtime mimo że AgentPanel importuje stąd `historyToEntries`.

import type { Entry } from '../components/code/AgentPanel'
import type { AgentSessionMeta, RawLlmMessage } from './api'

/** Tekst wiadomości: string wprost albo sklejone części tekstowe (multimodal). */
function textOf(content: unknown): string {
  if (typeof content === 'string') return content
  if (Array.isArray(content)) {
    return content
      .map((p) =>
        p && typeof p === 'object' && (p as { type?: string }).type === 'text'
          ? String((p as { text?: string }).text ?? '')
          : ''
      )
      .filter(Boolean)
      .join(' ')
  }
  return ''
}

export function historyToEntries(history: RawLlmMessage[] | undefined | null): Entry[] {
  const entries: Entry[] = []
  let n = 0
  const nextId = (): string => `r${n++}`

  for (const m of history ?? []) {
    if (!m || typeof m !== 'object') continue
    if (m.role === 'user') {
      const text = textOf(m.content)
      if (text) entries.push({ kind: 'user', id: nextId(), text })
    } else if (m.role === 'assistant') {
      const text = textOf(m.content)
      if (text) entries.push({ kind: 'assistant', id: nextId(), text })
      for (const tc of m.tool_calls ?? []) {
        const name = tc.function?.name || 'tool'
        let args: Record<string, unknown> = {}
        try {
          if (tc.function?.arguments) args = JSON.parse(tc.function.arguments)
        } catch {
          args = {}
        }
        entries.push({
          kind: 'tool',
          id: tc.id || nextId(),
          name,
          args,
          status: 'done',
          output: '',
          summary: ''
        })
      }
    } else if (m.role === 'tool') {
      // Dopnij wynik narzędzia do pasującego wpisu (po tool_call_id).
      const tid = m.tool_call_id
      const result = textOf(m.content)
      const target = tid ? entries.find((e) => e.kind === 'tool' && e.id === tid) : undefined
      if (target && target.kind === 'tool') target.summary = result.slice(0, 600)
    }
  }
  return entries
}

/**
 * M21: filtruj listę sesji po zapytaniu tekstowym (case-insensitive). Dopasowanie po
 * tytule, ścieżce katalogu (cwd) i modelu — by szukać i po treści, i po projekcie/folderze.
 * Spacje rozbijają zapytanie na tokeny łączone AND (wszystkie muszą trafić w którekolwiek pole).
 * CZYSTA funkcja (testowalna); puste zapytanie → lista bez zmian.
 */
export function filterSessions(sessions: AgentSessionMeta[], query: string): AgentSessionMeta[] {
  const tokens = query.toLowerCase().split(/\s+/).filter(Boolean)
  if (tokens.length === 0) return sessions
  return sessions.filter((s) => {
    const hay = `${s.title} ${s.cwd || ''} ${s.model || ''}`.toLowerCase()
    return tokens.every((t) => hay.includes(t))
  })
}

/** Normalizuj ścieżkę do porównań: slashe w przód, bez końcowych slashy, lowercase. */
function normPath(p: string): string {
  return p.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
}

/**
 * M21: sesje należące do danego projektu = otwartego FOLDERU (po `cwd`). W tej aplikacji
 * folder roboczy wiąże się 1:1 z projektem (set_workspace → ensure_project_for_root), więc
 * zawężenie po katalogu odpowiada „filtrowi po projekcie" — bez zależności od (bywa
 * nieaktualnego) bieżącego projektu w hubie. Pusty `workspacePath` → lista bez zmian.
 */
export function sessionsForWorkspace(
  sessions: AgentSessionMeta[],
  workspacePath: string | null
): AgentSessionMeta[] {
  if (!workspacePath) return sessions
  const target = normPath(workspacePath)
  return sessions.filter((s) => !!s.cwd && normPath(s.cwd) === target)
}
