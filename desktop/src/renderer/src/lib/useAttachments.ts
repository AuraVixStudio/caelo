import { useState } from 'react'
import { fileToAttachment } from './attachments'
import type { ChatAttachment } from './api'

/**
 * Załączniki wiadomości (P2-3) — identyczny kod `addFiles`/`removeAttachment`
 * powtarzał się w ChatView i AgentPanel. `addFiles` ładuje pliki przez
 * `fileToAttachment` (obrazy → data-URI, tekst → treść) i odsiewa nieobsługiwane.
 */
export function useAttachments(): {
  attachments: ChatAttachment[]
  addFiles: (files: FileList | null) => Promise<void>
  removeAttachment: (id: string) => void
  clear: () => void
} {
  const [attachments, setAttachments] = useState<ChatAttachment[]>([])

  async function addFiles(files: FileList | null): Promise<void> {
    if (!files) return
    const loaded = (await Promise.all(Array.from(files).map(fileToAttachment))).filter(
      Boolean
    ) as ChatAttachment[]
    if (loaded.length) setAttachments((prev) => [...prev, ...loaded])
  }

  function removeAttachment(id: string): void {
    setAttachments((prev) => prev.filter((a) => a.id !== id))
  }

  return { attachments, addFiles, removeAttachment, clear: () => setAttachments([]) }
}
