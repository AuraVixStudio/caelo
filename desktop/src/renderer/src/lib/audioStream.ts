// Wspólny prymityw przechwytywania mikrofonu jako strumień PCM16 (M12). Używany
// przez realtime (`realtime.ts`) i pipeline rozmowy (`converse.ts`) — jeden skeleton
// audio, by fixy nie driftowały. Procesor PCM działa w AudioWorklet (osobny wątek,
// zastępuje deprecated ScriptProcessorNode), ładowany z Blob URL (działa w dev,
// podglądzie i spakowanym build `file://` bez osobnego pliku-assetu).

// Kod procesora AudioWorklet: buforuje wejście mikrofonu i co ~`target` próbek
// konwertuje Float32 → PCM16, po czym przekazuje transferowalny ArrayBuffer (bez kopii)
// do wątku głównego.
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

type AudioCtxCtor = typeof AudioContext

function audioCtxCtor(): AudioCtxCtor {
  return (
    window.AudioContext ||
    (window as unknown as { webkitAudioContext: AudioCtxCtor }).webkitAudioContext
  )
}

export interface MicCaptureOptions {
  sampleRate: number
  /** Wołany dla każdej porcji PCM16 (transferowalny ArrayBuffer). */
  onChunk: (pcm16: ArrayBuffer) => void
  /** Wołany, gdy dostęp do mikrofonu/audio jest niedostępny. */
  onError?: (message: string) => void
}

/**
 * Przechwytywanie mikrofonu jako strumień PCM16 o zadanym sample rate. `start()`
 * rozkręca getUserMedia + AudioWorklet i wywołuje `onChunk` dla kolejnych porcji;
 * `stop()` sprząta cały graf audio i zwalnia mikrofon. Bezpieczne wobec stop()
 * w trakcie asynchronicznego `addModule` (guard na podmieniony kontekst).
 */
export class MicCapture {
  private stream: MediaStream | null = null
  private ctx: AudioContext | null = null
  private worklet: AudioWorkletNode | null = null
  private source: MediaStreamAudioSourceNode | null = null
  private sink: GainNode | null = null

  constructor(private opts: MicCaptureOptions) {}

  /** Zwraca `true`, gdy przechwytywanie ruszyło; `false` przy odmowie/braku audio
   *  (lub gdy `stop()` ubiegł asynchroniczne wejście). */
  async start(): Promise<boolean> {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }
      })
    } catch {
      this.opts.onError?.('Microphone access was denied.')
      return false
    }
    const ctx = new (audioCtxCtor())({ sampleRate: this.opts.sampleRate })
    this.ctx = ctx
    try {
      const url = URL.createObjectURL(new Blob([PCM_WORKLET_CODE], { type: 'application/javascript' }))
      try {
        await ctx.audioWorklet.addModule(url)
      } finally {
        URL.revokeObjectURL(url)
      }
    } catch {
      this.opts.onError?.('Audio capture is unavailable in this environment.')
      this.stop()
      return false
    }
    // stop() mógł wystartować podczas await addModule — wtedy ctx już znullowany/podmieniony.
    if (this.ctx !== ctx || !this.stream) return false

    this.source = ctx.createMediaStreamSource(this.stream)
    const node = new AudioWorkletNode(ctx, 'pcm-capture')
    this.worklet = node
    node.port.onmessage = (e) => this.opts.onChunk(e.data as ArrayBuffer)
    // AudioWorklet przetwarza tylko, gdy jest w ścieżce do destination; zerowy gain
    // eliminuje odsłuch własnego mikrofonu.
    const sink = ctx.createGain()
    sink.gain.value = 0
    this.sink = sink
    this.source.connect(node)
    node.connect(sink)
    sink.connect(ctx.destination)
    return true
  }

  stop(): void {
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
    this.stream?.getTracks().forEach((t) => t.stop())
    try {
      void this.ctx?.close()
    } catch {
      /* ignore */
    }
    this.worklet = null
    this.sink = null
    this.source = null
    this.stream = null
    this.ctx = null
  }
}
