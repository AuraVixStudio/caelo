import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { AgentConnection, type AgentEvent } from '../../lib/agentClient'
import type { ChatAttachment, Conn } from '../../lib/api'
import { imageUris, inlineTextFiles } from '../../lib/attachments'
import { useHub } from '../../lib/hub'
import { inputBlockToAttachment } from '../../lib/sendTo'
import { useAttachments } from '../../lib/useAttachments'
import { cn } from '../../lib/cn'
import { Markdown } from '../Markdown'
import { AttachButton, AttachmentChips } from '../Attachments'
import { Button } from '../ui/Button'
import { ModelSelect } from '../ui/ModelSelect'
import { Textarea } from '../ui/Textarea'
import { DiffView } from './DiffView'

type Entry =
  | { kind: 'user'; id: string; text: string; attachments?: ChatAttachment[] }
  | { kind: 'assistant'; id: string; text: string }
  | { kind: 'error'; id: string; text: string }
  | {
      kind: 'tool'
      id: string
      name: string
      args: Record<string, unknown>
      status: 'pending' | 'awaiting' | 'done' | 'error'
      output: string
      summary: string
      detail?: { kind?: string; diff?: string; command?: string; cwd?: string }
    }

export function AgentPanel({
  conn,
  workspacePath,
  model,
  models,
  onModelChange,
  onFilesChanged
}: {
  conn: Conn
  workspacePath: string | null
  model: string
  models: string[]
  onModelChange: (m: string) => void
  onFilesChanged: () => void
}) {
  const [entries, setEntries] = useState<Entry[]>([])
  const [input, setInput] = useState('')
  const att = useAttachments() // P2-3: wspólny hook załączników
  const hub = useHub()
  const [busy, setBusy] = useState(false)
  const [connected, setConnected] = useState(false)

  const agentRef = useRef<AgentConnection | null>(null)
  const curAssistant = useRef<string | null>(null)
  const idRef = useRef(0)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  // Handler zdarzeń rejestrowany jest raz — onFilesChanged przez ref (świeży).
  const onFilesChangedRef = useRef(onFilesChanged)
  onFilesChangedRef.current = onFilesChanged

  const nextId = (): string => `e${++idRef.current}`

  function patchTool(id: string, patch: Partial<Extract<Entry, { kind: 'tool' }>>): void {
    setEntries((prev) =>
      prev.map((e) => (e.kind === 'tool' && e.id === id ? { ...e, ...patch } : e))
    )
  }

  // Połączenie WS agenta (jedno na sesję modułu Code).
  useEffect(() => {
    const agent = new AgentConnection(
      conn,
      () => {
        setConnected(true)
        if (workspacePath) agent.setWorkspace(workspacePath)
      },
      () => setConnected(false)
    )
    agentRef.current = agent

    const off = agent.on((e: AgentEvent) => handleEvent(e))
    return () => {
      off()
      agent.close()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conn.baseUrl, conn.token])

  // Zmiana workspace → poinformuj agenta.
  useEffect(() => {
    if (connected && workspacePath) agentRef.current?.setWorkspace(workspacePath)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspacePath, connected])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [entries])

  // M9-F2: „Send to → Code" — podnieś artefakt jako załącznik agenta (np. obraz),
  // a opcjonalny prompt wstaw do pola (bez kasowania tekstu użytkownika).
  useEffect(() => {
    const ps = hub.pendingSend
    if (!ps || ps.target !== 'Code') return
    const a = inputBlockToAttachment(ps.block)
    if (a) att.add(a)
    if (ps.prompt) setInput((prev) => prev || ps.prompt!)
    hub.setPendingSend(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hub.pendingSend])

  // P2-7: `e` to discriminated union (zwalidowany na granicy WS) — pola są już
  // poprawnych typów, więc bez `String(...)`/`as`; switch zawęża po `e.type`.
  function handleEvent(e: AgentEvent): void {
    switch (e.type) {
      case 'text': {
        const full = e.full
        if (curAssistant.current === null) {
          const id = nextId()
          curAssistant.current = id
          setEntries((prev) => [...prev, { kind: 'assistant', id, text: full }])
        } else {
          const id = curAssistant.current
          setEntries((prev) =>
            prev.map((x) => (x.id === id && x.kind === 'assistant' ? { ...x, text: full } : x))
          )
        }
        break
      }
      case 'tool_call': {
        curAssistant.current = null
        setEntries((prev) => [
          ...prev,
          {
            kind: 'tool',
            id: e.id,
            name: e.name,
            args: e.args,
            status: 'pending',
            output: '',
            summary: ''
          }
        ])
        break
      }
      case 'approval_request':
        patchTool(e.id, { status: 'awaiting', detail: e.detail })
        break
      case 'output':
        setEntries((prev) =>
          prev.map((x) =>
            x.kind === 'tool' && x.id === e.id ? { ...x, output: x.output + e.chunk } : x
          )
        )
        break
      case 'tool_result':
        patchTool(e.id, { status: e.ok ? 'done' : 'error', summary: e.summary })
        break
      case 'assistant_done': {
        const content = e.content
        const id = curAssistant.current
        if (id) {
          setEntries((prev) =>
            prev.map((x) =>
              x.id === id && x.kind === 'assistant' ? { ...x, text: content || x.text } : x
            )
          )
        } else if (content) {
          setEntries((prev) => [...prev, { kind: 'assistant', id: nextId(), text: content }])
        }
        curAssistant.current = null
        break
      }
      case 'stopped':
        setBusy(false)
        break
      case 'done':
        setBusy(false)
        onFilesChangedRef.current()
        break
      case 'error':
        setEntries((prev) => [...prev, { kind: 'error', id: nextId(), text: e.error }])
        setBusy(false)
        break
      case 'workspace':
        break // potwierdzenie ustawienia katalogu — obsługiwane po stronie CodeView
      default:
        break
    }
  }

  function send(): void {
    const text = input.trim()
    if ((!text && att.attachments.length === 0) || busy || !connected) return
    if (!workspacePath) {
      setEntries((prev) => [...prev, { kind: 'error', id: nextId(), text: 'Open a folder first.' }])
      return
    }
    const atts = att.attachments
    setEntries((prev) => [
      ...prev,
      { kind: 'user', id: nextId(), text, attachments: atts.length ? atts : undefined }
    ])
    curAssistant.current = null
    setBusy(true)
    setInput('')
    att.clear()
    agentRef.current?.sendMessage(inlineTextFiles(text, atts), model, imageUris(atts))
  }

  function approve(id: string, decision: 'accept' | 'reject' | 'always'): void {
    patchTool(id, { status: 'pending' })
    agentRef.current?.approve(id, decision)
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>): void {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-3">
        <span className="text-sm font-semibold">Agent</span>
        <div className="ml-1 min-w-0 flex-1">
          <ModelSelect value={model} models={models} onChange={onModelChange} />
        </div>
        <span
          title={connected ? 'connected' : 'disconnected'}
          className={cn('h-2 w-2 shrink-0 rounded-full', connected ? 'bg-success' : 'bg-muted')}
        />
      </header>

      <div
        className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3"
        ref={scrollRef}
        role="log"
        aria-live="polite"
        aria-label="Agent activity"
      >
        {entries.length === 0 ? (
          <p className="text-xs text-muted">
            Ask the agent to read, edit or run code in the workspace.
          </p>
        ) : (
          entries.map((e) => <EntryView key={e.id} entry={e} onApprove={approve} />)
        )}
      </div>

      <div className="shrink-0 border-t border-border p-2.5">
        <AttachmentChips items={att.attachments} onRemove={att.removeAttachment} className="mb-2" />
        <div className="flex items-end gap-2">
          <AttachButton
            onPick={att.addFiles}
            disabled={!connected}
            className="h-8 w-8 rounded-lg"
          />
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={workspacePath ? 'Ask the agent…' : 'Open a folder to start…'}
            rows={2}
            disabled={!connected}
            className="flex-1 text-[13px]"
          />
          {busy ? (
            <Button variant="danger" size="sm" onClick={() => agentRef.current?.stop()}>
              Stop
            </Button>
          ) : (
            <Button
              size="sm"
              onClick={send}
              disabled={(!input.trim() && att.attachments.length === 0) || !connected}
            >
              Send
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

function EntryView({
  entry,
  onApprove
}: {
  entry: Entry
  onApprove: (id: string, decision: 'accept' | 'reject' | 'always') => void
}) {
  if (entry.kind === 'user') {
    return (
      <div>
        <div className="mb-1 text-[10px] font-bold uppercase tracking-wide text-muted">You</div>
        {entry.text ? (
          <div className="whitespace-pre-wrap break-words rounded-lg bg-surface-2 px-3 py-2 text-[13px]">
            {entry.text}
          </div>
        ) : null}
        {entry.attachments?.length ? (
          <AttachmentChips items={entry.attachments} className="mt-1.5" />
        ) : null}
      </div>
    )
  }
  if (entry.kind === 'assistant') {
    return (
      <div>
        <div className="mb-1 text-[10px] font-bold uppercase tracking-wide text-muted">Grok</div>
        {entry.text ? (
          <Markdown text={entry.text} />
        ) : (
          <span className="text-lg leading-none tracking-widest text-muted">…</span>
        )}
      </div>
    )
  }
  if (entry.kind === 'error') {
    return <div className="text-[13px] text-error">⚠️ {entry.text}</div>
  }

  // tool
  const argSummary =
    entry.name === 'run_command'
      ? String(entry.args.command ?? '')
      : String(entry.args.path ?? JSON.stringify(entry.args))
  return (
    <div
      className={cn(
        'overflow-hidden rounded-lg border text-xs',
        entry.status === 'awaiting'
          ? 'border-warn'
          : entry.status === 'error'
            ? 'border-error'
            : 'border-border'
      )}
    >
      <div className="flex items-center gap-2 bg-surface-2 px-2.5 py-1.5">
        <span className="font-bold text-accent">{entry.name}</span>
        <span className="min-w-0 flex-1 truncate font-mono text-muted" title={argSummary}>
          {argSummary}
        </span>
        <span className="shrink-0 text-[10px] uppercase text-muted">{entry.status}</span>
      </div>

      {entry.status === 'awaiting' && entry.detail ? (
        <div className="flex flex-col gap-2 p-2.5">
          {entry.detail.kind === 'diff' ? (
            <DiffView diff={entry.detail.diff ?? ''} />
          ) : entry.detail.kind === 'command' ? (
            <pre className="m-0 whitespace-pre-wrap rounded-md bg-surface-2 px-2.5 py-2 font-mono text-xs text-fg/90">
              $ {entry.detail.command}
              {entry.detail.cwd ? `   (cwd: ${entry.detail.cwd})` : ''}
            </pre>
          ) : null}
          <div className="flex gap-2">
            <Button size="sm" onClick={() => onApprove(entry.id, 'accept')}>
              Accept
            </Button>
            <Button variant="danger" size="sm" onClick={() => onApprove(entry.id, 'reject')}>
              Reject
            </Button>
            <Button variant="outline" size="sm" onClick={() => onApprove(entry.id, 'always')}>
              Always allow
            </Button>
          </div>
        </div>
      ) : null}

      {entry.output ? (
        <pre className="m-0 max-h-44 overflow-auto whitespace-pre-wrap bg-surface-3/40 px-2.5 py-2 font-mono text-[11.5px]">
          {entry.output.slice(-4000)}
        </pre>
      ) : null}
      {entry.summary && entry.status !== 'awaiting' ? (
        <div className="whitespace-pre-wrap border-t border-border px-2.5 py-1.5 font-mono text-[11.5px] text-muted">
          {entry.summary}
        </div>
      ) : null}
    </div>
  )
}
