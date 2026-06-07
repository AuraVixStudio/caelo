// Utrwalanie rozmów czatu po stronie frontendu (localStorage).
// Faza 2: backend ChatStore nie jest jeszcze wystawiony przez REST — rozmowami
// zarządza frontend i wysyła pełną historię wiadomości do WS /chat/stream.

import type { ChatMessage } from './api'

export interface Conversation {
  id: string
  title: string
  created: number
  /** M22: projekt czatu, do którego należy rozmowa. Brak/undefined = bez projektu
   *  (widoczna pod „All projects"). Stare rozmowy (przed M22) nie mają tego pola. */
  project_id?: string | null
  messages: ChatMessage[]
}

const KEY = 'caelo.chat.conversations.v1'
const ACTIVE_KEY = 'caelo.chat.active.v1'

export function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) return parsed
    }
  } catch {
    /* ignore */
  }
  return []
}

/** P1-7: nie utrwalaj base64 załączników (obraz `uri` / tekst pliku `text`) —
 *  to one wysadzają limit ~5 MB localStorage. Zostaje metadana (id/name/kind),
 *  więc historia jest lekka; podgląd obrazu z poprzedniej sesji nie wraca. */
function stripForStorage(conversations: Conversation[]): Conversation[] {
  return conversations.map((c) => ({
    ...c,
    messages: c.messages.map((m) =>
      m.attachments?.length
        ? { ...m, attachments: m.attachments.map((a) => ({ id: a.id, name: a.name, kind: a.kind })) }
        : m
    )
  }))
}

/** Zwraca true przy sukcesie; false (np. QuotaExceededError) — caller pokazuje błąd. */
export function saveConversations(conversations: Conversation[]): boolean {
  try {
    localStorage.setItem(KEY, JSON.stringify(stripForStorage(conversations)))
    return true
  } catch (e) {
    // P1-7: nie połykaj po cichu — quota/utrata danych musi być widoczna.
    console.error('Failed to persist conversations (localStorage quota?):', e)
    return false
  }
}

export function loadActiveId(): string | null {
  return localStorage.getItem(ACTIVE_KEY)
}

export function saveActiveId(id: string): void {
  try {
    localStorage.setItem(ACTIVE_KEY, id)
  } catch {
    /* ignore */
  }
}

function uid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return 'c_' + Math.floor(performance.now()).toString(36) + Math.floor(performance.now() * 7).toString(36)
}

export function newConversation(projectId?: string | null): Conversation {
  return { id: uid(), title: 'New chat', created: Date.now(), project_id: projectId ?? null, messages: [] }
}

/** M22: rozmowy należące do projektu czatu. `projectId === null` → „All projects"
 *  (cała lista). Inaczej tylko rozmowy z `project_id === projectId`. CZYSTA funkcja. */
export function conversationsForProject(
  convos: Conversation[],
  projectId: string | null
): Conversation[] {
  if (!projectId) return convos
  return convos.filter((c) => c.project_id === projectId)
}

/** Tytuł rozmowy z pierwszej wiadomości użytkownika (jak w legacy ChatStore). */
export function titleFromText(text: string): string {
  const t = (text || '').trim().replace(/\s+/g, ' ')
  if (!t) return 'New chat'
  return t.length > 34 ? t.slice(0, 34) + '…' : t
}
