// M9-F1/F3: testy czystych utili kręgosłupa huba — budowa zapytania historii,
// mapowanie trybu→moduł i tytuł zdarzenia. Bez DOM (vitest node env).
import { describe, it, expect } from 'vitest'
import {
  buildHistoryQuery,
  eventTitle,
  modeToModule,
  modeTone
} from '../src/renderer/src/lib/hubQuery'

describe('buildHistoryQuery', () => {
  it('always sets a limit', () => {
    expect(buildHistoryQuery({ q: '', mode: 'all' }).limit).toBe(100)
    expect(buildHistoryQuery({ q: '', mode: 'all' }, 25).limit).toBe(25)
  })

  it('trims q and drops empty/whitespace', () => {
    expect(buildHistoryQuery({ q: '  cyberpunk  ', mode: 'all' }).q).toBe('cyberpunk')
    expect(buildHistoryQuery({ q: '   ', mode: 'all' }).q).toBeUndefined()
  })

  it("drops 'all' and empty mode, keeps a real mode", () => {
    expect(buildHistoryQuery({ q: '', mode: 'all' }).mode).toBeUndefined()
    expect(buildHistoryQuery({ q: '', mode: '' }).mode).toBeUndefined()
    expect(buildHistoryQuery({ q: '', mode: 'image' }).mode).toBe('image')
  })

  it('includes project_id only when truthy', () => {
    expect(buildHistoryQuery({ q: '', mode: 'all', projectId: 'p1' }).project_id).toBe('p1')
    expect(buildHistoryQuery({ q: '', mode: 'all', projectId: null }).project_id).toBeUndefined()
    expect(buildHistoryQuery({ q: '', mode: 'all' }).project_id).toBeUndefined()
  })
})

describe('modeToModule', () => {
  it('maps known modes to their module', () => {
    expect(modeToModule('chat')).toBe('Chat')
    expect(modeToModule('image')).toBe('Image')
    expect(modeToModule('video')).toBe('Video')
    expect(modeToModule('voice')).toBe('Voice')
    expect(modeToModule('code')).toBe('Code')
  })

  it('returns null for unknown modes', () => {
    expect(modeToModule('weird')).toBeNull()
    expect(modeToModule('')).toBeNull()
  })
})

describe('modeTone', () => {
  it('gives each mode a tone and falls back to neutral', () => {
    expect(modeTone('image')).toBe('success')
    expect(modeTone('chat')).toBe('info')
    expect(modeTone('unknown')).toBe('neutral')
  })
})

describe('eventTitle', () => {
  it('uses text when present, else a mode fallback', () => {
    expect(eventTitle({ text: 'hello world', mode: 'chat' })).toBe('hello world')
    expect(eventTitle({ text: '   ', mode: 'video' })).toBe('(video)')
    expect(eventTitle({ text: '', mode: 'image' })).toBe('(image)')
  })
})
