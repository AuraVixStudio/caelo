// M12-F1/F2: testy czystych utili głosu — wstrzykiwanie dyktowanego tekstu
// (appendDictation) i defensywny parser zdarzeń STT (parseStt).
import { describe, it, expect, vi } from 'vitest'
import { appendDictation } from '../src/renderer/src/lib/useDictation'
import { parseStt } from '../src/renderer/src/lib/converse'
import { MicCapture } from '../src/renderer/src/lib/audioStream'

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

// P1-J: szybki toggle Talk/Live (stop() w trakcie await getUserMedia) nie może zostawić
// żywego tracku mikrofonu ani budować grafu audio — wznowiony start() ubija świeży track.
describe('MicCapture stop-during-start race (P1-J)', () => {
  it('stop() during getUserMedia stops the track and builds no AudioContext', async () => {
    let resolveGUM!: (s: unknown) => void
    const gum = new Promise((res) => {
      resolveGUM = res
    })
    const trackStop = vi.fn()
    const fakeStream = { getTracks: () => [{ stop: trackStop }] }
    const ACSpy = vi.fn()

    // vi.stubGlobal radzi sobie z getter-only `navigator` w Node (zwykły przypis pada).
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: () => gum } })
    vi.stubGlobal('window', { AudioContext: ACSpy })
    try {
      const mic = new MicCapture({ sampleRate: 24000, onChunk: () => undefined })
      const p = mic.start()
      mic.stop() // stop ubiega rozwiązanie getUserMedia
      resolveGUM(fakeStream) // track dopiero teraz pozyskany
      const ok = await p
      expect(ok).toBe(false) // start zawrócił
      expect(trackStop).toHaveBeenCalledTimes(1) // świeży track ubity
      expect(ACSpy).not.toHaveBeenCalled() // graf audio NIE zbudowany
    } finally {
      vi.unstubAllGlobals()
    }
  })
})
