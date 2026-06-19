// Klient pipeline'u rozmowy głosowej (M12-B3/F2 „Talk to Caelo"). Orkiestruje:
//   mikrofon → VAD (auto-stop na ciszy) → batch STT (/voice/stt)
//           → /voice/converse (Responses M10 + live search + historia M9)
//           → tekst na żywo + audio TTS → odtwarzanie.
// Maszyna stanów: idle → listening → thinking → speaking → listening…
// Barge-in: mowa w trakcie odtwarzania TTS przerywa je i zaczyna nową turę.
//
// To „kolejny front na ten sam mózg" (M10/M9), nie wyspa — w odróżnieniu od
// niskolatencyjnego realtime (B4, `realtime.ts`), które jest osobną powierzchnią.
//
// ⚠️ STT: pierwotnie ten pipeline streamował audio do wss://api.x.ai/v1/stt
// (`input_audio_buffer.append`). LIVE-zweryfikowano (D3, 2026-06-19), że xAI ODRZUCA
// ten protokół: serwer zwraca `transcript.created` + `error: unknown variant
// input_audio_buffer.append, expected audio.done` — czyli oczekuje innego (binarnego)
// formatu, nieudokumentowanego. Decyzja: Talk używa DZIAŁAJĄCEGO batch-STT (jak
// dyktowanie D2) z lokalnym VAD do wykrycia końca wypowiedzi. Tracimy partiale na żywo
// (których streaming i tak nie dostarczał), zyskujemy odporny, działający tryb. Streaming
// `parseStt`/`/voice/stt/stream` zostają w kodzie na wypadek, gdy xAI udokumentuje endpoint.

import { blobToBase64, playBase64Audio } from './audio'
import { speechToText, voiceConverseUrl, type Conn } from './api'

// --- VAD (Voice Activity Detection) — strojalne progi auto-stopu ---
const SILENCE_MS = 1500 // cisza po mowie kończąca wypowiedź
const SPEECH_RMS = 0.02 // próg RMS uznawany za mowę (0..1)
const VAD_INTERVAL_MS = 50 // okres próbkowania głośności
const SPEECH_FRAMES = 3 // ile kolejnych głośnych ramek = początek mowy (anty-trzask)
const MAX_SEGMENT_MS = 30000 // bezpiecznik: utnij segment po 30 s ciągłej mowy

export type ConverseState = 'idle' | 'connecting' | 'listening' | 'thinking' | 'speaking'

export interface ConverseHandlers {
  onState?: (s: ConverseState) => void
  onPartial?: (text: string) => void // partial bieżącej wypowiedzi usera (batch: tylko czyszczenie)
  onUserText?: (text: string) => void // sfinalizowana tura usera
  onAssistantDelta?: (delta: string) => void // przyrost odpowiedzi
  onAssistantDone?: (full: string) => void
  onCitations?: (urls: string[]) => void
  onCost?: (c: { ttsChars: number; ttsCost: number }) => void
  onSttSeconds?: (seconds: number) => void // czas audio wypowiedzi (koszt STT batch)
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

/** Defensywny parser zdarzeń STT-stream (warianty nazw xAI). Zachowany dla
 *  ewentualnego powrotu do streamingu (xAI obecnie odrzuca nasz protokół — zob. nagłówek). */
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

/** RMS (0..1) z bloku próbek time-domain. Czysta funkcja — testowalna bez WebAudio. */
export function computeRms(samples: Float32Array): number {
  if (!samples.length) return 0
  let sum = 0
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i]
  return Math.sqrt(sum / samples.length)
}

export class ConversePipeline {
  private convWs: WebSocket | null = null
  private audio: HTMLAudioElement | null = null
  private state: ConverseState = 'idle'
  private history: { role: string; content: string }[] = []
  private pendingUser = '' // transkrypt usera czekający na odpowiedź
  private assistant = '' // narastająca odpowiedź bieżącej tury
  private stopped = false

  // --- VAD / nagrywanie ---
  private stream: MediaStream | null = null
  private vadCtx: AudioContext | null = null
  private analyser: AnalyserNode | null = null
  // Jawny ArrayBuffer (nie ArrayBufferLike) — getFloatTimeDomainData wymaga Float32Array<ArrayBuffer>.
  private vadBuf: Float32Array<ArrayBuffer> | null = null
  private vadTimer: number | null = null
  private rec: MediaRecorder | null = null
  private recChunks: BlobPart[] = []
  private segHasSpeech = false // bieżący segment zawierał mowę
  private aboveFrames = 0 // licznik kolejnych głośnych ramek (start mowy)
  private silenceSince = 0 // znacznik początku ciszy po mowie
  private segStartMs = 0 // start bieżącego segmentu (czas/koszt + bezpiecznik)
  private finalizing = false // trwa zamykanie segmentu (anty-reentry)

  constructor(
    private conn: Conn,
    private opts: ConverseOptions,
    private handlers: ConverseHandlers
  ) {}

  start(): void {
    this.stopped = false
    this.setState('connecting')
    this.openConverse()
    void this.startListening()
  }

  stop(): void {
    this.stopped = true
    this.stopVad()
    this.stopPlayback()
    try {
      this.convWs?.close()
    } catch {
      /* ignore */
    }
    this.convWs = null
    this.setState('idle')
  }

  private setState(s: ConverseState): void {
    if (this.state === s) return
    this.state = s
    this.handlers.onState?.(s)
  }

