// Klient realtime voice. Łączy się z mostem sidecara (/voice/realtime), który
// proxuje do wss://api.x.ai/v1/realtime. Przechwytuje mikrofon jako PCM16 24 kHz,
// strumieniuje go (input_audio_buffer.append) i odtwarza audio z odpowiedzi
// (response.output_audio.delta). Detekcja tur po stronie serwera (server_vad).
//
// Nazwy zdarzeń trzymają się konwencji OpenAI Realtime, którą odwzorowuje xAI
// (session.update / server_vad / *audio.delta / *audio_transcript.delta) — dokładne
// nazwy potwierdzamy na żywo; obsługujemy warianty z/bez prefiksu "output_".

import { arrayBufferToBase64, base64ToArrayBuffer } from './audio'
import { voiceRealtimeUrl, type Conn } from './api'

const SAMPLE_RATE = 24000

// Kod procesora AudioWorklet (P2-5) — zastępuje deprecated ScriptProcessorNode.
// Działa w AudioWorkletGlobalScope (osobny wątek audio, bez importów ESM): buforuje
// wejście mikrofonu i co ~2048 próbek konwertuje na PCM16, po czym przekazuje
// ArrayBuffer (transferowalny → bez kopii) do wątku głównego, który strumieniuje go
// po WS. Ładowany jako Blob URL, więc działa tak samo w dev, podglądzie i spakowanym
// build (file://) bez osobnego pliku-assetu.
const PCM_WORKLET_CODE = `
class PCMCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this._chunks = []
    this._count = 0
    this._target = 2048
  }
  process(inputs) {
    const input = inputs[0]
    if (input && input[0]) {
      this._chunks.push(new Float32Array(input[0]))
      this._count += input[0].length
      if (this._count >= this._target) {
        const merged = new Float32Array(this._count)
        let off = 0
        for (let i = 0; i < this._chunks.length; i++) {
          merged.set(this._chunks[i], off)
          off += this._chunks[i].length
        }
        this._chunks = []
        this._count = 0
        const out = new Int16Array(merged.length)
        for (let i = 0; i < merged.length; i++) {
          const s = Math.max(-1, Math.min(1, merged[i]))
          out[i] = s < 0 ? s * 0x8000 : s * 0x7fff
        }
        this.port.postMessage(out.buffer, [out.buffer])
      }
    }
    return true
  }
}
registerProcessor('pcm-capture', PCMCaptureProcessor)
`

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
  private micCtx: AudioContext | null = null
  private playCtx: AudioContext | null = null
  private stream: MediaStream | null = null
  private worklet: AudioWorkletNode | null = null
  private sink: GainNode | null = null
  private source: MediaStreamAudioSourceNode | null = null
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
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }
      })
    } catch {
      this.handlers.onError?.('Microphone access was denied.')
      return
    }
    const Ctx: AudioCtxCtor =
      window.AudioContext || (window as unknown as { webkitAudioContext: AudioCtxCtor }).webkitAudioContext
    const ctx = new Ctx({ sampleRate: SAMPLE_RATE })
    this.micCtx = ctx

    // Załaduj procesor AudioWorklet z Blob URL (P2-5).
    try {
      const url = URL.createObjectURL(
        new Blob([PCM_WORKLET_CODE], { type: 'application/javascript' })
      )
      try {
        await ctx.audioWorklet.addModule(url)
      } finally {
        URL.revokeObjectURL(url)
      }
    } catch {
      this.handlers.onError?.('Audio capture is unavailable in this environment.')
      this.stopMic()
      return
    }
    // stop() mógł wystartować podczas await addModule — wtedy micCtx już znullowany.
    if (this.micCtx !== ctx) return

    this.source = ctx.createMediaStreamSource(this.stream)
    const node = new AudioWorkletNode(ctx, 'pcm-capture')
    this.worklet = node
    node.port.onmessage = (e) => {
      if (this.ws?.readyState !== WebSocket.OPEN) return
      this.send({
        type: 'input_audio_buffer.append',
        audio: arrayBufferToBase64(e.data as ArrayBuffer)
      })
    }
    // AudioWorklet przetwarza tylko, gdy jest w ścieżce do destination; zerowy gain
    // eliminuje odsłuch własnego mikrofonu (jak przy ScriptProcessorze).
    const sink = ctx.createGain()
    sink.gain.value = 0
    this.sink = sink
    this.source.connect(node)
    node.connect(sink)
    sink.connect(ctx.destination)
    this.handlers.onStatus?.('Listening…')
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
      window.AudioContext || (window as unknown as { webkitAudioContext: AudioCtxCtor }).webkitAudioContext
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
    try {
      if (this.worklet) this.worklet.port.onmessage = null
      this.worklet?.port.close()
      this.worklet?.disconnect()
    } catch {
      /* ignore */
    }
    try {
      this.sink?.disconnect()
    } catch {
      /* ignore */
    }
    try {
      this.source?.disconnect()
    } catch {
      /* ignore */
    }
    this.stream?.getTracks().forEach((track) => track.stop())
    try {
      void this.micCtx?.close()
    } catch {
      /* ignore */
    }
    this.worklet = null
    this.sink = null
    this.source = null
    this.stream = null
    this.micCtx = null
  }
}
