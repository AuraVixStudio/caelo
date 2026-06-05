// Czysta konwersja bloku wejściowego send-to bus (M9-B4) → załącznik composera
// (M9-F2). Obraz → vision (data-URI), text/code → tekst, dokument → Q&A nad
// dokumentem (M10-B4/F5: data-URI). Bez React/DOM → testowalne w Vitest.

import type { ChatAttachment, InputBlock } from './api'

/** Zamień gotowy blok wejściowy artefaktu na załącznik wiadomości albo `null`,
 *  gdy typ nie jest wspierany jako załącznik. `id` jest deterministyczne
 *  (`art:<id>`) → naturalny dedup w `useAttachments`. */
export function inputBlockToAttachment(ib: InputBlock): ChatAttachment | null {
  const b = ib.block
  const id = `art:${ib.artifact_id}`
  if (b.type === 'image_url') {
    return { id, name: ib.name || 'image', kind: 'image', uri: b.image_url.url }
  }
  if (b.type === 'text') {
    return { id, name: ib.name || 'text', kind: 'text', text: b.text }
  }
  if (b.type === 'document') {
    // M10-F5: dokument z huba (PDF/arkusz) → załącznik Q&A (data-URI), domyka dług
    // M9 („document → załącznik = M10").
    return {
      id,
      name: ib.name || 'document',
      kind: 'document',
      uri: b.document.data,
      mime: b.document.mime
    }
  }
  return null
}
