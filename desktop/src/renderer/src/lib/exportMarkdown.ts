// M19-B10: export a chat conversation (renderer-side, from localStorage) to Markdown.
// Chats live in the renderer (P2-8: not in the sidecar), so this serializer is the
// chat half of B10 — the hub history + headless sessions are exported backend-side.
import type { Conversation } from './storage'

/** Serialize a conversation to Markdown. Pure (no DOM) — unit-tested. */
export function conversationToMarkdown(conv: Conversation): string {
  const out: string[] = [`# ${conv.title || 'Chat'}`, '']
  if (conv.created) {
    try {
      out.push(`_${new Date(conv.created).toISOString()}_`, '')
    } catch {
      /* ignore bad timestamp */
    }
  }
  for (const m of conv.messages) {
    const text = (m.content || '').trim()
    if (m.role === 'user') {
      out.push('## You', '', text || '(no text)', '')
    } else if (m.role === 'assistant') {
      out.push('## Assistant', '', text || '(no response)', '')
      if (m.citations?.length) {
        out.push('**Sources:**', '')
        for (const c of m.citations) out.push(`- [${c.title || c.url}](${c.url})`)
        out.push('')
      }
    } else {
      out.push(`## ${m.role}`, '', text, '')
    }
  }
  return out.join('\n').trimEnd() + '\n'
}

/** Build a filesystem-safe filename stem from a chat title. */
export function safeFilename(title: string, fallback = 'chat'): string {
  const stem = (title || fallback)
    .trim()
    .replace(/[^\w.-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
  return stem || fallback
}

/** Trigger a browser download of `text` as a file. DOM side-effect (not unit-tested). */
export function downloadText(filename: string, text: string, mime = 'text/markdown;charset=utf-8'): void {
  const blob = new Blob([text], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
