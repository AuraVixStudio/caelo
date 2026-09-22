// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { usePersistentState } from '../src/renderer/src/lib/usePersistentState'

describe('usePersistentState', () => {
  beforeEach(() => localStorage.clear())

  it('odtwarza ostatnią wartość po odmontowaniu widoku', () => {
    const first = renderHook(() => usePersistentState('caelo.test.preference', 'default'))
    act(() => first.result.current[1]('custom'))
    first.unmount()

    const second = renderHook(() => usePersistentState('caelo.test.preference', 'default'))
    expect(second.result.current[0]).toBe('custom')
  })

  it('ignoruje uszkodzoną lub nieprawidłową zapisaną wartość', () => {
    localStorage.setItem('caelo.test.number', JSON.stringify(-5))
    const { result } = renderHook(() => usePersistentState(
      'caelo.test.number',
      6,
      (value): value is number => typeof value === 'number' && value > 0
    ))

    expect(result.current[0]).toBe(6)
    expect(localStorage.getItem('caelo.test.number')).toBe('6')
  })
})
