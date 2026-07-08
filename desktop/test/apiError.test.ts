// Regres „[object Object]": błąd 422 z FastAPI (detail = tablica {loc,msg,type})
// musi renderować się jako czytelny tekst, nie String(obiekt).
import { describe, it, expect } from 'vitest'
import { formatDetail } from '../src/renderer/src/lib/api'

describe('formatDetail', () => {
  it('passes a plain string through', () => {
    expect(formatDetail('image too large (> 9 MB)')).toBe('image too large (> 9 MB)')
  })

  it('flattens a FastAPI validation array (was [object Object])', () => {
    const detail = [
      { loc: ['body', 'images', 0], msg: 'image too large (> 9 MB)', type: 'value_error' }
    ]
    const out = formatDetail(detail)
    expect(out).toContain('image too large (> 9 MB)')
    expect(out).not.toContain('[object Object]')
    expect(out).toContain('images.0')
  })

  it('joins multiple validation errors', () => {
    const out = formatDetail([
      { loc: ['body', 'n'], msg: 'must be <= 10' },
      { loc: ['body', 'prompt'], msg: 'required' }
    ])
    expect(out).toBe('n: must be <= 10; prompt: required')
  })

  it('handles a bare object with msg', () => {
    expect(formatDetail({ msg: 'nope' })).toBe('nope')
  })

  it('never yields [object Object] for an arbitrary object', () => {
    expect(formatDetail({ foo: 1 })).not.toContain('[object Object]')
  })
})
