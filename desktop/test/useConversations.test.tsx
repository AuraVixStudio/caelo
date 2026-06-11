// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useConversations } from '../src/renderer/src/lib/useConversations'

const KEY = 'caelo.chat.conversations.v1'

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
