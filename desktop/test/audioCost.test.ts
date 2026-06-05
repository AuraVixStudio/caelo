// M12-B5/F5: testy czystego licznika kosztu audio (BYO-key) — stawki, akumulacja,
// formatowanie.
import { describe, it, expect } from 'vitest'
import {
  emptyAudioUsage,
  formatAudioUsage,
  recordStt,
  recordTts,
  sttCost,
  ttsCost
} from '../src/renderer/src/lib/audioCost'

describe('audioCost rates', () => {
  it('STT stream costs twice the batch rate per hour', () => {
    expect(sttCost(3600, false)).toBeCloseTo(0.1, 6)
    expect(sttCost(3600, true)).toBeCloseTo(0.2, 6)
  })

  it('TTS cost scales with characters and clamps negatives', () => {
    expect(ttsCost(1000)).toBeCloseTo(0.015, 6)
    expect(ttsCost(2000)).toBeCloseTo(0.03, 6)
    expect(ttsCost(-5)).toBe(0)
    expect(sttCost(-5)).toBe(0)
  })
})

describe('audioCost accumulation', () => {
  it('records STT seconds and TTS chars, summing cost', () => {
    let u = emptyAudioUsage()
    u = recordStt(u, { seconds: 30, streaming: true }) // 30s * 0.2/3600
    u = recordTts(u, { chars: 1000 }) // 0.015
    expect(u.sttSeconds).toBe(30)
    expect(u.ttsChars).toBe(1000)
    expect(u.cost).toBeCloseTo((0.2 * 30) / 3600 + 0.015, 6)
  })

  it('prefers an explicit backend cost over the local estimate', () => {
    let u = emptyAudioUsage()
    u = recordTts(u, { chars: 500, cost: 0.99 })
    expect(u.cost).toBe(0.99)
    u = recordStt(u, { seconds: 10, cost: 0.5 })
    expect(u.cost).toBeCloseTo(1.49, 6)
  })

  it('is immutable (returns a new object)', () => {
    const u0 = emptyAudioUsage()
    const u1 = recordTts(u0, { chars: 100 })
    expect(u1).not.toBe(u0)
    expect(u0.ttsChars).toBe(0)
  })
})

describe('formatAudioUsage', () => {
  it('is empty for zero usage', () => {
    expect(formatAudioUsage(emptyAudioUsage())).toBe('')
  })

  it('formats minutes/seconds, chars and cost', () => {
    const u = { sttSeconds: 80, ttsChars: 340, cost: 0.0123 }
    const label = formatAudioUsage(u)
    expect(label).toContain('STT 1m 20s')
    expect(label).toContain('TTS 340 chars')
    expect(label).toContain('~$0.0123')
  })

  it('omits sub-minute STT minutes and shows only present parts', () => {
    expect(formatAudioUsage({ sttSeconds: 0, ttsChars: 50, cost: 0 })).toBe('TTS 50 chars')
    expect(formatAudioUsage({ sttSeconds: 45, ttsChars: 0, cost: 0 })).toBe('STT 45s')
  })
})
