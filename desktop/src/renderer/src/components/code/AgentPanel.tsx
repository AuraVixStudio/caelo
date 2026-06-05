import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { Check, ChevronDown, History, ListChecks, Mic, Pencil, Play, ShieldCheck, Square, Undo2, Zap } from 'lucide-react'
import { AgentConnection, type AgentEvent, type ApprovalDetail } from '../../lib/agentClient'
import {
  agentUndo,
  applyTeamMerge,
  listCheckpoints,
  listTeamMerges,
  rejectTeamMerge,
  type ChatAttachment,
  type CheckpointInfo,
  type Conn,
  type TeamMerge,
  type TeamReport
} from '../../lib/api'
import {
  addApproval,
  applyEvent,
  applyStatus,
  clearApproval,
  type SubAgentMap
} from '../../lib/teamView'
import { TeamView } from './TeamView'
import {
  AGENT_MODES,
  canApproveRun,
  checkpointSubtitle,
  checkpointTitle,
  modeBanner,
  modeInfo,
  partialUndoNote,
  planReducer,
  undoSummary,
  type AgentMode,
  type PlanPhase
} from '../../lib/agentTrust'
import { imageUris, inlineTextFiles } from '../../lib/attachments'
import { useHub } from '../../lib/hub'
import { inputBlockToAttachment } from '../../lib/sendTo'
import { useAttachments } from '../../lib/useAttachments'
import { appendDictation, useDictation } from '../../lib/useDictation'
import { cn } from '../../lib/cn'
import { Markdown } from '../Markdown'
import { AttachButton, AttachmentChips } from '../Attachments'
import { Button } from '../ui/Button'
import { IconButton } from '../ui/IconButton'
import { ModelSelect } from '../ui/ModelSelect'
import { Popover } from '../ui/Popover'
import { Textarea } from '../ui/Textarea'
import { DiffView } from './DiffView'

function modeIcon(id: AgentMode, size = 14): ReactNode {
  switch (id) {
    case 'accept-edits':
      return <Pencil size={size} />
    case 'plan':
      return <ListChecks size={size} />
    case 'bypass':
      return <Zap size={size} />
    default:
      return <ShieldCheck size={size} />
  }
}

