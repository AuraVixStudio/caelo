// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

// S35-c: dwa szybkie „Read aloud" nie mogą zagrać dwóch audio — epoka unieważnia
// poprzedni in-flight request, ostatni klik wygrywa.
vi.mock('../src/renderer/src/lib/api', () => ({ textToSpeech: vi.fn() }))
vi.mock('../src/renderer/src/lib/audio', () => ({
  playBase64Audio: vi.fn(() => ({ pause: vi.fn(), onended: null as unknown }))
}))

import { useTts } from '../src/renderer/src/lib/useTts'
import { textToSpeech } from '../src/renderer/src/lib/api'
import { playBase64Audio } from '../src/renderer/src/lib/audio'

const ttsMock = textToSpeech as ReturnType<typeof vi.fn>
const playMock = playBase64Audio as ReturnType<typeof vi.fn>
const conn = { baseUrl: '', token: '' } as never

describe('useTts — wyścig dwóch speak (S35-c)', () => {
  beforeEach(() => {
    ttsMock.mockReset()
    playMock.mockClear()
  })

  it('odtwarza tylko najnowsze żądanie (raz)', async () => {
    const resolvers: ((v: { audio_b64: string; mime: string }) => void)[] = []
    ttsMock.mockImplementation(() => new Promise((res) => resolvers.push(res)))
    const { result } = renderHook(() => useTts(conn, 'eve'))

    await act(async () => {
      void result.current.speak(0, 'a') // req0
      void result.current.speak(1, 'b') // req1 unieważnia req0
    })
    expect(resolvers.length).toBe(2)

    await act(async () => {
      resolvers[0]({ audio_b64: 'x', mime: 'audio/mpeg' }) // stary — zignorowany
      resolvers[1]({ audio_b64: 'y', mime: 'audio/mpeg' }) // najnowszy — odtwarza
      await Promise.resolve()
    })
    expect(playMock).toHaveBeenCalledTimes(1)
  })
})
