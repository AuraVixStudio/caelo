// M9-F2: test czystej konwersji bloku send-to → załącznik composera.
import { describe, it, expect } from 'vitest'
import { inputBlockToAttachment } from '../src/renderer/src/lib/sendTo'
import type { InputBlock } from '../src/renderer/src/lib/api'

const base = { artifact_id: 'abc123', type: 'image', mode: 'image', mime: 'image/png' }

describe('inputBlockToAttachment', () => {
  it('maps an image block to a vision attachment with a deterministic id', () => {
    const ib: InputBlock = {
      ...base,
      name: 'pic.png',
      block: { type: 'image_url', image_url: { url: 'data:image/png;base64,AAAA' } }
    }
    expect(inputBlockToAttachment(ib)).toEqual({
      id: 'art:abc123',
      name: 'pic.png',
      kind: 'image',
      uri: 'data:image/png;base64,AAAA'
    })
  })

  it('maps a text block to a text attachment', () => {
    const ib: InputBlock = {
      artifact_id: 'doc1',
      type: 'text',
      mode: 'chat',
      mime: 'text/plain',
      name: 'note.txt',
      block: { type: 'text', text: 'hello world' }
    }
    expect(inputBlockToAttachment(ib)).toEqual({
      id: 'art:doc1',
      name: 'note.txt',
      kind: 'text',
      text: 'hello world'
    })
  })

  it('falls back to a generic name and returns null for unsupported (document) blocks', () => {
    const img: InputBlock = {
      ...base,
      name: '',
      block: { type: 'image_url', image_url: { url: 'data:image/png;base64,BB' } }
    }
    expect(inputBlockToAttachment(img)?.name).toBe('image')

    const doc: InputBlock = {
      artifact_id: 'd2',
      type: 'file',
      mode: 'chat',
      mime: 'application/pdf',
      name: 'a.pdf',
      block: { type: 'document', document: { data: 'data:application/pdf;base64,CC', mime: 'application/pdf', name: 'a.pdf' } }
    }
    expect(inputBlockToAttachment(doc)).toBeNull()
  })
})
