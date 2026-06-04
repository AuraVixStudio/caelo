import {
  memo,
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent
} from 'react'
import { Group, Panel, useDefaultLayout, usePanelRef } from 'react-resizable-panels'
import {
  ArrowUp,
  Copy,
  Mic,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  SlidersHorizontal,
  Sparkles,
  Square,
  Volume2,
  X
} from 'lucide-react'
import { type ChatMessage, type Conn } from '../lib/api'
import { saveSettings, useModels, useSettings } from '../lib/serverState'
import { toApiMessages } from '../lib/attachments'
import { useAttachments } from '../lib/useAttachments'
import { useChatStream } from '../lib/useChatStream'
import { useConversations } from '../lib/useConversations'
import { useDictation } from '../lib/useDictation'
import { useTts } from '../lib/useTts'
import { AttachButton, AttachmentChips } from './Attachments'
import { titleFromText } from '../lib/storage'
import { cn } from '../lib/cn'
import { Markdown } from './Markdown'
import { Button } from './ui/Button'
import { IconButton } from './ui/IconButton'
import { ModelSelect } from './ui/ModelSelect'
import { Popover } from './ui/Popover'
import { ResizeHandle } from './ui/ResizeHandle'
import { Textarea } from './ui/Textarea'

function updateLastAssistant(messages: ChatMessage[], content: string): ChatMessage[] {
  const out = messages.slice()
  for (let i = out.length - 1; i >= 0; i--) {
    if (out[i].role === 'assistant') {
      out[i] = { ...out[i], content }
      break
    }
  }
  return out
}

/**
 * Pojedynczy wiersz czatu (P2-4). `memo` + stabilne propsy (`onCopy`/`onSpeak`
 * przez useCallback/useTts, `isSpeaking` jako bool zamiast całego ttsIdx) sprawiają,
 * że podczas streamingu odświeża się TYLKO ostatnia (zmieniana) wiadomość, a nie
 * wszystkie Markdowny. Klucze po indeksie są tu bezpieczne — lista rośnie tylko na
 * końcu, a edytowana jest wyłącznie ostatnia wiadomość (brak wstawień w środku).
 */
const ChatMessageRow = memo(function ChatMessageRow({
  message,
  index,
  isSpeaking,
  onCopy,
  onSpeak
}: {
  message: ChatMessage
  index: number
  isSpeaking: boolean
  onCopy: (content: string) => void
  onSpeak: (idx: number, content: string) => void
}) {
  const m = message
  if (m.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="group relative max-w-[85%] rounded-2xl bg-surface-2 px-4 py-2.5">
          {m.content ? (
            <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">
              {m.content}
            </div>
          ) : null}
          {m.attachments?.length ? (
            <AttachmentChips items={m.attachments} className="mt-2" />
          ) : null}
          {m.content ? (
            <button
              onClick={() => onCopy(m.content)}
              aria-label="Copy message"
              className="absolute -right-1 -top-1 flex h-6 w-6 items-center justify-center rounded-md bg-surface text-muted opacity-0 shadow-sm outline-none transition-opacity hover:text-fg focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-accent group-hover:opacity-100"
              title="Copy"
            >
              <Copy size={13} />
            </button>
          ) : null}
        </div>
      </div>
    )
  }
  return (
    <div className="group relative">
      <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-muted">
        <span className="flex h-5 w-5 items-center justify-center rounded-md bg-accent/15 text-accent">
          <Sparkles size={12} />
        </span>
        Grok
      </div>
      {m.content ? (
        <Markdown text={m.content} />
      ) : (
        <span className="text-2xl leading-none tracking-widest text-muted">…</span>
      )}
      {m.content ? (
        <div className="absolute right-0 top-0 flex items-center gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
          <button
            onClick={() => onSpeak(index, m.content)}
            aria-label={isSpeaking ? 'Stop reading aloud' : 'Read message aloud'}
            className="flex h-7 items-center rounded-md px-2 text-xs text-muted outline-none hover:bg-surface-2 hover:text-fg focus-visible:ring-2 focus-visible:ring-accent"
            title={isSpeaking ? 'Stop' : 'Read aloud'}
          >
            {isSpeaking ? <Square size={13} /> : <Volume2 size={13} />}
          </button>
          <button
            onClick={() => onCopy(m.content)}
            aria-label="Copy message"
            className="flex h-7 items-center gap-1 rounded-md px-2 text-xs text-muted outline-none hover:bg-surface-2 hover:text-fg focus-visible:ring-2 focus-visible:ring-accent"
            title="Copy"
          >
            <Copy size={13} /> Copy
          </button>
        </div>
      ) : null}
    </div>
  )
})

