// Załączniki do wiadomości (czat + agent Code). Obrazy idą jako multimodalne
// part-y image_url; pliki tekstowe/kodu są wklejane do treści promptu.

import type { ApiChatMessage, ChatAttachment, ChatMessage, ContentPart } from './api'
import { fileToDataUri } from './files'

const MAX_IMAGE_BYTES = 12 * 1024 * 1024 // 12 MB
const MAX_TEXT_BYTES = 256 * 1024 // 256 KB
const MAX_DOCUMENT_BYTES = 32 * 1024 * 1024 // 32 MB (PDF/arkusz → Q&A nad dokumentem, M10-B4)

let counter = 0
function aid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `a${(++counter).toString(36)}`
}

/** Czy plik to dokument do Q&A (PDF / arkusz / dokument biurowy) — wysyłany jako
 *  blok `document` (data-URI), nie wklejany jako tekst (M10-B4/F5). CSV/TXT zostają
 *  tekstem (inline). */
export function isDocumentFile(file: File): boolean {
  const mime = file.type || ''
  if (mime === 'application/pdf') return true
  if (/officedocument|ms-excel|msword|ms-powerpoint|spreadsheet|presentation/i.test(mime)) return true
  return /\.(pdf|docx|xlsx|pptx|doc|xls|ppt)$/i.test(file.name)
}

/**
 * Plik → załącznik. Obraz: data-URI (vision). Dokument (PDF/arkusz): data-URI
 * (Q&A nad dokumentem). Inny: próbujemy odczytać jako tekst (kod/notatki). Zwraca
 * null, gdy plik za duży albo binarny (bajt NUL) i nie jest rozpoznanym dokumentem.
 */
export async function fileToAttachment(file: File): Promise<ChatAttachment | null> {
  if (file.type.startsWith('image/')) {
    if (file.size > MAX_IMAGE_BYTES) return null
    return { id: aid(), name: file.name, kind: 'image', uri: await fileToDataUri(file) }
  }
  if (isDocumentFile(file)) {
    if (file.size > MAX_DOCUMENT_BYTES) return null
    return {
      id: aid(),
      name: file.name,
      kind: 'document',
      uri: await fileToDataUri(file),
      mime: file.type || 'application/octet-stream'
    }
  }
  if (file.size > MAX_TEXT_BYTES) return null
  const text = await file.text()
  if (text.includes(String.fromCharCode(0))) return null // bajt NUL => binarny, pomijamy
  return { id: aid(), name: file.name, kind: 'text', text }
}

/** Doklej treść plików tekstowych do promptu (wspólne dla czatu i agenta). */
export function inlineTextFiles(text: string, attachments: ChatAttachment[]): string {
  let out = text
  for (const a of attachments) {
    if (a.kind === 'text' && a.text) out += `\n\nFile: ${a.name}\n\`\`\`\n${a.text}\n\`\`\``
  }
  return out
}

/** Data-URI obrazów (dla agenta — przekazywane osobno przez WS). */
export function imageUris(attachments: ChatAttachment[]): string[] {
  return attachments.filter((a) => a.kind === 'image' && a.uri).map((a) => a.uri as string)
}

/**
 * Historia czatu → format API. Pliki tekstowe wklejone w treść; obrazy jako
 * part-y image_url (vision), dokumenty jako part-y document (Q&A). Gdy są obrazy
 * lub dokumenty, content staje się listą part-ów.
 */
export function toApiMessages(messages: ChatMessage[]): ApiChatMessage[] {
  return messages.map((m) => {
    const atts = m.attachments || []
    const text = inlineTextFiles(m.content, atts)
    const images = atts.filter((a) => a.kind === 'image' && a.uri)
    const docs = atts.filter((a) => a.kind === 'document' && a.uri)
    if (images.length || docs.length) {
      const parts: ContentPart[] = []
      if (text.trim()) parts.push({ type: 'text', text })
      for (const im of images) parts.push({ type: 'image_url', image_url: { url: im.uri as string } })
      for (const d of docs)
        parts.push({
          type: 'document',
          document: { data: d.uri as string, mime: d.mime || 'application/octet-stream', name: d.name }
        })
      return { role: m.role, content: parts }
    }
    return { role: m.role, content: text }
  })
}
