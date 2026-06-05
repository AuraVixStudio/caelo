import { useEffect, useRef, useState } from 'react'
import { Copy, Mic, Square, Volume2 } from 'lucide-react'
import { speechToText, textToSpeech, type Conn } from '../lib/api'
import { useModels, useSettings } from '../lib/serverState'
import { DEFAULT_VOICE, VOICE_LANGUAGES, VOICES } from '../lib/constants'
import { blobToBase64, MicRecorder } from '../lib/audio'
import { RealtimeSession } from '../lib/realtime'
import { ConversePipeline, type ConverseState } from '../lib/converse'
import {
  emptyAudioUsage,
  formatAudioUsage,
  recordStt,
  recordTts,
  type AudioUsage
} from '../lib/audioCost'
import { cn } from '../lib/cn'
import { Button } from './ui/Button'
import { Card } from './ui/Card'
import { Page, Field } from './ui/Page'
import { Select } from './ui/Select'
import { Textarea } from './ui/Textarea'

type Mode = 'speak' | 'transcribe' | 'talk' | 'live'

const MODES: { id: Mode; label: string }[] = [
  { id: 'speak', label: 'Speak' },
  { id: 'transcribe', label: 'Transcribe' },
  { id: 'talk', label: 'Talk' },
  { id: 'live', label: 'Live' }
]

interface LiveEntry {
  role: 'user' | 'assistant'
  text: string
}

// Etykieta + kolor kropki dla stanu pipeline'u rozmowy (F2).
const TALK_STATE: Record<ConverseState, { label: string; dot: string }> = {
  idle: { label: 'Idle', dot: 'bg-muted' },
  connecting: { label: 'Connecting…', dot: 'bg-warn animate-pulse' },
  listening: { label: 'Listening', dot: 'bg-success animate-pulse' },
  thinking: { label: 'Thinking…', dot: 'bg-accent animate-pulse' },
  speaking: { label: 'Speaking', dot: 'bg-accent' }
}

