// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { ToastContext } from '../src/renderer/src/components/ui/Toast'

// S35-j: odmowa mikrofonu i błąd STT trafiają do wspólnego toastu (były 2× ciche catch).
vi.mock('../src/renderer/src/lib/api', () => ({ speechToText: vi.fn() }))
vi.mock('../src/renderer/src/lib/audio', () => ({
  blobToBase64: vi.fn().mockResolvedValue('b64'),
  MicRecorder: vi.fn()
}))

import { useDictation } from '../src/renderer/src/lib/useDictation'
import { speechToText } from '../src/renderer/src/lib/api'
import { MicRecorder } from '../src/renderer/src/lib/audio'

const push = vi.fn()
const wrapper = ({ children }: { children: ReactNode }) =>
  createElement(ToastContext.Provider, { value: { push } }, children)
const conn = { baseUrl: '', token: '' } as never
const MicMock = MicRecorder as unknown as ReturnType<typeof vi.fn>
const sttMock = speechToText as ReturnType<typeof vi.fn>

describe('useDictation — błędy przez toast (S35-j)', () => {
  beforeEach(() => {
    push.mockClear()
    MicMock.mockReset()
    sttMock.mockReset()
  })

  it('odmowa mikrofonu → toast', async () => {
    MicMock.mockImplementation(() => ({
      start: vi.fn().mockRejectedValue(new Error('denied')),
      cancel: vi.fn()
    }))
    const onText = vi.fn()
    const { result } = renderHook(() => useDictation(conn, onText), { wrapper })
    await act(async () => {
      await result.current.toggle()
    })
    expect(push).toHaveBeenCalledWith(expect.stringMatching(/microphone/i), 'error')
    expect(result.current.recording).toBe(false)
  })

  it('błąd transkrypcji (STT) → toast, onText nie wołany', async () => {
    MicMock.mockImplementation(() => ({
      start: vi.fn().mockResolvedValue(undefined),
      stop: vi.fn().mockResolvedValue({ blob: new Blob(['x']) }),
      cancel: vi.fn()
    }))
    sttMock.mockRejectedValue(new Error('stt down'))
    const onText = vi.fn()
    const { result } = renderHook(() => useDictation(conn, onText), { wrapper })
    await act(async () => {
      await result.current.toggle() // start
    })
    await act(async () => {
      await result.current.toggle() // stop + transcribe (rejects)
    })
    expect(push).toHaveBeenCalledWith(expect.stringMatching(/transcribe/i), 'error')
    expect(onText).not.toHaveBeenCalled()
  })
})
