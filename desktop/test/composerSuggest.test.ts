import { describe, it, expect } from 'vitest'
import {
  detectSuggest,
  fuzzyFiles,
  applyFileSuggest
} from '../src/renderer/src/lib/composerSuggest'

describe('detectSuggest', () => {
  it('detects a leading slash command being typed', () => {
    expect(detectSuggest('/pl', 3)).toEqual({ kind: 'slash', query: 'pl', start: 0, end: 3 })
    expect(detectSuggest('/', 1)).toEqual({ kind: 'slash', query: '', start: 0, end: 1 })
  })
  it('does not treat a slash followed by a space as a command', () => {
    expect(detectSuggest('/plan now', 9)).toBeNull()
  })
  it('detects an @file token at the caret', () => {
    expect(detectSuggest('see @src/ap', 11)).toEqual({
      kind: 'file',
      query: 'src/ap',
      start: 4,
      end: 11
    })
  })
  it('detects @ at the start of input', () => {
    expect(detectSuggest('@foo', 4)).toEqual({ kind: 'file', query: 'foo', start: 0, end: 4 })
  })
  it('closes the @ token after whitespace', () => {
    expect(detectSuggest('@foo ', 5)).toBeNull()
  })
  it('returns null for plain text', () => {
    expect(detectSuggest('hello world', 11)).toBeNull()
  })
})

describe('fuzzyFiles', () => {
  const files = ['src/app.ts', 'src/components/App.tsx', 'README.md', 'src/lib/api.ts']
  it('ranks basename matches above path matches and shorter paths first', () => {
    const r = fuzzyFiles(files, 'app', 8)
    expect(r[0]).toBe('src/app.ts')
    expect(r).toContain('src/components/App.tsx')
  })
  it('returns the head when the query is empty', () => {
    expect(fuzzyFiles(files, '', 2)).toEqual(['src/app.ts', 'src/components/App.tsx'])
  })
  it('matches on the full path', () => {
    expect(fuzzyFiles(files, 'lib/')).toEqual(['src/lib/api.ts'])
  })
})

describe('applyFileSuggest', () => {
  it('replaces the @token with @path plus a trailing space', () => {
    const text = 'see @src/ap rest'
    const tok = detectSuggest('see @src/ap', 11)!
    const r = applyFileSuggest(text, tok, 'src/app.ts')
    expect(r.text).toBe('see @src/app.ts  rest')
    expect(r.caret).toBe('see @src/app.ts '.length)
  })
})