export function ChatView({ conn }: { conn: Conn }) {
  const [input, setInput] = useState('')
  const [error, setError] = useState<string | null>(null)

  const [models, setModels] = useState<string[]>([])
  const [model, setModel] = useState<string>('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [temperature, setTemperature] = useState(0.7)

  // Voice: czytanie odpowiedzi na głos (TTS → useTts); dyktowanie promptu (STT → useDictation).
  const [defaultVoice, setDefaultVoice] = useState('eve')

  const scrollRef = useRef<HTMLDivElement | null>(null)
  const taRef = useRef<HTMLTextAreaElement | null>(null)

  // P2-2: współdzielony cache zamiast osobnych GET-ów /models i /settings.
  const { models: modelsResp } = useModels(conn)
  const { settings } = useSettings(conn)
  const settingsInit = useRef(false)

  // P2-3/P2-4: logika wydzielona do hooków (stabilne callbacki dla memoizacji wierszy).
  const convo = useConversations()
  const att = useAttachments()
  const stream = useChatStream(conn)
  const tts = useTts(conn, defaultVoice)
  const dictation = useDictation(conn, (t) => {
    setInput((prev) => (prev ? prev + ' ' : '') + t)
    taRef.current?.focus()
  })

  const { defaultLayout, onLayoutChanged } = useDefaultLayout({ id: 'grok.chat' })
  const convosPanelRef = usePanelRef()
  const [convosCollapsed, setConvosCollapsed] = useState(false)

  function toggleConvos(): void {
    const p = convosPanelRef.current
    if (!p) return
    if (p.isCollapsed()) p.expand()
    else p.collapse()
  }

  // Modele: idempotentne (prev || …), więc bezpieczne na każdą zmianę cache.
  useEffect(() => {
    if (!modelsResp) return
    setModels(modelsResp.chat)
    setModel((prev) => prev || modelsResp.default_chat)
    if (modelsResp.default_voice) setDefaultVoice(modelsResp.default_voice)
  }, [modelsResp])

  // Ustawienia: zaaplikuj RAZ (system_prompt/temperature są edytowalne — kolejne
  // odświeżenia cache nie mogą nadpisać niezapisanych zmian użytkownika).
  useEffect(() => {
    if (!settings || settingsInit.current) return
    settingsInit.current = true
    setSystemPrompt(settings.system_prompt || '')
    setTemperature(typeof settings.chat_temperature === 'number' ? settings.chat_temperature : 0.7)
    setModel((prev) => prev || settings.chat_model)
  }, [settings])

  // Auto-scroll na dół przy zmianie treści.
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [convo.active?.messages])

  function send(): void {
    const text = input.trim()
    if ((!text && att.attachments.length === 0) || stream.streaming) return
    setError(null)

    const userMsg: ChatMessage = {
      role: 'user',
      content: text,
      attachments: att.attachments.length ? att.attachments : undefined
    }
    const history = [...(convo.active?.messages || []), userMsg]

    convo.patchActive((c) => ({
      ...c,
      title:
        c.title === 'New chat'
          ? titleFromText(text || att.attachments[0]?.name || 'Attachment')
          : c.title,
      messages: [...c.messages, userMsg, { role: 'assistant', content: '' }]
    }))
    setInput('')
    att.clear()
    if (taRef.current) taRef.current.style.height = 'auto'

    stream.start(
      { messages: toApiMessages(history), model, temperature, system_prompt: systemPrompt },
      {
        onDelta: (full) =>
          convo.patchActive((c) => ({ ...c, messages: updateLastAssistant(c.messages, full) })),
        onDone: (full) =>
          convo.patchActive((c) => ({ ...c, messages: updateLastAssistant(c.messages, full) })),
        onError: (err) => {
          setError(err)
          convo.patchActive((c) => ({
            ...c,
            messages: updateLastAssistant(c.messages, `⚠️ ${err}`)
          }))
        }
      }
    )
  }

  function onModelChange(value: string): void {
    setModel(value)
    void saveSettings(conn, { chat_model: value }).catch(() => undefined)
  }

  function saveChatSettings(): void {
    void saveSettings(conn, { system_prompt: systemPrompt, chat_temperature: temperature }).catch(
      () => undefined
    )
  }

  function newChat(): void {
    convo.createChat()
    setInput('')
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>): void {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  function autoGrow(e: FormEvent<HTMLTextAreaElement>): void {
    const el = e.currentTarget
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }

  // Stabilny callback (P2-4) — wiersze czatu są zmemoizowane, więc onCopy nie może
  // zmieniać tożsamości między renderami (TTS przez stabilne `tts.speak` z useTts).
  const copyMessage = useCallback(async (content: string): Promise<void> => {
    try {
      await navigator.clipboard.writeText(content)
    } catch {
      /* ignore */
    }
  }, [])

  const messages = convo.active?.messages || []
  const displayError = error || convo.saveError

  return (
    <Group
      orientation="horizontal"
      defaultLayout={defaultLayout}
      onLayoutChanged={onLayoutChanged}
      className="min-w-0 flex-1"
    >
      {/* Lista rozmów */}
      <Panel
        id="convos"
        panelRef={convosPanelRef}
        defaultSize="22%"
        minSize="15%"
        maxSize="36%"
        collapsible
        collapsedSize="0%"
        onResize={(size) => setConvosCollapsed(size.asPercentage <= 0.5)}
        style={{ overflow: 'hidden' }}
        className="flex min-h-0 flex-col bg-surface"
      >
        <div className="shrink-0 p-2.5">
          <Button
            variant="subtle"
            className="w-full justify-start"
            icon={<Plus size={16} />}
            onClick={newChat}
          >
            New chat
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto px-2 pb-2">
          {convo.convos.map((c) => {
            const isActive = c.id === convo.activeId
            return (
              <div
                key={c.id}
                className={cn(
                  'group flex items-center gap-1 rounded-lg pr-1 text-sm transition-colors',
                  isActive ? 'bg-surface-2 text-fg' : 'text-muted hover:bg-surface-2 hover:text-fg'
                )}
              >
                {/* P2-6: realny <button> zamiast klikalnego <div> (fokus + Enter/Space). */}
                <button
                  onClick={() => convo.setActiveId(c.id)}
                  aria-current={isActive ? 'true' : undefined}
                  className="min-w-0 flex-1 truncate rounded-lg px-2.5 py-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  {c.title}
                </button>
                <button
                  aria-label={`Delete chat: ${c.title}`}
                  title="Delete"
                  onClick={() => convo.deleteChat(c.id)}
                  className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-muted opacity-0 outline-none transition-opacity hover:text-error focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-accent group-hover:opacity-100"
                >
                  <X size={14} />
                </button>
              </div>
            )
          })}
        </div>
      </Panel>

      <ResizeHandle orientation="horizontal" />

      {/* Główny panel */}
      <Panel
        id="main"
        minSize="40%"
        style={{ overflow: 'hidden' }}
        className="flex min-h-0 flex-col bg-bg"
      >
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-4">
          <IconButton
            label={convosCollapsed ? 'Show chats' : 'Hide chats'}
            icon={convosCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
            onClick={toggleConvos}
          />
          <span className="text-xs font-medium text-muted">Model</span>
          <div className="w-52">
            <ModelSelect value={model} models={models} onChange={onModelChange} />
          </div>
          <div className="ml-auto">
            <Popover
              align="end"
              label="System & temperature"
              trigger={({ toggle, open, triggerProps }) => (
                <IconButton
                  label="System & temperature"
                  icon={<SlidersHorizontal size={18} />}
                  active={open}
                  tooltip={!open}
                  tooltipSide="bottom-end"
                  onClick={toggle}
                  {...triggerProps}
                />
              )}
            >
              {(close) => (
                <div className="w-80 p-1.5">
                  <label className="mb-1.5 block text-xs font-medium text-muted">System prompt</label>
                  <Textarea
                    rows={4}
                    value={systemPrompt}
                    onChange={(e) => setSystemPrompt(e.target.value)}
                    placeholder="Optional instructions that steer the assistant…"
                  />
                  <label className="mb-1.5 mt-3 block text-xs font-medium text-muted">
                    Temperature: {temperature.toFixed(2)}
                  </label>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={temperature}
                    onChange={(e) => setTemperature(parseFloat(e.target.value))}
                    className="w-full accent-accent"
                  />
                  <div className="mt-3 flex justify-end">
                    <Button
                      size="sm"
                      onClick={() => {
                        saveChatSettings()
                        close()
                      }}
                    >
                      Save
                    </Button>
                  </div>
                </div>
              )}
            </Popover>
          </div>
        </header>

        {messages.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center px-4 text-center">
            <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/12 text-accent">
              <Sparkles size={26} />
            </div>
            <h2 className="text-xl font-semibold">Start a conversation</h2>
            <p className="mt-1.5 text-sm text-muted">
              Streaming chat powered by Grok via the local backend.
            </p>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto" ref={scrollRef}>
            <div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6">
              {messages.map((m, i) => (
                <ChatMessageRow
                  key={i}
                  message={m}
                  index={i}
                  isSpeaking={tts.speakingIdx === i}
                  onCopy={copyMessage}
                  onSpeak={tts.speak}
                />
              ))}
            </div>
          </div>
        )}

        {displayError ? <div className="px-4 pb-1 text-xs text-error">{displayError}</div> : null}

        <div className="shrink-0 px-4 pb-5 pt-2">
          <div className="mx-auto max-w-3xl">
            <AttachmentChips items={att.attachments} onRemove={att.removeAttachment} className="mb-2" />
            <div className="flex items-end gap-2 rounded-2xl border border-border bg-surface px-3 py-2 shadow-[var(--shadow)] transition-colors focus-within:border-border-strong">
              <AttachButton onPick={att.addFiles} />
              <textarea
              ref={taRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onInput={autoGrow}
              onKeyDown={onKeyDown}
              placeholder="Message Grok…"
              rows={1}
              className="max-h-52 flex-1 resize-none bg-transparent py-1.5 text-sm leading-relaxed text-fg outline-none placeholder:text-muted"
            />
            <button
              onClick={dictation.toggle}
              disabled={dictation.busy}
              aria-label={
                dictation.recording
                  ? 'Stop dictation and transcribe'
                  : dictation.busy
                    ? 'Transcribing'
                    : 'Dictate a message'
              }
              title={
                dictation.recording
                  ? 'Stop & transcribe'
                  : dictation.busy
                    ? 'Transcribing…'
                    : 'Dictate'
              }
              className={cn(
                'flex h-9 w-9 shrink-0 items-center justify-center rounded-xl outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50',
                dictation.recording
                  ? 'bg-error text-white hover:opacity-90'
                  : 'text-muted hover:bg-surface-2 hover:text-fg'
              )}
            >
              {dictation.recording ? <Square size={16} /> : <Mic size={18} />}
            </button>
            {stream.streaming ? (
              <button
                onClick={stream.stop}
                aria-label="Stop generating"
                title="Stop"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-error text-white outline-none transition-opacity hover:opacity-90 focus-visible:ring-2 focus-visible:ring-accent"
              >
                <Square size={16} fill="currentColor" />
              </button>
            ) : (
              <button
                onClick={send}
                disabled={!input.trim() && att.attachments.length === 0}
                aria-label="Send message"
                title="Send"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent text-accent-fg outline-none transition-colors hover:bg-accent-hover focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-40"
              >
                <ArrowUp size={18} />
              </button>
            )}
            </div>
            <p className="mt-2 text-center text-[11px] text-muted">
              Enter to send · Shift+Enter for newline
            </p>
          </div>
        </div>
      </Panel>
    </Group>
  )
}
