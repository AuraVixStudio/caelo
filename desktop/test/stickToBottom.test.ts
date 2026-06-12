import { describe, it, expect } from 'vitest'
import { isNearBottom } from '../src/renderer/src/lib/useStickToBottom'

// S35-i: auto-scroll tylko gdy user jest blisko dołu — `isNearBottom` to rdzeń strażnika.
describe('isNearBottom (S35-i)', () => {
  it('przy dole → true', () => {
    expect(isNearBottom({ scrollHeight: 1000, scrollTop: 940, clientHeight: 100 })).toBe(true)
  })
  it('przewinięte w górę → false', () => {
    expect(isNearBottom({ scrollHeight: 1000, scrollTop: 200, clientHeight: 100 })).toBe(false)
  })
  it('dokładnie na progu (80) → false (>= threshold)', () => {
    expect(isNearBottom({ scrollHeight: 1000, scrollTop: 820, clientHeight: 100 })).toBe(false)
  })
  it('próg konfigurowalny', () => {
    expect(isNearBottom({ scrollHeight: 1000, scrollTop: 850, clientHeight: 100 }, 60)).toBe(true)
  })
})
