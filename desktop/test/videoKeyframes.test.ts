// Klatki kluczowe xAI 1.5: siatka 1/3 s, ściśle wewnątrz klipu, bez duplikatów.
import { describe, it, expect } from 'vitest'
import {
  formatKeyframeTime,
  keyframeTimes,
  keyframesValid,
  nextKeyframeTime
} from '../src/renderer/src/lib/videoKeyframes'

describe('keyframeTimes', () => {
  it('2-sekundowy klip → 1/3 … 5/3 (bez 0 i bez końca)', () => {
    expect(keyframeTimes(2)).toEqual([1 / 3, 2 / 3, 1, 4 / 3, 5 / 3])
  })
})

describe('nextKeyframeTime', () => {
  it('pierwsza klatka trafia w środek klipu', () => {
    expect(nextKeyframeTime([], 6)).toBe(3)
  })

  it('omija zajęte punkty i zwraca null, gdy siatka jest pełna', () => {
    expect(nextKeyframeTime([3], 6)).toBe(4)
    expect(nextKeyframeTime([1 / 3, 2 / 3], 1)).toBeNull()
  })
})

describe('keyframesValid', () => {
  it('akceptuje punkty siatki wewnątrz klipu', () => {
    expect(keyframesValid([1 / 3, 3], 6)).toBe(true)
  })

  it('odrzuca poza siatką, na krawędzi i duplikaty', () => {
    expect(keyframesValid([0.5], 6)).toBe(false)
    expect(keyframesValid([6], 6)).toBe(false)
    expect(keyframesValid([2, 2], 6)).toBe(false)
  })
})

describe('formatKeyframeTime', () => {
  it('dwa miejsca po przecinku bez zbędnych zer', () => {
    expect(formatKeyframeTime(4 / 3)).toBe('1.33s')
    expect(formatKeyframeTime(3)).toBe('3s')
  })
})