  // --- Mikrofon + VAD (mowa → batch STT) ---
  private async startListening(): Promise<void> {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }
      })
    } catch {
      this.handlers.onError?.('Microphone access was denied.')
      this.setState('idle')
      return
    }
    if (this.stopped) {
      this.stream.getTracks().forEach((t) => t.stop())
      this.stream = null
      return
    }
    try {
      const Ctor =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      const ctx = new Ctor()
      this.vadCtx = ctx
      const src = ctx.createMediaStreamSource(this.stream)
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 1024
      src.connect(analyser)
      this.analyser = analyser
      this.vadBuf = new Float32Array(new ArrayBuffer(analyser.fftSize * Float32Array.BYTES_PER_ELEMENT))
    } catch {
      this.handlers.onError?.('Audio capture is unavailable in this environment.')
      this.stop()
      return
    }
    this.startRecorder()
    this.vadTimer = window.setInterval(() => this.vadTick(), VAD_INTERVAL_MS)
    if (this.state === 'connecting') this.setState('listening')
  }

  private startRecorder(): void {
    if (!this.stream) return
    const mime = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : ''
    this.rec = mime
      ? new MediaRecorder(this.stream, { mimeType: mime })
      : new MediaRecorder(this.stream)
    this.recChunks = []
    this.segHasSpeech = false
    this.aboveFrames = 0
    this.silenceSince = 0
    this.segStartMs = Date.now()
    this.rec.ondataavailable = (e) => {
      if (e.data.size) this.recChunks.push(e.data)
    }
    this.rec.start()
  }

  private vadTick(): void {
    if (this.stopped || this.finalizing || !this.analyser || !this.vadBuf) return
    this.analyser.getFloatTimeDomainData(this.vadBuf)
    const rms = computeRms(this.vadBuf)
    const now = Date.now()
    if (rms > SPEECH_RMS) {
      this.aboveFrames++
      this.silenceSince = 0
      if (!this.segHasSpeech && this.aboveFrames >= SPEECH_FRAMES) {
        this.segHasSpeech = true
        // Barge-in: mowa usera w trakcie odtwarzania TTS przerywa je natychmiast.
        if (this.state === 'speaking' && this.opts.bargeIn !== false) this.bargeIn()
      }
    } else {
      this.aboveFrames = 0
      if (this.segHasSpeech) {
        if (this.silenceSince === 0) this.silenceSince = now
        else if (now - this.silenceSince >= SILENCE_MS) this.endUtterance()
      }
    }
    // Bezpiecznik: bardzo długa wypowiedź bez ciszy — utnij segment.
    if (this.segHasSpeech && now - this.segStartMs >= MAX_SEGMENT_MS) this.endUtterance()
  }

  private endUtterance(): void {
    const rec = this.rec
    if (!rec || this.finalizing) return
    this.finalizing = true
    const seconds = (Date.now() - this.segStartMs) / 1000
    const mime = rec.mimeType || 'audio/webm'
    rec.onstop = () => {
      const blob = new Blob(this.recChunks, { type: mime })
      this.finalizing = false
      if (!this.stopped) this.startRecorder() // nasłuchuj kolejnej wypowiedzi
      void this.transcribe(blob, seconds)
    }
    try {
      rec.stop()
    } catch {
      this.finalizing = false
    }
  }

  private async transcribe(blob: Blob, seconds: number): Promise<void> {
    if (this.stopped) return
    this.handlers.onSttSeconds?.(seconds) // koszt STT (batch) z czasu wypowiedzi
    this.setState('thinking')
    try {
      const audio_b64 = await blobToBase64(blob)
      const r = await speechToText(this.conn, {
        audio_b64,
        filename: 'speech.webm',
        language: this.opts.language
      })
      const t = (r.text || '').trim()
      if (!t || this.stopped) {
        if (!this.stopped && this.state === 'thinking') this.setState('listening')
        return
      }
      this.handlers.onPartial?.('')
      this.handlers.onUserText?.(t)
      this.sendTurn(t)
    } catch {
      this.handlers.onError?.('Speech-to-text failed.')
      if (!this.stopped) this.setState('listening')
    }
  }

  private stopVad(): void {
    if (this.vadTimer !== null) {
      clearInterval(this.vadTimer)
      this.vadTimer = null
    }
    try {
      if (this.rec && this.rec.state !== 'inactive') {
        this.rec.onstop = null
        this.rec.stop()
      }
    } catch {
      /* ignore */
    }
    this.rec = null
    this.recChunks = []
    this.stream?.getTracks().forEach((t) => t.stop())
    this.stream = null
    try {
      void this.vadCtx?.close()
    } catch {
      /* ignore */
    }
    this.vadCtx = null
    this.analyser = null
    this.vadBuf = null
    this.finalizing = false
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
    // Nowa tura, gdy poprzednia trwa (mowa w trakcie thinking/speaking): przerwij ją
    // (converse jest single-flight i odrzuca równoległe tury) i wyślij po krótkiej chwili.
    const wasBusy = this.state === 'thinking' || this.state === 'speaking'
    if (wasBusy) {
      this.stopPlayback()
      try {
        this.convWs.send(JSON.stringify({ type: 'stop' }))
      } catch {
        /* ignore */
      }
    }
    const doSend = (): void => {
      if (this.stopped || this.convWs?.readyState !== WebSocket.OPEN) return
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
    if (wasBusy) window.setTimeout(doSend, 250)
    else doSend()
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
