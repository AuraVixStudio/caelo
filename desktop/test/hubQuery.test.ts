// M9-F1/F3: testy czystych utili kręgosłupa huba — budowa zapytania historii,
// mapowanie trybu→moduł i tytuł zdarzenia. Bez DOM (vitest node env).
import { describe, it, expect } from 'vitest'
import {
  basename,
  buildHistoryQuery,
  eventTitle,
  isImageEvent,
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

describe('basename', () => {
  it('returns the last path segment for posix and windows paths', () => {
    expect(basename('/home/user/my-project')).toBe('my-project')
    expect(basename('C:\\Users\\me\\repo')).toBe('repo')
    expect(basename('G:/Projekty/grok_desktop_app')).toBe('grok_desktop_app')
  })

  it('handles trailing separators and bare names', () => {
    expect(basename('/home/user/proj/')).toBe('proj')
    expect(basename('C:\\Users\\me\\repo\\')).toBe('repo')
    expect(basename('solo')).toBe('solo')
  })
})

describe('isImageEvent', () => {
  it('is true only for image-mode events with an artifact', () => {
    expect(isImageEvent({ mode: 'image', artifact_id: 'a1' })).toBe(true)
    expect(isImageEvent({ mode: 'image', artifact_id: null })).toBe(false)
    expect(isImageEvent({ mode: 'chat', artifact_id: 'a1' })).toBe(false)
    expect(isImageEvent({ mode: 'video', artifact_id: 'a1' })).toBe(false)
  })
})
