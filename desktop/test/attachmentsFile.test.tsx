// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import { fileToAttachment } from '../src/renderer/src/lib/attachments'

// S35-h: fileToAttachment zwraca powód odrzucenia (too-large / binary), by UI mogło
// powiedzieć userowi, czemu plik nie wszedł — zamiast cicho zwrócić null.
describe('fileToAttachment — rozróżnialny wynik (S35-h)', () => {
  it('za duży obraz → {ok:false, reason:too-large}', async () => {
    const f = new File(['x'], 'big.png', { type: 'image/png' })
    Object.defineProperty(f, 'size', { value: 13 * 1024 * 1024 })
    const r = await fileToAttachment(f)
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.reason).toBe('too-large')
      expect(r.name).toBe('big.png')
    }
  })

  it('binarny plik tekstowy (bajt NUL) → {ok:false, reason:binary}', async () => {
    const content = 'ab' + String.fromCharCode(0) + 'cd'
    const r = await fileToAttachment(new File([content], 'bin.dat', { type: 'text/plain' }))
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.reason).toBe('binary')
  })

  it('mały plik tekstowy → {ok:true, att.kind:text}', async () => {
    const r = await fileToAttachment(new File(['hello'], 'a.txt', { type: 'text/plain' }))
    expect(r.ok).toBe(true)
    if (r.ok) expect(r.att.kind).toBe('text')
  })
})
