// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { streamChat } from '../src/renderer/src/lib/api'

// S35-l: Stop w trakcie CONNECTING zamyka gniazdo i NIE startuje tury (wcześniej send
// gubił ramkę, onopen wysyłał 'chat' i bieg trwał mimo Stop).
class FakeWS {
  static last: FakeWS | null = null
  static CONNECTING = 0
  static OPEN = 1
  onopen: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  readyState = 0 // CONNECTING
  send = vi.fn()
  close = vi.fn(() => {
    this.readyState = 3
    this.onclose?.()
  })
  constructor(public url: string) {
    FakeWS.last = this
  }
}

describe('streamChat — Stop podczas łączenia (S35-l)', () => {
  let prev: unknown
  beforeEach(() => {
    const g = globalThis as unknown as { WebSocket?: unknown }
    prev = g.WebSocket
    g.WebSocket = FakeWS as unknown
    FakeWS.last = null
  })
  afterEach(() => {
    ;(globalThis as unknown as { WebSocket?: unknown }).WebSocket = prev
  })

  it('stop() w CONNECTING zamyka socket, a po onopen NIE wysyła ramki chat', () => {
    const handle = streamChat(
      { baseUrl: 'http://x', token: 't' },
      { messages: [] } as never,
      { onDelta: vi.fn(), onDone: vi.fn(), onError: vi.fn() }
    )
    const ws = FakeWS.last as FakeWS
    handle.stop() // wciąż CONNECTING
    expect(ws.close).toHaveBeenCalled()

    ws.readyState = FakeWS.OPEN
    ws.onopen?.() // serwer się połączył mimo Stop
    expect(ws.send).not.toHaveBeenCalledWith(expect.stringContaining('"type":"chat"'))
  })
})
