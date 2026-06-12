import { useCallback, useState } from 'react'
import { fileToAttachment } from './attachments'
import type { ChatAttachment } from './api'
import { useToast } from '../components/ui/Toast'

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
  const toast = useToast() // S35-h: powiedz, czemu pliki zostały pominięte (nie cisza)

  async function addFiles(files: FileList | File[] | null): Promise<void> {
    if (!files) return
    const results = await Promise.all(Array.from(files).map(fileToAttachment))
    const ok = results.flatMap((r) => (r.ok ? [r.att] : []))
    const rejected = results.filter((r) => !r.ok) as { reason: 'too-large' | 'binary'; name: string }[]
    if (ok.length) setAttachments((prev) => [...prev, ...ok])
    if (rejected.length) {
      const reason = (r: { reason: string }): string =>
        r.reason === 'too-large' ? 'too large' : 'not a text file'
      toast.push(
        `Skipped ${rejected.length} file(s): ` +
          rejected.map((r) => `${r.name} (${reason(r)})`).join(', '),
        'error'
      )
    }
  }

  const add = useCallback((att: ChatAttachment): void => {
    setAttachments((prev) => (prev.some((a) => a.id === att.id) ? prev : [...prev, att]))
  }, [])

  function removeAttachment(id: string): void {
    setAttachments((prev) => prev.filter((a) => a.id !== id))
  }

  return { attachments, addFiles, add, removeAttachment, clear: () => setAttachments([]) }
}
