// M12-F1/F2: testy czystych utili głosu — wstrzykiwanie dyktowanego tekstu
// (appendDictation) i defensywny parser zdarzeń STT (parseStt).
import { describe, it, expect } from 'vitest'
import { appendDictation } from '../src/renderer/src/lib/useDictation'
import { parseStt } from '../src/renderer/src/lib/converse'

describe('appendDictation (F1: transcript injection)', () => {
  it('fills an empty field without a leading space', () => {
    expect(appendDictation('', 'hello world')).toBe('hello world')
  })

  it('appends after existing text with a single space', () => {
    expect(appendDictation('draft a note', 'about voice')).toBe('draft a note about voice')
  })

  it('trims and collapses whitespace at the seam', () => {
    expect(appendDictation('draft a note   ', '  about voice ')).toBe('draft a note about voice')
  })

  it('is a no-op for blank dictation', () => {
    expect(appendDictation('keep me', '   ')).toBe('keep me')
  })
})

describe('parseStt (F2: streaming STT event shapes)', () => {
  it('reads incremental partials from *.transcript.delta', () => {
    expect(parseStt(JSON.stringify({ type: 'transcript.delta', delta: 'hel' }))).toEqual({
      kind: 'partial',
      text: 'hel'
    })
  })

  it('reads finals from *.transcript.completed', () => {
    expect(
      parseStt(JSON.stringify({ type: 'response.transcript.completed', transcript: 'hello there' }))
    ).toEqual({ kind: 'final', text: 'hello there' })
  })

  it('treats is_final flag as final regardless of type', () => {
    expect(parseStt(JSON.stringify({ type: 'x', text: 'done', is_final: true }))).toEqual({
      kind: 'final',
      text: 'done'
    })
  })

  it('handles a bare {text} partial shape', () => {
    expect(parseStt(JSON.stringify({ text: 'typing' }))).toEqual({ kind: 'partial', text: 'typing' })
  })

  it('ignores errors and unparseable frames', () => {
    expect(parseStt(JSON.stringify({ type: 'error', error: { message: 'bad' } })).kind).toBeNull()
    expect(parseStt('not json').kind).toBeNull()
    expect(parseStt(JSON.stringify({ type: 'session.created' })).kind).toBeNull()
  })
})
