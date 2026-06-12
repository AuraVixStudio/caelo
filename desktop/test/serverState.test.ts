import { describe, it, expect } from 'vitest'
import { mergeSettings } from '../src/renderer/src/lib/serverState'

// S35-a: write-through cache scala WSZYSTKIE pola odpowiedzi (nie tylko 4) — inaczej
// effort/search/voice cofały się w UI po remount.
describe('mergeSettings (S35-a)', () => {
  const current = {
    chat_model: 'a',
    code_model: 'b',
    system_prompt: '',
    chat_temperature: 0.7,
    chat_effort: '',
    chat_search_mode: 'off',
    voice: 'eve',
    has_api_key: false
  } as never

  it('scala effort/search/voice, zachowuje resztę', () => {
    const merged = mergeSettings(current, {
      voice: 'fin',
      chat_effort: 'high',
      chat_search_mode: 'on'
    } as never) as Record<string, unknown>
    expect(merged.voice).toBe('fin')
    expect(merged.chat_effort).toBe('high')
    expect(merged.chat_search_mode).toBe('on')
    expect(merged.chat_model).toBe('a')
  })

  it('api_key przełącza has_api_key i NIE trafia do SettingsResp', () => {
    const merged = mergeSettings(current, { api_key: 'sk-x' } as never) as Record<string, unknown>
    expect(merged.has_api_key).toBe(true)
    expect(merged.api_key).toBeUndefined()
  })
})
