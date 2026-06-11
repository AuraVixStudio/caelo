// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { AgentConnection } from '../src/renderer/src/lib/agentClient'

// P1-G: po padzie/restarcie sidecara composer agenta zostawał zablokowany na „Stop",
// bo żadna ramka terminalna nie nadchodziła. AgentPanel resetuje `busy` w onClose — ten
// test pilnuje KONTRAKTU, na którym fix się opiera: onClose odpala na zamknięciu gniazda,
// a onerror funneluje przez close() → onclose → onClose (jeden punkt odzysku).
class FakeWS {
  static last: FakeWS | null = null
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  readyState = 0
  send = vi.fn()
  close = vi.fn(() => {
    this.readyState = 3
    this.onclose?.()
  })
  constructor(public url: string) {
    FakeWS.last = this
  }
}

describe('AgentConnection — onClose funnel (P1-G)', () => {
  let prevWS: unknown
  beforeEach(() => {
    vi.useFakeTimers() // unieruchom auto-reconnect (setTimeout)
    const g = globalThis as unknown as { WebSocket?: unknown }
    prevWS = g.WebSocket
    g.WebSocket = FakeWS as unknown
    FakeWS.last = null
  })
  afterEach(() => {
    ;(globalThis as unknown as { WebSocket?: unknown }).WebSocket = prevWS
    vi.useRealTimers()
  })

  it('zamknięcie gniazda odpala onClose (tam AgentPanel resetuje busy)', () => {
    const onClose = vi.fn()
    const conn = new AgentConnection({ baseUrl: 'http://x', token: 't' }, undefined, onClose)
    FakeWS.last?.onclose?.()
    expect(onClose).toHaveBeenCalledTimes(1)
    conn.close()
  })

  it('onerror funneluje przez close() → onClose (jeden punkt odzysku)', () => {
    const onClose = vi.fn()
    const conn = new AgentConnection({ baseUrl: 'http://x', token: 't' }, undefined, onClose)
    FakeWS.last?.onerror?.()
    expect(FakeWS.last?.close).toHaveBeenCalled() // błąd wymusił close()
    expect(onClose).toHaveBeenCalledTimes(1) // close → onclose → onClose
    conn.close()
  })
})
