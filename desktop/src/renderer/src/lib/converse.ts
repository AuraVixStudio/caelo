// Klient pipeline'u rozmowy głosowej (M12-B3/F2 „Talk to Grok"). Orkiestruje:
//   mikrofon → STT-stream (/voice/stt/stream) → finalny transkrypt
//           → /voice/converse (Responses M10 + live search + historia M9)
//           → tekst na żywo + audio TTS → odtwarzanie.
// Maszyna stanów: idle → listening → thinking → speaking → listening…
// Barge-in: mowa w trakcie odtwarzania TTS przerywa je i zaczyna nową turę.
//
// To „kolejny front na ten sam mózg" (M10/M9), nie wyspa — w odróżnieniu od
// niskolatencyjnego realtime (B4, `realtime.ts`), które jest osobną powierzchnią.
//
// Nazwy zdarzeń STT xAI potwierdzamy na żywo — parser jest defensywny (warianty
// partial/final), jak w realtime.ts. Klucz nigdy nie dotyka renderera (most sidecara).

import { playBase64Audio, arrayBufferToBase64 } from './audio'
import { MicCapture } from './audioStream'
import { voiceConverseUrl, voiceSttStreamUrl, type Conn } from './api'

// STT xAI: sample rate do potwierdzenia na żywo (open question planu). 16 kHz to typowa
// wartość STT; renderer pakuje porcje mikrofonu pod nią.
const STT_SAMPLE_RATE = 16000

export type ConverseState = 'idle' | 'connecting' | 'listening' | 'thinking' | 'speaking'

export interface ConverseHandlers {
  onState?: (s: ConverseState) => void
  onPartial?: (text: string) => void // partial bieżącej wypowiedzi usera
  onUserText?: (text: string) => void // sfinalizowana tura usera
  onAssistantDelta?: (delta: string) => void // przyrost odpowiedzi
  onAssistantDone?: (full: string) => void
  onCitations?: (urls: string[]) => void
  onCost?: (c: { ttsChars: number; ttsCost: number }) => void
  onSttSeconds?: (seconds: number) => void // czas mikrofonu (koszt STT-stream)
  onError?: (e: string) => void
}

export interface ConverseOptions {
  voice?: string
  language?: string
  model?: string
  systemPrompt?: string
  searchMode?: 'auto' | 'on' | 'off'
  sources?: string[]
  /** Barge-in: mowa w trakcie TTS przerywa odtwarzanie (domyślnie true). */
  bargeIn?: boolean
}

interface SttParsed {
  kind: 'partial' | 'final' | null
  text: string
}

/** Defensywny parser zdarzeń STT (warianty nazw xAI — potwierdzane na żywo). */
export function parseStt(raw: string): SttParsed {
  let m: Record<string, unknown>
  try {
    m = JSON.parse(raw) as Record<string, unknown>
  } catch {
    return { kind: null, text: '' }
  }
  const t = typeof m.type === 'string' ? m.type : ''
  const delta = typeof m.delta === 'string' ? m.delta : ''
  const transcript = typeof m.transcript === 'string' ? m.transcript : ''
  const text = typeof m.text === 'string' ? m.text : ''
  const isFinal = m.is_final === true || m.final === true
  if (t === 'error') return { kind: null, text: '' }
  // Finalne: *.completed / *.done / *.final / is_final
  if (/transcript\.(completed|done|final)$/.test(t) || isFinal) {
    return { kind: 'final', text: transcript || text || delta }
  }
  // Partiale: *.delta / *partial*
  if (t.endsWith('transcript.delta') || /partial/i.test(t)) {
    return { kind: 'partial', text: delta || text || transcript }
  }
  // Goły kształt {text, is_final:false}
  if (!t && text) return { kind: isFinal ? 'final' : 'partial', text }
  return { kind: null, text: '' }
}

export class ConversePipeline {
  private sttWs: WebSocket | null = null
  private convWs: WebSocket | null = null
  private mic: MicCapture | null = null
  private audio: HTMLAudioElement | null = null
  private state: ConverseState = 'idle'
  private history: { role: string; content: string }[] = []
  private pendingUser = '' // transkrypt usera czekający na odpowiedź
  private assistant = '' // narastająca odpowiedź bieżącej tury
  private micStartMs = 0
  private stopped = false

  constructor(
    private conn: Conn,
    private opts: ConverseOptions,
    private handlers: ConverseHandlers
  ) {}

  start(): void {
    this.stopped = false
    this.setState('connecting')
    this.openConverse()
    this.openStt()
  }

  stop(): void {
    this.stopped = true
    this.flushSttSeconds()
    this.stopPlayback()
    this.mic?.stop()
    this.mic = null
    try {
      this.sttWs?.close()
    } catch {
      /* ignore */
    }
    try {
      this.convWs?.close()
    } catch {
      /* ignore */
    }
    this.sttWs = null
    this.convWs = null
    this.setState('idle')
  }

  private setState(s: ConverseState): void {
    if (this.state === s) return
    this.state = s
    this.handlers.onState?.(s)
  }

  // --- STT stream (mowa → transkrypt) ---
  private openStt(): void {
    const ws = new WebSocket(voiceSttStreamUrl(this.conn, this.opts.language))
    this.sttWs = ws
    ws.onopen = () => {
      if (this.stopped) return
      void this.startMic()
      if (this.state === 'connecting') this.setState('listening')
    }
    ws.onmessage = (ev) => this.onSttMessage(ev.data as string)
    ws.onerror = () => this.handlers.onError?.('Speech-to-text connection error')
    ws.onclose = () => {
      this.flushSttSeconds()
    }
  }

