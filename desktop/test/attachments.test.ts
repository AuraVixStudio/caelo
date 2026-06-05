// P3-9: testy czystych utili załączników (bez DOM/File). Granica, na której
// historia czatu zamienia się w format API (tekst wklejony, obrazy jako part-y).
import { describe, it, expect } from 'vitest'
import {
  imageUris,
  inlineTextFiles,
  isDocumentFile,
  toApiMessages
} from '../src/renderer/src/lib/attachments'
import type { ChatAttachment, ChatMessage, ContentPart } from '../src/renderer/src/lib/api'

const textAtt = (name: string, text: string): ChatAttachment => ({ id: 'a1', name, kind: 'text', text })
const imgAtt = (uri: string): ChatAttachment => ({ id: 'i1', name: 'img.png', kind: 'image', uri })
const docAtt = (uri: string, name = 'r.pdf', mime = 'application/pdf'): ChatAttachment => ({
  id: 'd1',
  name,
  kind: 'document',
  uri,
  mime
})

describe('inlineTextFiles', () => {
  it('appends text-file content as a fenced block after the prompt', () => {
    const out = inlineTextFiles('hello', [textAtt('a.py', 'print(1)')])
    expect(out.startsWith('hello')).toBe(true)
    expect(out).toContain('File: a.py')
    expect(out).toContain('print(1)')
  })
  it('leaves the prompt unchanged when there are no text attachments', () => {
    expect(inlineTextFiles('hi', [imgAtt('data:image/png;base64,AAAA')])).toBe('hi')
  })
})

describe('imageUris', () => {
  it('returns only image data-URIs', () => {
    const atts = [imgAtt('data:image/png;base64,AAAA'), textAtt('a.txt', 'x')]
    expect(imageUris(atts)).toEqual(['data:image/png;base64,AAAA'])
  })
})

describe('toApiMessages', () => {
  it('inlines text files into plain string content', () => {
    const msgs: ChatMessage[] = [{ role: 'user', content: 'do it', attachments: [textAtt('n.md', 'NOTE')] }]
    const out = toApiMessages(msgs)
    expect(out).toHaveLength(1)
    expect(typeof out[0].content).toBe('string')
    expect(out[0].content as string).toContain('NOTE')
  })

  it('emits multimodal parts (text + image_url) when images are present', () => {
    const msgs: ChatMessage[] = [{ role: 'user', content: 'see', attachments: [imgAtt('data:image/png;base64,AAAA')] }]
    const parts = toApiMessages(msgs)[0].content as ContentPart[]
    expect(Array.isArray(parts)).toBe(true)
    expect(parts.some((p) => p.type === 'text' && p.text === 'see')).toBe(true)
    expect(parts.some((p) => p.type === 'image_url' && p.image_url.url.startsWith('data:image'))).toBe(true)
  })

  it('omits the text part when content is blank but images exist', () => {
    const msgs: ChatMessage[] = [{ role: 'user', content: '   ', attachments: [imgAtt('data:image/png;base64,AAAA')] }]
    const parts = toApiMessages(msgs)[0].content as ContentPart[]
    expect(parts.every((p) => p.type !== 'text')).toBe(true)
    expect(parts).toHaveLength(1)
  })

  it('emits a document part for document attachments (M10-B4/F5)', () => {
    const msgs: ChatMessage[] = [
      { role: 'user', content: 'summarize', attachments: [docAtt('data:application/pdf;base64,JVBER')] }
    ]
    const parts = toApiMessages(msgs)[0].content as ContentPart[]
    expect(parts.some((p) => p.type === 'text' && p.text === 'summarize')).toBe(true)
    const doc = parts.find((p) => p.type === 'document')
    expect(doc).toEqual({
      type: 'document',
      document: { data: 'data:application/pdf;base64,JVBER', mime: 'application/pdf', name: 'r.pdf' }
    })
  })
})

describe('isDocumentFile', () => {
  const f = (name: string, type = ''): File => ({ name, type }) as File
  it('recognizes pdf/office docs by mime or extension', () => {
    expect(isDocumentFile(f('a.pdf', 'application/pdf'))).toBe(true)
    expect(isDocumentFile(f('b.xlsx', ''))).toBe(true)
    expect(isDocumentFile(f('c.docx', ''))).toBe(true)
    expect(
      isDocumentFile(
        f('d.unknown', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
      )
    ).toBe(true)
  })
  it('leaves images, text and csv as non-documents', () => {
    expect(isDocumentFile(f('p.png', 'image/png'))).toBe(false)
    expect(isDocumentFile(f('n.txt', 'text/plain'))).toBe(false)
    expect(isDocumentFile(f('s.csv', 'text/csv'))).toBe(false)
  })
})
