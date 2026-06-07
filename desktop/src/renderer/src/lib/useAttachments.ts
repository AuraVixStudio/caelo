import { useCallback, useState } from 'react'
import { fileToAttachment } from './attachments'
import type { ChatAttachment } from './api'

/**
 * Załączniki wiadomości (P2-3) — identyczny kod `addFiles`/`removeAttachment`
 * powtarzał się w ChatView i AgentPanel. `addFiles` ładuje pliki przez
 * `fileToAttachment` (obrazy → data-URI, tekst → treść) i odsiewa nieobsługiwane.
 * `add` (M9-F2) dokłada gotowy załącznik (np. z magistrali „Send to…") — z dedup
 * po `id`, by ten sam artefakt nie wpadł dwa razy.
 */
export function useAttachments(): {
  attachments: ChatAttachment[]
  addFiles: (files: FileList | File[] | null) => Promise<void>
  add: (att: ChatAttachment) => void
  removeAttachment: (id: string) => void
  clear: () => void
} {
  const [attachments, setAttachments] = useState<ChatAttachment[]>([])

  async function addFiles(files: FileList | File[] | null): Promise<void> {
    if (!files) return
    const loaded = (await Promise.all(Array.from(files).map(fileToAttachment))).filter(
      Boolean
    ) as ChatAttachment[]
    if (loaded.length) setAttachments((prev) => [...prev, ...loaded])
  }

  const add = useCallback((att: ChatAttachment): void => {
    setAttachments((prev) => (prev.some((a) => a.id === att.id) ? prev : [...prev, att]))
  }, [])

  function removeAttachment(id: string): void {
    setAttachments((prev) => prev.filter((a) => a.id !== id))
  }

  return { attachments, addFiles, add, removeAttachment, clear: () => setAttachments([]) }
}
