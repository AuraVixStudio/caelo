// P3-9: testy czystej funkcji tytułowania rozmowy (jak w legacy ChatStore).
import { describe, it, expect } from 'vitest'
import { titleFromText } from '../src/renderer/src/lib/storage'

describe('titleFromText', () => {
  it('falls back to "New chat" for empty/whitespace input', () => {
    expect(titleFromText('')).toBe('New chat')
    expect(titleFromText('   \n\t ')).toBe('New chat')
  })

  it('collapses internal whitespace runs to single spaces', () => {
    expect(titleFromText('hello   world\n\ttabs')).toBe('hello world tabs')
  })

  it('truncates long text to 34 chars + ellipsis', () => {
    const t = titleFromText('a'.repeat(50))
    expect(t.endsWith('…')).toBe(true)
    expect(t.length).toBe(35) // 34 znaki + 1 znak wielokropka
  })

  it('keeps short text as-is', () => {
    expect(titleFromText('short title')).toBe('short title')
  })
})
