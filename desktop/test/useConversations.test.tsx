// @vitest-environment jsdom
import { StrictMode } from 'react'
import { describe, it, expect, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useConversations } from '../src/renderer/src/lib/useConversations'

const KEY = 'caelo.chat.conversations.v1'

// Faza-G (LIVE): flush przy odmontowaniu NIE może nadpisać zapisanych rozmów PUSTĄ listą.
// W dev StrictMode robi mount→unmount→mount: cleanup flusha odpalał się, gdy convosRef
// wciąż = [] (init jeszcze nie wczytał), zapisywał [] i KASOWAŁ historię → po remoncie
// został tylko świeży „New chat". To dokładnie objaw „czat się nie zapisuje / znika po
// zmianie zakładki" (moduł czatu jest lazy i odmontowuje się przy przełączeniu).
describe('useConversations — StrictMode/odmontowanie nie kasuje historii (Faza-G)', () => {
  beforeEach(() => localStorage.clear())

  it('podwójny mount (StrictMode) z zaseedowanym localStorage nie nadpisuje go pustką', () => {
    const seeded = [
      { id: 'seed1', title: 'Kept', created: 1, project_id: null,
        messages: [{ role: 'user', content: 'keep me' }] }
    ]
    localStorage.setItem(KEY, JSON.stringify(seeded))

    const { unmount } = renderHook(() => useConversations(), { wrapper: StrictMode })
    act(() => {
      unmount()
    })

    const parsed = JSON.parse(localStorage.getItem(KEY) as string)
    expect(Array.isArray(parsed)).toBe(true)
    expect(parsed.some((c: { id: string }) => c.id === 'seed1')).toBe(true)
    const kept = parsed.find((c: { id: string }) => c.id === 'seed1')
    expect(kept.messages.some((m: { content?: string }) => m.content === 'keep me')).toBe(true)
  })
})

// P1-I: zapis rozmów był debounce'owany (800 ms), a cleanup robił tylko clearTimeout —
// odmontowanie modułu / zamknięcie apki gubiło ostatnią turę. Flush w cleanup to naprawia.
describe('useConversations — flush przy odmontowaniu (P1-I)', () => {
  beforeEach(() => localStorage.clear())

  it('odmontowanie zapisuje niedopisaną turę bez czekania na debounce', () => {
    const { result, unmount } = renderHook(() => useConversations())

    act(() => {
      result.current.createChat()
    })
    act(() => {
      result.current.patchActive((c) => ({
        ...c,
        messages: [{ role: 'user', content: 'unsaved turn' }]
      }))
    })

    // BEZ upływu 800 ms — odmontuj (jak lazy unmount modułu czatu).
    act(() => {
      unmount()
    })

    const raw = localStorage.getItem(KEY)
    expect(raw).toBeTruthy()
    const parsed = JSON.parse(raw as string)
    const msgs = parsed[0]?.messages || []
    expect(msgs.some((m: { content?: string }) => m.content === 'unsaved turn')).toBe(true)
  })
})

// P1-H: kontrakt warstwy danych, na którym opiera się fix „Retry do złej rozmowy" —
// patchActive ZAWSZE celuje w bieżącą activeId. Po przełączeniu na B żaden zapis nie może
// trafić do A (ChatView dodatkowo zeruje error/lastTurnRef przy zmianie activeId).
describe('useConversations — patchActive celuje w aktywną rozmowę (P1-H)', () => {
  beforeEach(() => localStorage.clear())

  it('po setActiveId(B) patchActive mutuje tylko B, nie A', () => {
    const { result } = renderHook(() => useConversations())

    act(() => {
      result.current.createChat()
    }) // B (na początku listy, aktywne)
    const idB = result.current.activeId
    const idA = result.current.convos.find((c) => c.id !== idB)?.id as string
    expect(idA).toBeTruthy()

    act(() => {
      result.current.setActiveId(idA)
    })
    act(() => {
      result.current.patchActive((c) => ({ ...c, messages: [{ role: 'user', content: 'do-A' }] }))
    })
    act(() => {
      result.current.setActiveId(idB)
    })
    act(() => {
      result.current.patchActive((c) => ({ ...c, messages: [{ role: 'user', content: 'do-B' }] }))
    })

    const A = result.current.convos.find((c) => c.id === idA)
    const B = result.current.convos.find((c) => c.id === idB)
    expect(A?.messages?.[0]?.content).toBe('do-A')
    expect(B?.messages?.[0]?.content).toBe('do-B') // zapis do B nie wyciekł do A
  })
})
