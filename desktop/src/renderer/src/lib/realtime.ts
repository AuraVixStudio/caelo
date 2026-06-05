// Klient realtime voice (M12-B4). Łączy się z mostem sidecara (/voice/realtime),
// który proxuje do wss://api.x.ai/v1/realtime. Przechwytuje mikrofon jako PCM16
// 24 kHz (wspólny `MicCapture` z audioStream.ts), strumieniuje go
// (input_audio_buffer.append) i odtwarza audio z odpowiedzi
// (response.output_audio.delta). Detekcja tur po stronie serwera (server_vad).
//
// Nazwy zdarzeń trzymają się konwencji OpenAI Realtime, którą odwzorowuje xAI
// (session.update / server_vad / *audio.delta / *audio_transcript.delta) — dokładne
// nazwy potwierdzamy na żywo; obsługujemy warianty z/bez prefiksu "output_".

import { arrayBufferToBase64, base64ToArrayBuffer } from './audio'
import { MicCapture } from './audioStream'
import { voiceRealtimeUrl, type Conn } from './api'

const SAMPLE_RATE = 24000

export interface RealtimeHandlers {
  onStatus?: (status: string) => void
  onUserText?: (text: string) => void // pełna transkrypcja wypowiedzi użytkownika
  onAssistantDelta?: (delta: string) => void // przyrost transkrypcji asystenta
  onAssistantDone?: () => void
  onError?: (error: string) => void
}

export interface RealtimeOptions {
  voice?: string
  instructions?: string
  model?: string
}

interface RealtimeEvent {
  type?: string
  delta?: string
  transcript?: string
  error?: { message?: string }
}

function pcm16ToFloat(buf: ArrayBuffer): Float32Array {
  const even = buf.byteLength - (buf.byteLength % 2)
  const view = new Int16Array(buf.slice(0, even))
  const out = new Float32Array(view.length)
  for (let i = 0; i < view.length; i++) out[i] = view[i] / 0x8000
  return out
}

type AudioCtxCtor = typeof AudioContext

export class RealtimeSession {
  private ws: WebSocket | null = null
  private mic: MicCapture | null = null
  private playCtx: AudioContext | null = null
  private nextTime = 0

  constructor(
    private conn: Conn,
    private opts: RealtimeOptions,
    private handlers: RealtimeHandlers
  ) {}

  start(): void {
    this.handlers.onStatus?.('Connecting…')
    const ws = new WebSocket(voiceRealtimeUrl(this.conn, this.opts.model))
    this.ws = ws
    ws.onopen = () => {
      this.handlers.onStatus?.('Connected')
      this.sendSessionUpdate()
      void this.startMic()
    }
    ws.onmessage = (ev) => this.onMessage(ev.data as string)
    ws.onerror = () => {
      this.handlers.onError?.('WebSocket connection error')
      try {
        ws.close() // P1-5: wymuś onclose + sprzątanie mikrofonu, nie wisij w błędzie
      } catch {
        /* ignore */
      }
    }
    ws.onclose = () => {
      this.handlers.onStatus?.('Disconnected')
      this.stopMic()
    }
  }

  private send(obj: unknown): void {
    try {
      this.ws?.send(JSON.stringify(obj))
    } catch {
      /* ignore */
    }
  }

  private sendSessionUpdate(): void {
    const session: Record<string, unknown> = {
      turn_detection: { type: 'server_vad' },
      input_audio_format: 'pcm16',
      output_audio_format: 'pcm16'
    }
    if (this.opts.voice) session.voice = this.opts.voice
    if (this.opts.instructions?.trim()) session.instructions = this.opts.instructions.trim()
    this.send({ type: 'session.update', session })
  }

  private async startMic(): Promise<void> {
    const mic = new MicCapture({
      sampleRate: SAMPLE_RATE,
      onChunk: (buf) => {
        if (this.ws?.readyState !== WebSocket.OPEN) return
        this.send({ type: 'input_audio_buffer.append', audio: arrayBufferToBase64(buf) })
      },
      onError: (m) => this.handlers.onError?.(m)
    })
    this.mic = mic
    const ok = await mic.start()
    // 'Listening…' tylko gdy capture ruszył i stop() nie ubiegł nas podczas await.
    if (ok && this.mic === mic) this.handlers.onStatus?.('Listening…')
  }

  private onMessage(raw: string): void {
    let m: RealtimeEvent
    try {
      m = JSON.parse(raw) as RealtimeEvent
    } catch {
      return
    }
    const t = m.type
    if (!t) return
    if (t.endsWith('audio.delta') && m.delta) {
      this.enqueueAudio(m.delta)
    } else if (t.endsWith('audio_transcript.delta') && m.delta) {
      this.handlers.onAssistantDelta?.(m.delta)
    } else if (t === 'conversation.item.input_audio_transcription.completed' && m.transcript) {
      this.handlers.onUserText?.(m.transcript)
    } else if (t === 'response.done' || t === 'response.completed') {
      this.handlers.onAssistantDone?.()
    } else if (t === 'error') {
      this.handlers.onError?.(m.error?.message || 'Realtime error')
    }
  }

  private enqueueAudio(b64: string): void {
    const Ctx: AudioCtxCtor =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: AudioCtxCtor }).webkitAudioContext
    if (!this.playCtx) {
      this.playCtx = new Ctx({ sampleRate: SAMPLE_RATE })
      this.nextTime = 0
    }
    const ctx = this.playCtx
    const f32 = pcm16ToFloat(base64ToArrayBuffer(b64))
    if (!f32.length) return
    const buf = ctx.createBuffer(1, f32.length, SAMPLE_RATE)
    buf.getChannelData(0).set(f32)
    const src = ctx.createBufferSource()
    src.buffer = buf
    src.connect(ctx.destination)
    const now = ctx.currentTime
    if (this.nextTime < now) this.nextTime = now
    src.start(this.nextTime)
    this.nextTime += buf.duration
  }

  stop(): void {
    this.stopMic()
    try {
      this.ws?.close()
    } catch {
      /* ignore */
    }
    this.ws = null
    try {
      void this.playCtx?.close()
    } catch {
      /* ignore */
    }
    this.playCtx = null
  }

  private stopMic(): void {
    this.mic?.stop()
    this.mic = null
  }
}