type Entry =
  | { kind: 'user'; id: string; text: string; attachments?: ChatAttachment[] }
  | { kind: 'assistant'; id: string; text: string }
  | { kind: 'error'; id: string; text: string }
  | { kind: 'info'; id: string; text: string; tone: 'info' | 'warn' }
  | {
      kind: 'tool'
      id: string
      name: string
      args: Record<string, unknown>
      status: 'pending' | 'awaiting' | 'done' | 'error'
      output: string
      summary: string
      detail?: ApprovalDetail
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
  // M12-F1: dyktowanie promptu agenta (2. tryb po czacie) — wspólny hook STT.
  const dictation = useDictation(conn, (t) => setInput((prev) => appendDictation(prev, t)))
  const att = useAttachments() // P2-3: wspólny hook załączników
  const hub = useHub()
  const [busy, setBusy] = useState(false)
  const [connected, setConnected] = useState(false)
  const [dragging, setDragging] = useState(false) // M9-F4: drop plików do composera
  // M13-F2: tryb agenta (ask/accept-edits/plan/bypass) + faza cyklu plan → review → execute.
  const [mode, setMode] = useState<AgentMode>('ask')
  const [planPhase, setPlanPhase] = useState<PlanPhase>('idle')
  // M13-F3: oś checkpointów sesji + flaga „partial undo".
  const [checkpoints, setCheckpoints] = useState<CheckpointInfo[]>([])
  const [partial, setPartial] = useState(false)
  const [undoing, setUndoing] = useState(false)
  // M17-F1/F2/F5: drzewo subagentów, oczekujące scalenia worktree, ostatni raport zespołu.
  const [teamNodes, setTeamNodes] = useState<SubAgentMap>({})
  const [merges, setMerges] = useState<TeamMerge[]>([])
  const [teamReport, setTeamReport] = useState<TeamReport | null>(null)

  const agentRef = useRef<AgentConnection | null>(null)
  const curAssistant = useRef<string | null>(null)
  const idRef = useRef(0)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  // Handlery rejestrowane są raz — świeże wersje przez refy.
  const onFilesChangedRef = useRef(onFilesChanged)
  onFilesChangedRef.current = onFilesChanged
  const turnWasPlanRef = useRef(false)

  const nextId = (): string => `e${++idRef.current}`

  function patchTool(id: string, patch: Partial<Extract<Entry, { kind: 'tool' }>>): void {
    setEntries((prev) =>
      prev.map((e) => (e.kind === 'tool' && e.id === id ? { ...e, ...patch } : e))
    )
  }

  function pushInfo(text: string, tone: 'info' | 'warn' = 'info'): void {
    setEntries((prev) => [...prev, { kind: 'info', id: nextId(), text, tone }])
  }

  // M13-F3: pobierz aktualną oś checkpointów z backendu (autorytatywne źródło).
  const refreshCheckpoints = (): void => {
    void listCheckpoints(conn)
      .then((r) => {
        setCheckpoints(r.checkpoints)
        setPartial(r.partial)
      })
      .catch(() => undefined)
  }
  const refreshCheckpointsRef = useRef(refreshCheckpoints)
  refreshCheckpointsRef.current = refreshCheckpoints

  // M17-F2: pobierz oczekujące scalenia worktree (autorytatywne źródło, jak checkpointy).
  const refreshMerges = (): void => {
    void listTeamMerges(conn)
      .then((r) => setMerges(r.merges))
      .catch(() => undefined)
  }
  const refreshMergesRef = useRef(refreshMerges)
  refreshMergesRef.current = refreshMerges

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

  // Zmiana workspace → poinformuj agenta i odśwież checkpointy nowego workspace.
  useEffect(() => {
    if (connected && workspacePath) {
      agentRef.current?.setWorkspace(workspacePath)
      refreshCheckpointsRef.current()
      refreshMergesRef.current()
      setTeamNodes({}) // nowy workspace → nowe drzewo zespołu
      setTeamReport(null)
    }
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
        // M17-F3: zatwierdzenie subagenta (detail.agent_id) → karta w jego węźle,
        // nie w głównym strumieniu (atrybucja). Orkiestrator → dotychczasowa ścieżka.
        if (e.detail?.agent_id) {
          setTeamNodes((m) => addApproval(m, e.id, e.name, e.detail))
        } else {
          patchTool(e.id, { status: 'awaiting', detail: e.detail })
        }
        break
      case 'subagent':
        // M17-F1: zagnieżdżona ramka subagenta → aktualizuj jego węzeł w drzewie.
        setTeamNodes((m) => applyEvent(m, e.agent_id, e.role, e.task, e.event))
        break
      case 'subagent_status':
        setTeamNodes((m) => applyStatus(m, e))
        if (e.merge_id) refreshMergesRef.current() // pojawiło się scalenie do przeglądu
        break
      case 'team_done':
        setTeamReport(e.report)
        refreshMergesRef.current()
        break
      case 'checkpoint':
        // M13-F3: agent zsnapshotował pliki → odśwież oś checkpointów.
        refreshCheckpointsRef.current()
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
        setPlanPhase((p) => planReducer(p, { type: 'done' }))
        break
      case 'done':
        setBusy(false)
        // M13-F2: po planie → faza review (pokaż „Approve & run"); po wykonaniu → idle.
        setPlanPhase((p) => planReducer(p, { type: 'done' }))
        refreshCheckpointsRef.current()
        refreshMergesRef.current() // M17: subagenci mogli przygotować scalenia
        onFilesChangedRef.current()
        break
      case 'error':
        setEntries((prev) => [...prev, { kind: 'error', id: nextId(), text: e.error }])
        setBusy(false)
        setPlanPhase((p) => planReducer(p, { type: 'done' }))
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
    const usePlan = mode === 'plan'
    const atts = att.attachments
    setEntries((prev) => [
      ...prev,
      { kind: 'user', id: nextId(), text, attachments: atts.length ? atts : undefined }
    ])
    curAssistant.current = null
    turnWasPlanRef.current = usePlan
    setPlanPhase((p) => planReducer(p, { type: 'send', plan: usePlan }))
    setBusy(true)
    setInput('')
    att.clear()
    agentRef.current?.sendMessage(inlineTextFiles(text, atts), model, imageUris(atts), mode)
  }

  // M13-F2: zatwierdź plan i wykonaj go w trybie „accept edits" (plan był sprawdzony).
  function approveAndRun(): void {
    if (busy || !connected || !workspacePath) return
    const text = 'Proceed with the plan above and make the changes.'
    setMode('accept-edits')
    setPlanPhase((p) => planReducer(p, { type: 'approveRun' }))
    setEntries((prev) => [...prev, { kind: 'user', id: nextId(), text }])
    curAssistant.current = null
    turnWasPlanRef.current = false
    setBusy(true)
    agentRef.current?.sendMessage(text, model, [], 'accept-edits')
  }

  function approve(id: string, decision: 'accept' | 'reject' | 'always'): void {
    patchTool(id, { status: 'pending' })
    agentRef.current?.approve(id, decision)
  }

  // M17-F3: decyzja na karcie zatwierdzenia subagenta (id znamespace'owany).
  function approveTeam(id: string, decision: 'accept' | 'reject' | 'always'): void {
    setTeamNodes((m) => clearApproval(m, id))
    agentRef.current?.approve(id, decision)
  }

  // M17-F2: scal/odrzuć zmiany worktree subagenta (jeden diff).
  async function applyMerge(id: string): Promise<void> {
    try {
      await applyTeamMerge(conn, id)
      pushInfo('Merged subagent changes into the workspace.')
      onFilesChangedRef.current()
      refreshCheckpointsRef.current() // merge tworzy checkpoint (cofalne)
    } catch {
      pushInfo('Merge failed.', 'warn')
    } finally {
      refreshMergesRef.current()
    }
  }

  async function rejectMerge(id: string): Promise<void> {
    try {
      await rejectTeamMerge(conn, id)
      pushInfo('Discarded the subagent worktree.')
    } catch {
      pushInfo('Discard failed.', 'warn')
    } finally {
      refreshMergesRef.current()
    }
  }

  // M13-F3: cofnij wskazany checkpoint (lub całą sesję, gdy brak id).
  async function undo(checkpointId?: string): Promise<void> {
    if (undoing || busy) return
    setUndoing(true)
    try {
      const r = await agentUndo(conn, checkpointId)
      pushInfo(undoSummary(r), r.partial ? 'warn' : 'info')
      const note = partialUndoNote(r.partial)
      if (note) pushInfo(note, 'warn')
      refreshCheckpointsRef.current()
      onFilesChangedRef.current() // odśwież drzewo + otwarte pliki w edytorze
    } catch {
      pushInfo('Undo failed.', 'warn')
    } finally {
      setUndoing(false)
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>): void {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const showApproveRun = canApproveRun(planPhase, busy)
  const banner = modeBanner(mode)

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-3">
        <span className="text-sm font-semibold">Agent</span>
        <div className="ml-1 min-w-0 flex-1">
          <ModelSelect value={model} models={models} onChange={onModelChange} />
        </div>
        <Popover
          align="end"
          label="Checkpoints"
          trigger={({ toggle, open, triggerProps }) => (
            <IconButton
              label="Checkpoints & undo"
              icon={<History size={18} />}
              active={open}
              tooltip={!open}
              tooltipSide="bottom-end"
              onClick={() => {
                refreshCheckpoints()
                toggle()
              }}
              {...triggerProps}
            />
          )}
        >
          {(close) => (
            <CheckpointsMenu
              checkpoints={checkpoints}
              partial={partial}
              undoing={undoing}
              onUndo={(id) => {
                void undo(id)
                close()
              }}
            />
          )}
        </Popover>
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

      <TeamView
        nodes={teamNodes}
        merges={merges}
        report={teamReport}
        conn={conn}
        onApprove={approveTeam}
        onApplyMerge={(id) => void applyMerge(id)}
        onRejectMerge={(id) => void rejectMerge(id)}
        busy={busy}
      />

      {showApproveRun ? (
        <div className="shrink-0 border-t border-border bg-accent/5 px-3 py-2">
          <div className="flex items-center gap-2">
            <span className="min-w-0 flex-1 text-xs text-muted">
              Plan ready — review the steps above, then run it.
            </span>
            <Button size="sm" icon={<Play size={14} />} onClick={approveAndRun}>
              Approve &amp; run
            </Button>
          </div>
        </div>
      ) : null}

      <div
        onDragOver={(e) => {
          if (!connected) return
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          if (connected) void att.addFiles(e.dataTransfer.files)
        }}
        className={cn(
          'shrink-0 border-t p-2.5 transition-colors',
          dragging ? 'border-accent' : 'border-border'
        )}
      >
        {banner ? (
          <div
            className={cn(
              'mb-2 rounded-md px-2.5 py-1.5 text-[11.5px]',
              banner.tone === 'warn' ? 'bg-warn/10 text-warn' : 'bg-surface-2 text-muted'
            )}
          >
            {banner.text}
          </div>
        ) : null}
        <AttachmentChips items={att.attachments} onRemove={att.removeAttachment} className="mb-2" />
        <div className="flex items-end gap-2">
          <ModeSelector mode={mode} disabled={false} onSelect={setMode} />
          <AttachButton onPick={att.addFiles} disabled={!connected} className="h-8 w-8 rounded-lg" />
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={
              workspacePath
                ? mode === 'plan'
                  ? 'Describe the change — get a plan first…'
                  : 'Ask the agent…'
                : 'Open a folder to start…'
            }
            rows={2}
            disabled={!connected}
            className="flex-1 text-[13px]"
          />
          <button
            type="button"
            onClick={dictation.toggle}
            disabled={!connected || dictation.busy}
            aria-label={
              dictation.recording
                ? 'Stop dictation and transcribe'
                : dictation.busy
                  ? 'Transcribing'
                  : 'Dictate'
            }
            title={
              dictation.recording
                ? 'Stop & transcribe'
                : dictation.busy
                  ? 'Transcribing…'
                  : 'Dictate'
            }
            className={cn(
              'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-50',
              dictation.recording
                ? 'bg-error text-white hover:opacity-90'
                : 'text-muted hover:bg-surface-2 hover:text-fg'
            )}
          >
            {dictation.recording ? <Square size={14} /> : <Mic size={16} />}
          </button>
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
              {mode === 'plan' ? 'Plan' : 'Send'}
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

function ModeSelector({
  mode,
  disabled,
  onSelect
}: {
  mode: AgentMode
  disabled: boolean
  onSelect: (m: AgentMode) => void
}) {
  const cur = modeInfo(mode)
  return (
    <Popover
      label="Agent mode"
      side="top"
      trigger={({ toggle, open, triggerProps }) => (
        <button
          type="button"
          disabled={disabled}
          aria-label={`Agent mode: ${cur.label}`}
          onClick={toggle}
          className={cn(
            'inline-flex h-8 shrink-0 items-center gap-1 rounded-lg border border-border px-2 text-xs text-fg transition-colors',
            'hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50',
            open && 'bg-surface-2'
          )}
          {...triggerProps}
        >
          {modeIcon(mode)}
          <span className="max-w-[68px] truncate">{cur.short}</span>
          <ChevronDown size={12} className="opacity-60" />
        </button>
      )}
    >
      {(close) => (
        <div className="flex w-72 flex-col gap-0.5">
          <div className="px-2 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
            Mode
          </div>
          {AGENT_MODES.map((m) => (
            <button
              key={m.id}
              onClick={() => {
                onSelect(m.id)
                close()
              }}
              className={cn(
                'flex items-start gap-2 rounded-lg px-2.5 py-1.5 text-left transition-colors hover:bg-surface-2',
                m.id === mode && 'bg-surface-2'
              )}
            >
              <span className="mt-0.5 shrink-0 text-muted">{modeIcon(m.id, 15)}</span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5 text-[13px] font-medium text-fg">
                  {m.label}
                  {m.id === mode ? <Check size={13} className="text-accent" /> : null}
                </div>
                <div className="text-[11px] text-muted">{m.desc}</div>
              </div>
            </button>
          ))}
        </div>
      )}
    </Popover>
  )
}

function CheckpointsMenu({
  checkpoints,
  partial,
  undoing,
  onUndo
}: {
  checkpoints: CheckpointInfo[]
  partial: boolean
  undoing: boolean
  onUndo: (id?: string) => void
}) {
  const ordered = [...checkpoints].reverse() // najnowszy na górze
  return (
    <div className="flex w-80 flex-col gap-2">
      <div className="flex items-center justify-between px-1 pt-1 text-xs font-semibold text-muted">
        <span>Session checkpoints</span>
        <Button
          variant="outline"
          size="sm"
          icon={<Undo2 size={13} />}
          disabled={undoing || checkpoints.length === 0}
          onClick={() => onUndo()}
        >
          Undo all
        </Button>
      </div>
      {partial ? (
        <div className="mx-1 rounded-md bg-warn/10 px-2 py-1.5 text-[11px] text-warn">
          {partialUndoNote(true)}
        </div>
      ) : null}
      {ordered.length === 0 ? (
        <div className="px-1 pb-1 text-xs text-muted">
          No checkpoints yet. They appear when the agent edits files.
        </div>
      ) : (
        <div className="flex max-h-72 flex-col gap-1 overflow-auto">
          {ordered.map((c) => (
            <div
              key={c.id}
              className="flex items-center gap-2 rounded-lg bg-surface-2 px-2.5 py-1.5"
            >
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] text-fg" title={checkpointTitle(c)}>
                  {checkpointTitle(c)}
                </div>
                <div className="text-[11px] text-muted">{checkpointSubtitle(c)}</div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                disabled={undoing}
                onClick={() => onUndo(c.id)}
                title="Undo to this checkpoint"
              >
                Undo to here
              </Button>
            </div>
          ))}
        </div>
      )}
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
        <div className="mb-1 text-[10px] font-bold uppercase tracking-wide text-muted">Caelo</div>
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
  if (entry.kind === 'info') {
    return (
      <div
        className={cn(
          'rounded-md px-2.5 py-1.5 text-[12px]',
          entry.tone === 'warn' ? 'bg-warn/10 text-warn' : 'bg-surface-2 text-muted'
        )}
      >
        {entry.text}
      </div>
    )
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
        {entry.detail?.created && entry.status === 'awaiting' ? (
          <span className="shrink-0 rounded bg-success/15 px-1 text-[10px] text-success">new</span>
        ) : null}
        <span className="shrink-0 text-[10px] uppercase text-muted">{entry.status}</span>
      </div>

      {entry.status === 'awaiting' && entry.detail ? (
        <div className="flex flex-col gap-2 p-2.5">
          {entry.detail.kind === 'diff' ? (
            <DiffView diff={entry.detail.diff ?? ''} />
          ) : entry.detail.kind === 'binary' ? (
            <div className="rounded-md bg-surface-2 px-2.5 py-2 font-mono text-[11.5px] text-muted">
              {entry.detail.detail ?? 'Binary file would change'}
            </div>
          ) : entry.detail.kind === 'command' ? (
            <pre className="m-0 whitespace-pre-wrap rounded-md bg-surface-2 px-2.5 py-2 font-mono text-xs text-fg/90">
              $ {entry.detail.command}
              {entry.detail.cwd ? `   (cwd: ${entry.detail.cwd})` : ''}
            </pre>
          ) : entry.detail.kind === 'mcp_tool_call' ? (
            <div className="rounded-md bg-surface-2 px-2.5 py-2">
              <div className="mb-1 flex items-center gap-2 text-xs">
                <span className="rounded bg-accent/15 px-1.5 py-0.5 font-medium text-accent">MCP</span>
                <span className="font-mono text-fg/90">{entry.detail.tool}</span>
                {entry.detail.server ? (
                  <span className="text-muted">on {entry.detail.server}</span>
                ) : null}
              </div>
              {entry.detail.description ? (
                <p className="mb-1.5 text-[11.5px] text-muted">{entry.detail.description}</p>
              ) : null}
              <pre className="m-0 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11.5px] text-fg/80">
                {JSON.stringify(entry.detail.args ?? {}, null, 2)}
              </pre>
            </div>
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