  private async startMic(): Promise<void> {
    this.micStartMs = Date.now()
    const mic = new MicCapture({
      sampleRate: STT_SAMPLE_RATE,
      onChunk: (buf) => {
        if (this.sttWs?.readyState !== WebSocket.OPEN) return
        // Konwencja realtime-like: porcje audio jako base64 w input_audio_buffer.append.
        this.sttWs.send(
          JSON.stringify({ type: 'input_audio_buffer.append', audio: arrayBufferToBase64(buf) })
        )
      },
      onError: (m) => this.handlers.onError?.(m)
    })
    this.mic = mic
    await mic.start()
  }

  private flushSttSeconds(): void {
    if (this.micStartMs) {
      const sec = (Date.now() - this.micStartMs) / 1000
      if (sec > 0) this.handlers.onSttSeconds?.(sec)
      this.micStartMs = 0
    }
  }

  private onSttMessage(raw: string): void {
    const { kind, text } = parseStt(raw)
    if (!kind || !text) return
    if (kind === 'partial') {
      this.handlers.onPartial?.(text)
      // Barge-in: mowa usera w trakcie odtwarzania TTS przerywa je.
      if (this.state === 'speaking' && this.opts.bargeIn !== false) this.bargeIn()
      return
    }
    // final
    const t = text.trim()
    if (!t) return
    if (this.state === 'speaking' && this.opts.bargeIn !== false) this.bargeIn()
    this.handlers.onPartial?.('')
    this.handlers.onUserText?.(t)
    this.sendTurn(t)
  }

  // --- Converse (transkrypt → odpowiedź + głos) ---
  private openConverse(): void {
    const ws = new WebSocket(voiceConverseUrl(this.conn))
    this.convWs = ws
    ws.onmessage = (ev) => this.onConverseMessage(ev.data as string)
    ws.onerror = () => this.handlers.onError?.('Conversation connection error')
  }

  private sendTurn(transcript: string): void {
    if (this.convWs?.readyState !== WebSocket.OPEN) {
      this.handlers.onError?.('Not connected.')
      return
    }
    this.pendingUser = transcript
    this.assistant = ''
    this.setState('thinking')
    this.convWs.send(
      JSON.stringify({
        type: 'converse',
        transcript,
        messages: this.history,
        model: this.opts.model,
        voice_id: this.opts.voice,
        language: this.opts.language || 'en',
        system_prompt: this.opts.systemPrompt || '',
        search_mode: this.opts.searchMode || 'off',
        sources: this.opts.sources || null,
        speak: true
      })
    )
  }

  private onConverseMessage(raw: string): void {
    let m: Record<string, unknown>
    try {
      m = JSON.parse(raw) as Record<string, unknown>
    } catch {
      return
    }
    switch (m.type) {
      case 'delta':
        if (typeof m.delta === 'string') {
          this.assistant += m.delta
          this.handlers.onAssistantDelta?.(m.delta)
        }
        break
      case 'citations': {
        const cits = Array.isArray(m.citations) ? m.citations : []
        const urls = cits
          .map((c) => (c && typeof c === 'object' ? (c as { url?: string }).url : undefined))
          .filter((u): u is string => !!u)
        if (urls.length) this.handlers.onCitations?.(urls)
        break
      }
      case 'audio':
        if (typeof m.audio_b64 === 'string') {
          this.playAudio(m.audio_b64, typeof m.mime === 'string' ? m.mime : 'audio/mpeg')
        }
        break
      case 'cost':
        this.handlers.onCost?.({
          ttsChars: Number(m.tts_chars) || 0,
          ttsCost: Number(m.tts_cost) || 0
        })
        break
      case 'done': {
        const full = typeof m.full === 'string' ? m.full : this.assistant
        if (this.pendingUser) this.history.push({ role: 'user', content: this.pendingUser })
        if (full) this.history.push({ role: 'assistant', content: full })
        this.pendingUser = ''
        this.handlers.onAssistantDone?.(full)
        // Jeśli nie odtwarzamy audio (np. brak TTS), wracamy do słuchania.
        if (this.state !== 'speaking') this.setState('listening')
        break
      }
      case 'warning':
        // TTS się nie udało — tekst dostarczony; nie wywracaj rozmowy.
        break
      case 'error':
        this.handlers.onError?.(typeof m.error === 'string' ? m.error : 'Conversation error')
        this.setState('listening')
        break
    }
  }

  // --- Odtwarzanie TTS (pełny MP3 z `audio` frame) ---
  private playAudio(b64: string, mime: string): void {
    this.stopPlayback()
    this.setState('speaking')
    const audio = playBase64Audio(b64, mime)
    this.audio = audio
    audio.onended = () => {
      if (this.audio === audio) {
        this.audio = null
        this.setState('listening')
      }
    }
  }

  private stopPlayback(): void {
    if (this.audio) {
      try {
        this.audio.pause()
      } catch {
        /* ignore */
      }
      this.audio.onended = null
      this.audio = null
    }
  }

  private bargeIn(): void {
    this.stopPlayback()
    try {
      this.convWs?.send(JSON.stringify({ type: 'stop' }))
    } catch {
      /* ignore */
    }
    this.setState('listening')
  }
}
