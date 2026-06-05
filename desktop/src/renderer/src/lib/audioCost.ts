// M12-B5/F5: licznik kosztu audio (BYO-key) — czysty model + formater (testowalne).
// Akumuluje sekundy STT (batch/stream), znaki TTS i koszt USD. Backend zwraca koszt
// dla STT batch (z `duration`) i TTS; koszt STT-stream renderer liczy z sekund
// mikrofonu (stawki mirrorowane z config.py w AUDIO_COST).

import { AUDIO_COST } from './constants'

export interface AudioUsage {
  sttSeconds: number // łączny czas STT (batch + stream)
  ttsChars: number // łączne znaki TTS
  cost: number // narastający koszt (USD, best-effort)
}

export function emptyAudioUsage(): AudioUsage {
  return { sttSeconds: 0, ttsChars: 0, cost: 0 }
}

/** Koszt STT z sekund. `streaming` → stawka na żywo ($0.20/h) vs batch ($0.10/h). */
export function sttCost(seconds: number, streaming = false): number {
  const rate = streaming ? AUDIO_COST.sttPerHourStream : AUDIO_COST.sttPerHourBatch
  return (rate * Math.max(0, seconds)) / 3600
}

/** Koszt TTS z liczby znaków (cena znakowa = strojalny szacunek; znaki dokładne). */
export function ttsCost(chars: number): number {
  return (AUDIO_COST.ttsPer1kChars * Math.max(0, chars)) / 1000
}

/** Dolicz turę STT. `cost` z backendu (batch) lub liczony z sekund (stream). */
export function recordStt(
  u: AudioUsage,
  opts: { seconds: number; streaming?: boolean; cost?: number }
): AudioUsage {
  const sec = Math.max(0, opts.seconds)
  const c = opts.cost != null ? opts.cost : sttCost(sec, opts.streaming)
  return { ...u, sttSeconds: u.sttSeconds + sec, cost: u.cost + Math.max(0, c) }
}

/** Dolicz turę TTS. `cost` z backendu lub liczony ze znaków. */
export function recordTts(u: AudioUsage, opts: { chars: number; cost?: number }): AudioUsage {
  const chars = Math.max(0, opts.chars)
  const c = opts.cost != null ? opts.cost : ttsCost(chars)
  return { ...u, ttsChars: u.ttsChars + chars, cost: u.cost + Math.max(0, c) }
}

function fmtDuration(seconds: number): string {
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const rem = s % 60
  return rem ? `${m}m ${rem}s` : `${m}m`
}

/** Etykieta licznika audio, np. "STT 1m 20s · TTS 340 chars · ~$0.0123".
 *  Pusta dla zerowego użycia (badge nic nie renderuje). */
export function formatAudioUsage(u: AudioUsage): string {
  if (u.sttSeconds <= 0 && u.ttsChars <= 0) return ''
  const parts: string[] = []
  if (u.sttSeconds > 0) parts.push(`STT ${fmtDuration(u.sttSeconds)}`)
  if (u.ttsChars > 0) parts.push(`TTS ${u.ttsChars.toLocaleString()} chars`)
  if (u.cost > 0) parts.push(`~$${u.cost.toFixed(4)}`)
  return parts.join(' · ')
}
