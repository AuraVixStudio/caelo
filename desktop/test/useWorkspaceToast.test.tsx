// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { ToastContext } from '../src/renderer/src/components/ui/Toast'

// S35-e: nieudany Ctrl+S / open / wybór folderu trafia do wspólnego toastu (nie w pustkę).
vi.mock('../src/renderer/src/lib/api', () => ({
  fsGetWorkspace: vi.fn().mockResolvedValue({ path: null }),
  fsRead: vi.fn(),
  fsSetWorkspace: vi.fn(),
  fsWrite: vi.fn(),
  gitStatus: vi.fn().mockResolvedValue({ is_repo: false, branch: '' })
}))

import { useWorkspace } from '../src/renderer/src/lib/useWorkspace'
import { fsRead, fsWrite, fsSetWorkspace } from '../src/renderer/src/lib/api'

const push = vi.fn()
const wrapper = ({ children }: { children: ReactNode }) =>
  createElement(ToastContext.Provider, { value: { push } }, children)
const conn = { baseUrl: '', token: '' } as never

describe('useWorkspace — błędy przez toast (S35-e)', () => {
  beforeEach(() => push.mockClear())

  it('nieudany Ctrl+S (saveActive) → toast z nazwą pliku, zakładka zostaje dirty', async () => {
    ;(fsRead as ReturnType<typeof vi.fn>).mockResolvedValue({ content: 'x' })
    ;(fsWrite as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('disk full'))
    const { result } = renderHook(() => useWorkspace(conn), { wrapper })
    await act(async () => {
      await result.current.openFile('src/a.txt')
    })
    act(() => result.current.changeContent('src/a.txt', 'y'))
    await act(async () => {
      await result.current.saveActive()
    })
    expect(push).toHaveBeenCalledWith(expect.stringContaining('src/a.txt'), 'error')
    expect(result.current.active?.dirty).toBe(true)
  })

  it('nieudany wybór workspace → toast', async () => {
    ;(fsSetWorkspace as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('nope'))
    const { result } = renderHook(() => useWorkspace(conn), { wrapper })
    await act(async () => {
      await result.current.selectWorkspace('/x')
    })
    expect(push).toHaveBeenCalledWith(expect.stringMatching(/workspace folder/i), 'error')
  })
})
