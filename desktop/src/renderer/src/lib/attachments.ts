// Załączniki do wiadomości (czat + agent Code). Obrazy idą jako multimodalne
// part-y image_url; pliki tekstowe/kodu są wklejane do treści promptu.

import type { ApiChatMessage, ChatAttachment, ChatMessage, ContentPart } from './api'
import { fileToDataUri } from './files'

const MAX_IMAGE_BYTES = 12 * 1024 * 1024 // 12 MB
const MAX_TEXT_BYTES = 256 * 1024 // 256 KB

let counter = 0
function aid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `a${(++counter).toString(36)}`
}

/**
 * Plik → załącznik. Obraz: data-URI (vision). Inny: próbujemy odczytać jako
 * tekst (kod/notatki). Zwraca null, gdy plik za duży albo binarny (bajt NUL).
 */
export async function fileToAttachment(file: File): Promise<ChatAttachment | null> {
  if (file.type.startsWith('image/')) {
    if (file.size > MAX_IMAGE_BYTES) return null
    return { id: aid(), name: file.name, kind: 'image', uri: await fileToDataUri(file) }
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
 * part-y image_url (gdy są — content staje się listą part-ów).
 */
export function toApiMessages(messages: ChatMessage[]): ApiChatMessage[] {
  return messages.map((m) => {
    const atts = m.attachments || []
    const text = inlineTextFiles(m.content, atts)
    const images = atts.filter((a) => a.kind === 'image' && a.uri)
    if (images.length) {
      const parts: ContentPart[] = []
      if (text.trim()) parts.push({ type: 'text', text })
      for (const im of images) parts.push({ type: 'image_url', image_url: { url: im.uri as string } })
      return { role: m.role, content: parts }
    }
    return { role: m.role, content: text }
  })
}