export function Voice({ conn }: { conn: Conn }) {
  const [mode, setMode] = useState<Mode>('speak')
  const [voices, setVoices] = useState(VOICES.map((v) => v.id))
  const [voice, setVoice] = useState(DEFAULT_VOICE)
  const [language, setLanguage] = useState('en')
  const [realtimeModel, setRealtimeModel] = useState<string | undefined>(undefined)
  // M12-F5: licznik kosztu audio per sesja (BYO-key) — wspólny dla wszystkich trybów.
  const [usage, setUsage] = useState<AudioUsage>(emptyAudioUsage)

  // TTS
  const [text, setText] = useState('')
  const [ttsBusy, setTtsBusy] = useState(false)
  const [ttsError, setTtsError] = useState<string | null>(null)
  const [ttsAudio, setTtsAudio] = useState<{ dataUrl: string; path: string | null } | null>(null)

  // STT
  const [recording, setRecording] = useState(false)
  const [sttBusy, setSttBusy] = useState(false)
  const [sttError, setSttError] = useState<string | null>(null)
  const [transcript, setTranscript] = useState('')
  const recorderRef = useRef<MicRecorder | null>(null)

  // Talk (pipeline rozmowy: STT-stream → Responses → TTS)
  const [talkState, setTalkState] = useState<ConverseState>('idle')
  const [talkError, setTalkError] = useState<string | null>(null)
  const [talkLog, setTalkLog] = useState<LiveEntry[]>([])
  const [talkPartial, setTalkPartial] = useState('')
  const [talkSearch, setTalkSearch] = useState(false) // live search w rozmowie (M10)
  const [talkCitations, setTalkCitations] = useState<string[]>([])
  const pipelineRef = useRef<ConversePipeline | null>(null)
  const talkAssistantOpen = useRef(false)
  const talkActive = talkState !== 'idle'

  // Realtime (Live, B4 stretch)
  const [liveStatus, setLiveStatus] = useState('Idle')
  const [liveError, setLiveError] = useState<string | null>(null)
  const [instructions, setInstructions] = useState('')
  const [liveLog, setLiveLog] = useState<LiveEntry[]>([])
  const sessionRef = useRef<RealtimeSession | null>(null)
  const assistantOpen = useRef(false)
  const connected = liveStatus !== 'Idle' && liveStatus !== 'Disconnected'
  const { models: modelsResp } = useModels(conn) // P2-2: współdzielony cache /models
  const { settings } = useSettings(conn)

  useEffect(() => {
    if (!modelsResp) return
    if (modelsResp.voices?.length) setVoices(modelsResp.voices)
    setVoice((prev) => prev || modelsResp.default_voice || DEFAULT_VOICE)
    setRealtimeModel(modelsResp.realtime_model)
  }, [modelsResp])

  // M12-F4: domyślny głos/język z ustawień (nadpisuje fallback z /models).
  const settingsInit = useRef(false)
  useEffect(() => {
    if (!settings || settingsInit.current) return
    settingsInit.current = true
    if (settings.voice) setVoice(settings.voice)
    if (settings.voice_language) setLanguage(settings.voice_language)
  }, [settings])

  useEffect(() => {
    return () => {
      sessionRef.current?.stop()
      pipelineRef.current?.stop()
      recorderRef.current?.cancel()
    }
  }, [])

  // P2-5: opuszczenie trybu (nie tylko odmontowanie) kończy aktywne sesje — mikrofon
  // i WS nie mogą zostać aktywne po przełączeniu zakładki trybu.
  useEffect(() => {
    if (mode !== 'live' && sessionRef.current) {
      sessionRef.current.stop()
      sessionRef.current = null
      assistantOpen.current = false
      setLiveStatus('Idle')
    }
    if (mode !== 'talk' && pipelineRef.current) {
      pipelineRef.current.stop()
      pipelineRef.current = null
      talkAssistantOpen.current = false
      setTalkState('idle')
      setTalkPartial('')
    }
  }, [mode])

  // --- TTS ---
  async function speak(): Promise<void> {
    if (!text.trim() || ttsBusy) return
    setTtsBusy(true)
    setTtsError(null)
    try {
      const r = await textToSpeech(conn, { text: text.trim(), voice_id: voice, language })
      setTtsAudio({ dataUrl: `data:${r.mime};base64,${r.audio_b64}`, path: r.path })
      setUsage((u) => recordTts(u, { chars: r.chars ?? text.trim().length, cost: r.cost }))
    } catch (e) {
      setTtsError(String((e as Error).message || e))
    } finally {
      setTtsBusy(false)
    }
  }

  // --- STT ---
  async function toggleRecording(): Promise<void> {
    if (sttBusy) return
    if (recording) {
      const rec = recorderRef.current
      recorderRef.current = null
      setRecording(false)
      if (!rec) return
      setSttBusy(true)
      setSttError(null)
      try {
        const { blob } = await rec.stop()
        const audio_b64 = await blobToBase64(blob)
        const r = await speechToText(conn, { audio_b64, filename: 'speech.webm', language })
        setTranscript((r.text || '').trim())
        if (r.duration || r.cost)
          setUsage((u) => recordStt(u, { seconds: r.duration ?? 0, cost: r.cost }))
      } catch (e) {
        setSttError(String((e as Error).message || e))
      } finally {
        setSttBusy(false)
      }
    } else {
      setSttError(null)
      const rec = new MicRecorder()
      try {
        await rec.start()
        recorderRef.current = rec
        setRecording(true)
      } catch {
        setSttError('Microphone access was denied.')
      }
    }
  }

  // --- Talk (pipeline) ---
  function toggleTalk(): void {
    if (talkActive) {
      pipelineRef.current?.stop()
      pipelineRef.current = null
      talkAssistantOpen.current = false
      setTalkState('idle')
      setTalkPartial('')
      return
    }
    setTalkError(null)
    setTalkLog([])
    setTalkCitations([])
    setTalkPartial('')
    talkAssistantOpen.current = false
    const pipeline = new ConversePipeline(
      conn,
      {
        // model: pominięty → sidecar użyje domyślnego chat-modelu (Responses M10).
        voice,
        language,
        searchMode: talkSearch ? 'auto' : 'off',
        sources: talkSearch ? ['web', 'x'] : undefined,
        bargeIn: true
      },
      {
        onState: setTalkState,
        onError: (e) => setTalkError(e),
        onPartial: setTalkPartial,
        onUserText: (t) => {
          talkAssistantOpen.current = false
          setTalkPartial('')
          setTalkLog((l) => [...l, { role: 'user', text: t }])
        },
        onAssistantDelta: (d) =>
          setTalkLog((l) => {
            if (talkAssistantOpen.current && l.length && l[l.length - 1].role === 'assistant') {
              const copy = l.slice()
              copy[copy.length - 1] = { role: 'assistant', text: copy[copy.length - 1].text + d }
              return copy
            }
            talkAssistantOpen.current = true
            return [...l, { role: 'assistant', text: d }]
          }),
        onAssistantDone: () => {
          talkAssistantOpen.current = false
        },
        onCitations: (urls) => setTalkCitations(urls),
        onCost: ({ ttsChars, ttsCost }) =>
          setUsage((u) => recordTts(u, { chars: ttsChars, cost: ttsCost })),
        onSttSeconds: (sec) => setUsage((u) => recordStt(u, { seconds: sec, streaming: true }))
      }
    )
    pipelineRef.current = pipeline
    pipeline.start()
  }

  // --- Realtime (Live) ---
  function toggleLive(): void {
    if (connected) {
      sessionRef.current?.stop()
      sessionRef.current = null
      setLiveStatus('Disconnected')
      return
    }
    setLiveError(null)
    setLiveLog([])
    assistantOpen.current = false
    const session = new RealtimeSession(
      conn,
      { voice, instructions, model: realtimeModel },
      {
        onStatus: setLiveStatus,
        onError: (e) => setLiveError(e),
        onUserText: (t) => {
          assistantOpen.current = false
          setLiveLog((l) => [...l, { role: 'user', text: t }])
        },
        onAssistantDelta: (d) =>
          setLiveLog((l) => {
            if (assistantOpen.current && l.length && l[l.length - 1].role === 'assistant') {
              const copy = l.slice()
              copy[copy.length - 1] = {
                role: 'assistant',
                text: copy[copy.length - 1].text + d
              }
              return copy
            }
            assistantOpen.current = true
            return [...l, { role: 'assistant', text: d }]
          }),
        onAssistantDone: () => {
          assistantOpen.current = false
        }
      }
    )
    sessionRef.current = session
    session.start()
  }

  async function copyTranscript(): Promise<void> {
    try {
      await navigator.clipboard.writeText(transcript)
    } catch {
      /* ignore */
    }
  }

  const voiceOptions = voices.length ? voices : [voice]
  const voiceLabel = (id: string): string => VOICES.find((v) => v.id === id)?.label || id
  const usageLabel = formatAudioUsage(usage)

  return (
    <Page title="Voice" subtitle="Dictate, talk with Caelo, transcribe, or read text aloud.">
      {/* Mode toggle + session cost (F5) */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-lg border border-border bg-surface-2 p-0.5">
          {MODES.map((m) => (
            <button
              key={m.id}
              onClick={() => setMode(m.id)}
              aria-pressed={mode === m.id}
              className={cn(
                'rounded-md px-3.5 py-1.5 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent',
                mode === m.id ? 'bg-surface text-fg shadow-sm' : 'text-muted hover:text-fg'
              )}
            >
              {m.label}
            </button>
          ))}
        </div>
        {usageLabel ? (
          <span
            title="Audio usage this session (BYO-key)"
            className="inline-flex items-center rounded-md bg-surface-2 px-2 py-0.5 text-[11px] font-medium text-muted"
          >
            {usageLabel}
          </span>
        ) : null}
      </div>

      {/* SPEAK (TTS) */}
      {mode === 'speak' ? (
        <>
          <Card>
            <Textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Type something for Caelo to read aloud…"
              rows={4}
              className="mb-4"
            />
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Voice" className="w-52">
                <Select size="sm" value={voice} onChange={(e) => setVoice(e.target.value)}>
                  {voiceOptions.map((v) => (
                    <option key={v} value={v}>
                      {voiceLabel(v)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Language" className="w-40">
                <Select size="sm" value={language} onChange={(e) => setLanguage(e.target.value)}>
                  {VOICE_LANGUAGES.map((l) => (
                    <option key={l.code} value={l.code}>
                      {l.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Button
                className="ml-auto"
                icon={<Volume2 size={16} />}
                onClick={speak}
                disabled={ttsBusy || !text.trim()}
              >
                {ttsBusy ? 'Synthesizing…' : 'Speak'}
              </Button>
            </div>
          </Card>
          {ttsError ? <p className="mt-4 text-sm text-error">{ttsError}</p> : null}
          {ttsAudio ? (
            <div className="mt-6 flex flex-wrap items-center gap-3">
              {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
              <audio src={ttsAudio.dataUrl} controls autoPlay className="w-full max-w-md" />
              {ttsAudio.path ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => window.caelo.openPath(ttsAudio.path as string)}
                >
                  Open file
                </Button>
              ) : null}
            </div>
          ) : null}
        </>
      ) : null}

      {/* TRANSCRIBE (STT) */}
      {mode === 'transcribe' ? (
        <>
          <Card>
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Language" className="w-40">
                <Select size="sm" value={language} onChange={(e) => setLanguage(e.target.value)}>
                  {VOICE_LANGUAGES.map((l) => (
                    <option key={l.code} value={l.code}>
                      {l.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Button
                icon={recording ? <Square size={16} /> : <Mic size={16} />}
                variant={recording ? 'outline' : 'primary'}
                onClick={toggleRecording}
                disabled={sttBusy}
              >
                {recording ? 'Stop & transcribe' : sttBusy ? 'Transcribing…' : 'Record'}
              </Button>
              {recording ? (
                <span className="flex items-center gap-2 text-sm text-error">
                  <span className="h-2 w-2 animate-pulse rounded-full bg-error" /> Recording…
                </span>
              ) : null}
            </div>
          </Card>
          {sttError ? <p className="mt-4 text-sm text-error">{sttError}</p> : null}
          {transcript ? (
            <Card className="mt-6">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-medium text-muted">Transcript</span>
                <Button variant="ghost" size="sm" icon={<Copy size={14} />} onClick={copyTranscript}>
                  Copy
                </Button>
              </div>
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{transcript}</p>
            </Card>
          ) : null}
        </>
      ) : null}

      {/* TALK (pipeline rozmowy: M12-B3/F2) */}
      {mode === 'talk' ? (
        <>
          <Card>
            <div className="mb-4 flex flex-wrap items-end gap-3">
              <Field label="Voice" className="w-52">
                <Select
                  size="sm"
                  value={voice}
                  onChange={(e) => setVoice(e.target.value)}
                  disabled={talkActive}
                >
                  {voiceOptions.map((v) => (
                    <option key={v} value={v}>
                      {voiceLabel(v)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Language" className="w-40">
                <Select
                  size="sm"
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  disabled={talkActive}
                >
                  {VOICE_LANGUAGES.map((l) => (
                    <option key={l.code} value={l.code}>
                      {l.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <label className="flex items-center gap-2 pb-1.5 text-sm text-fg">
                <input
                  type="checkbox"
                  checked={talkSearch}
                  onChange={(e) => setTalkSearch(e.target.checked)}
                  disabled={talkActive}
                  className="h-4 w-4 accent-[var(--accent)]"
                />
                Live search
              </label>
              <Button
                className="ml-auto"
                icon={talkActive ? <Square size={16} /> : <Mic size={16} />}
                variant={talkActive ? 'outline' : 'primary'}
                onClick={toggleTalk}
              >
                {talkActive ? 'End conversation' : 'Start conversation'}
              </Button>
            </div>
            <p className="flex items-center gap-2 text-xs text-muted">
              <span className={cn('h-2 w-2 rounded-full', TALK_STATE[talkState].dot)} />
              <span className="font-medium text-fg">{TALK_STATE[talkState].label}</span>
              {' · just start talking — your speech interrupts Caelo (barge-in).'}
            </p>
          </Card>
          {talkError ? <p className="mt-4 text-sm text-error">{talkError}</p> : null}
          {talkLog.length || talkPartial ? (
            <div className="mt-6 flex flex-col gap-4">
              {talkLog.map((entry, i) => (
                <div key={i} className={entry.role === 'user' ? 'flex justify-end' : ''}>
                  <div
                    className={cn(
                      'max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed',
                      entry.role === 'user' ? 'bg-surface-2' : 'bg-accent/10'
                    )}
                  >
                    {entry.text}
                  </div>
                </div>
              ))}
              {talkPartial ? (
                <div className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl bg-surface-2/60 px-4 py-2.5 text-sm italic leading-relaxed text-muted">
                    {talkPartial}…
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
          {talkCitations.length ? (
            <Card className="mt-4">
              <div className="mb-1.5 text-xs font-medium text-muted">Sources</div>
              <ul className="flex flex-col gap-1">
                {talkCitations.map((url, i) => (
                  <li key={i} className="truncate text-xs">
                    <a
                      href={url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-accent hover:underline"
                    >
                      {url}
                    </a>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
        </>
      ) : null}

      {/* LIVE (realtime / Voice Agent: M12-B4 stretch) */}
      {mode === 'live' ? (
        <>
          <Card>
            <div className="mb-4 flex flex-wrap items-end gap-3">
              <Field label="Voice" className="w-52">
                <Select
                  size="sm"
                  value={voice}
                  onChange={(e) => setVoice(e.target.value)}
                  disabled={connected}
                >
                  {voiceOptions.map((v) => (
                    <option key={v} value={v}>
                      {voiceLabel(v)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Button
                className="ml-auto"
                icon={connected ? <Square size={16} /> : <Mic size={16} />}
                variant={connected ? 'outline' : 'primary'}
                onClick={toggleLive}
              >
                {connected ? 'End conversation' : 'Start conversation'}
              </Button>
            </div>
            <Textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder="Optional instructions to steer the voice agent (e.g. Speak like a pirate)…"
              rows={2}
              disabled={connected}
            />
            <p className="mt-2 text-xs text-muted">
              Status: <span className="font-medium text-fg">{liveStatus}</span> · lowest-latency
              voice agent (no live-search/history — use Talk for those).
            </p>
          </Card>
          {liveError ? <p className="mt-4 text-sm text-error">{liveError}</p> : null}
          {liveLog.length ? (
            <div className="mt-6 flex flex-col gap-4">
              {liveLog.map((entry, i) => (
                <div key={i} className={entry.role === 'user' ? 'flex justify-end' : ''}>
                  <div
                    className={cn(
                      'max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed',
                      entry.role === 'user' ? 'bg-surface-2' : 'bg-accent/10'
                    )}
                  >
                    {entry.text}
                  </div>
                </div>
              ))}
            </div>
          ) : null}
        </>
      ) : null}
    </Page>
  )
}
