// Czysta konwersja bloku wejściowego send-to bus (M9-B4) → załącznik composera
// (M9-F2). Obraz → załącznik vision (data-URI), text/code → załącznik tekstowy.
// Dokument na razie bez obsługi w composerze (Q&A nad dokumentem to M10). Bez
// React/DOM → testowalne w Vitest.

import type { ChatAttachment, InputBlock } from './api'

/** Zamień gotowy blok wejściowy artefaktu na załącznik wiadomości albo `null`,
 *  gdy typ nie jest jeszcze wspierany jako załącznik (np. document → M10).
 *  `id` jest deterministyczne (`art:<id>`) → naturalny dedup w `useAttachments`. */
export function inputBlockToAttachment(ib: InputBlock): ChatAttachment | null {
  const b = ib.block
  const id = `art:${ib.artifact_id}`
  if (b.type === 'image_url') {
    return { id, name: ib.name || 'image', kind: 'image', uri: b.image_url.url }
  }
  if (b.type === 'text') {
    return { id, name: ib.name || 'text', kind: 'text', text: b.text }
  }
  return null
}
