import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode
} from 'react'
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  FileText,
  FolderTree,
  Globe,
  History,
  ListChecks,
  Loader2,
  MessagesSquare,
  Mic,
  Pencil,
  Play,
  Plug,
  Plus,
  Search,
  ShieldCheck,
  Square,
  Terminal,
  Trash2,
  Undo2,
  Zap
} from 'lucide-react'
import { AgentConnection, type AgentEvent, type ApprovalDetail } from '../../lib/agentClient'
import {
  agentUndo,
  applyTeamMerge,
  deleteAgentSession,
  fsFiles,
  getAgentSession,
  listAgentSessions,
  listCheckpoints,
  listTeamMerges,
  rejectTeamMerge,
  type AgentSessionMeta,
  type ChatAttachment,
  type CheckpointInfo,
  type Conn,
  type ReasoningEffort,
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
import { formatTokens } from '../../lib/searchState'
import { useStickToBottom } from '../../lib/useStickToBottom'
import { planCounts, type PlanItem } from '../../lib/agentPlan'
import { filterSessions, historyToEntries, sessionsForWorkspace } from '../../lib/agentSession'
import { detectSuggest, fuzzyFiles, applyFileSuggest } from '../../lib/composerSuggest'
import { filterSlashCommands, expandTemplate, matchSlash } from '../../lib/slashCommands'
import { useHub } from '../../lib/hub'
import { inputBlockToAttachment } from '../../lib/sendTo'
import { useAttachments } from '../../lib/useAttachments'
import { appendDictation, useDictation } from '../../lib/useDictation'
import { cn } from '../../lib/cn'
import { Markdown } from '../Markdown'
import { AttachButton, AttachmentChips } from '../Attachments'
import { Button } from '../ui/Button'
import { IconButton } from '../ui/IconButton'
import { EffortSelect } from '../ui/EffortSelect'
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

// Faza-G/TOP3: live checklist agenta (TODO) — przypięta u góry konwersacji, aktualizowana
// w trakcie przebiegu (narzędzie update_plan → ramka `plan`). Pełna lista zastępuje poprzednią.
function PlanWidget({ items }: { items: PlanItem[] }): ReactNode {
  const { total, done } = planCounts(items)
  return (
    <div className="shrink-0 border-b border-border bg-accent/5 px-3 py-2">
      <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted">
        <ListChecks size={13} />
        <span>Plan</span>
        <span className="ml-auto tabular-nums">
          {done}/{total}
        </span>
      </div>
      <ul className="flex flex-col gap-0.5">
        {items.map((it, i) => (
          <li key={i} className="flex items-start gap-1.5 text-xs">
            <span className="mt-0.5 shrink-0">
              {it.status === 'completed' ? (
                <Check size={13} className="text-success" />
              ) : it.status === 'in_progress' ? (
                <Loader2 size={13} className="animate-spin text-accent" />
              ) : (
                <Square size={13} className="text-muted" />
              )}
            </span>
            <span
              className={cn(
                it.status === 'completed' && 'text-muted line-through',
                it.status === 'in_progress' && 'font-medium text-fg'
              )}
            >
              {it.content}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// #2: miernik okna kontekstowego (pasek X/Y + %) — jak w Claude Code. `context_tokens`
// = bieżące zajęcie (realne usage.input lub szacunek), `max_context` = przybliżony limit
// modelu. Kolor ostrzega, gdy okno się zapełnia.
function ContextMeter({
  usage
}: {
  usage: { input_tokens: number; output_tokens: number; context_tokens: number; max_context: number }
}): ReactNode {
  const max = usage.max_context > 0 ? usage.max_context : 0
  const pct = max > 0 ? Math.min(100, Math.round((usage.context_tokens / max) * 100)) : 0
  const total = usage.input_tokens + usage.output_tokens
  const title =
    `Context window ≈ ${usage.context_tokens.toLocaleString()} / ${max.toLocaleString()} tokens (${pct}%)` +
    (total > 0 ? `\nSession total: ${total.toLocaleString()} tokens` : '') +
    `\n(approximate — context size is estimated)`
  return (
    <span className="flex shrink-0 items-center gap-1.5 text-[11px] text-muted" title={title}>
      <span className="hidden h-1.5 w-12 overflow-hidden rounded-full bg-surface-3 md:block">
        <span
          className={cn(
            'block h-full rounded-full',
            pct >= 90 ? 'bg-error' : pct >= 70 ? 'bg-warn' : 'bg-accent'
          )}
          style={{ width: `${pct}%` }}
        />
      </span>
      <span className="tabular-nums">
        {formatTokens(usage.context_tokens)}
        {max > 0 ? <span className="opacity-60">/{formatTokens(max)}</span> : null}
      </span>
    </span>
  )
}

export type Entry =
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
  onFilesChanged,
  onOpenWorkspace
}: {
  conn: Conn
  workspacePath: string | null
  model: string
  models: string[]
  onModelChange: (m: string) => void
  onFilesChanged: () => void
  // M21: wznowienie sesji z innego katalogu → przełącz workspace (selectWorkspace).
  onOpenWorkspace?: (path: string) => void
}) {
  const [entries, setEntries] = useState<Entry[]>([])
  // M21: id aktywnej trwałej sesji (serwer ustala je ramką `session`).
  const [sessionId, setSessionId] = useState<string | null>(null)
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
  // M19-B9: reasoning_effort tej sesji ('' = Auto → backend użyje code_effort).
  const [effort, setEffort] = useState<ReasoningEffort>('')
  const [planPhase, setPlanPhase] = useState<PlanPhase>('idle')
  // M13-F3: oś checkpointów sesji + flaga „partial undo".
  const [checkpoints, setCheckpoints] = useState<CheckpointInfo[]>([])
  const [partial, setPartial] = useState(false)
  const [undoing, setUndoing] = useState(false)
  // M17-F1/F2/F5: drzewo subagentów, oczekujące scalenia worktree, ostatni raport zespołu.
  const [teamNodes, setTeamNodes] = useState<SubAgentMap>({})
  const [merges, setMerges] = useState<TeamMerge[]>([])
  const [teamReport, setTeamReport] = useState<TeamReport | null>(null)
  // Faza-G/TOP3: live checklist (TODO) bieżącego zadania — ramka `plan` z update_plan.
  const [plan, setPlan] = useState<PlanItem[]>([])
  // Licznik tokenów + miernik okna kontekstowego (ramka `usage` po każdej turze).
  const [usage, setUsage] = useState<{
    input_tokens: number
    output_tokens: number
    context_tokens: number
    max_context: number
  } | null>(null)
  // M14/M19: autouzupełnianie composera agenta — slash-komendy ("/") i @-pliki.
  const [fileList, setFileList] = useState<string[]>([])
  const [caret, setCaret] = useState(0)
  const [suggestIdx, setSuggestIdx] = useState(0)
  const [suggestDismissed, setSuggestDismissed] = useState(false)
  // #3: licznik czasu bieżącej tury — wskaźnik pracy „Working… {n}s" (czy agent żyje).
  const [elapsed, setElapsed] = useState(0)
  const taRef = useRef<HTMLTextAreaElement | null>(null)

  const agentRef = useRef<AgentConnection | null>(null)
  const curAssistant = useRef<string | null>(null)
  const idRef = useRef(0)
  // S35-i: auto-scroll tylko gdy user przy dole (karta approval wymusza — niżej).
  const { scrollRef, atBottom, onScroll, scrollToBottom } = useStickToBottom()
  // Handlery rejestrowane są raz — świeże wersje przez refy.
  const onFilesChangedRef = useRef(onFilesChanged)
  onFilesChangedRef.current = onFilesChanged
  const turnWasPlanRef = useRef(false)
  // P1-G: lustro `busy` dla długożyjącego domknięcia onClose (rejestrowane raz, inaczej
  // złapałoby busy===false na zawsze).
  const busyRef = useRef(false)
  busyRef.current = busy

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

  // M19: płaski spis plików/katalogów workspace → @-odwołania w composerze. Odświeżany
  // przy zmianie workspace ORAZ po każdej turze (pliki utworzone przez agenta muszą
  // wejść do podpowiedzi @ — inaczej lista jest nieaktualna od momentu otwarcia folderu).
  const refreshFiles = (): void => {
    void fsFiles(conn)
      .then((r) => setFileList(r.files))
      .catch(() => setFileList([]))
  }
  const refreshFilesRef = useRef(refreshFiles)
  refreshFilesRef.current = refreshFiles

  // Połączenie WS agenta (jedno na sesję modułu Code).
  useEffect(() => {
    const agent = new AgentConnection(
      conn,
      () => {
        setConnected(true)
        if (workspacePath) agent.setWorkspace(workspacePath)
      },
      () => {
        setConnected(false)
        // P1-G: pad/restart sidecara w trakcie tury (busy) — żadna ramka terminalna
        // (done/stopped/error) już nie nadejdzie, więc composer utknąłby na „Stop" do
        // przeładowania. Odblokuj i zostaw ślad. Guard na busyRef, bo onClose woła się też
        // przy zwykłym unmount i każdym cyklu reconnectu (bez guardu = spam info).
        if (busyRef.current) {
          setBusy(false)
          curAssistant.current = null
          setPlanPhase((p) => planReducer(p, { type: 'done' }))
          pushInfo(
            'Connection to the agent was lost. Reconnecting… your last request may not have completed.',
            'warn'
          )
        }
      }
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
      refreshFilesRef.current() // M19: spis plików/katalogów → @-odwołania
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspacePath, connected])

  // #3: tykający licznik czasu tury — żywy znak, że agent pracuje (nie zaciął się).
  useEffect(() => {
    if (!busy) {
      setElapsed(0)
      return
    }
    const start = Date.now()
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000)
    return () => clearInterval(id)
  }, [busy])

  useEffect(() => {
    // S35-i: dosuń do dołu PO ułożeniu layoutu (rAF). Karta approval (detale + przyciski
    // Accept/Reject/Always) MUSI być w widoku, by dało się ją kliknąć — wymuszamy scroll
    // (force), pomijając strażnik stick-to-bottom; w pozostałych przypadkach honorujemy go.
    const last = entries[entries.length - 1]
    const force = !!last && last.kind === 'tool' && last.status === 'awaiting'
    const id = requestAnimationFrame(() => scrollToBottom(force))
    return () => cancelAnimationFrame(id)
  }, [entries, scrollToBottom])

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
        // Faza-G/TOP3: update_plan ma własny widżet (ramka `plan`) — nie dubluj go wierszem narzędzia.
        if (e.name === 'update_plan') break
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
      case 'plan':
        // Faza-G/TOP3: pełna lista przychodzi za każdym razem → podmień (live checklist).
        setPlan(e.items)
        break
      case 'checkpoint':
        // M13-F3: agent zsnapshotował pliki → odśwież oś checkpointów ORAZ drzewo plików
        // (write_file/edit_file tworzą pliki w trakcie tury — niech pojawią się na bieżąco,
        // nie dopiero po `done`; wyjścia run_command jak build/ i tak dochodzą na `done`).
        refreshCheckpointsRef.current()
        onFilesChangedRef.current()
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
        refreshFilesRef.current() // odśwież @-listę: nowe pliki agenta są teraz na dysku
        break
      case 'error':
        setEntries((prev) => [...prev, { kind: 'error', id: nextId(), text: e.error }])
        setBusy(false)
        setPlanPhase((p) => planReducer(p, { type: 'done' }))
        break
      case 'info':
        // Miękka notka z backendu (np. osiągnięty limit kroków) — wpis info w transkrypcie.
        pushInfo(e.text, e.level)
        break
      case 'usage':
        // Licznik + miernik kontekstu (zera pomijamy — mock/brak danych z serwera).
        if (e.context_tokens > 0 || e.input_tokens > 0 || e.output_tokens > 0) {
          setUsage({
            input_tokens: e.input_tokens,
            output_tokens: e.output_tokens,
            context_tokens: e.context_tokens,
            max_context: e.max_context
          })
        }
        break
      case 'diagnostics': {
        // M19-B3: pasywna diagnostyka LSP po edycie — pokaż w transkrypcie (puste pomiń).
        if (e.items.length === 0) break
        const base = e.path.split('/').pop() || e.path
        const lines = e.items.slice(0, 5).map((d) => {
          const ln = typeof d.line === 'number' ? `L${d.line + 1}: ` : ''
          return `• ${ln}${d.message}`
        })
        const more = e.items.length > 5 ? `\n…and ${e.items.length - 5} more` : ''
        setEntries((prev) => [
          ...prev,
          {
            kind: 'info',
            id: nextId(),
            tone: 'warn',
            text: `LSP — ${e.items.length} problem(s) in ${base}\n${lines.join('\n')}${more}`
          }
        ])
        break
      }
      case 'session':
        // M21: aktywne id trwałej sesji (po połączeniu / wznowieniu / nowej sesji).
        setSessionId(e.id)
        break
      case 'workspace':
        break // potwierdzenie ustawienia katalogu — obsługiwane po stronie CodeView
      default:
        break
    }
  }

  function send(): void {
    let text = input.trim()
    if ((!text && att.attachments.length === 0) || busy || !connected) return
    if (!workspacePath) {
      setEntries((prev) => [...prev, { kind: 'error', id: nextId(), text: 'Open a folder first.' }])
      return
    }
    // M14-B4: rozwiń slash-komendę w composerze agenta + zastosuj jej tryb (np. /plan).
    let effMode = mode
    const ms = matchSlash(text)
    if (ms) {
      const cmd = codeCommands.find((c) => c.name === ms.name)
      if (cmd?.template) {
        text = expandTemplate(cmd.template, ms.rest)
        if (cmd.mode) {
          effMode = cmd.mode as AgentMode
          setMode(effMode)
        }
      }
    }
    const usePlan = effMode === 'plan'
    const atts = att.attachments
    setEntries((prev) => [
      ...prev,
      { kind: 'user', id: nextId(), text, attachments: atts.length ? atts : undefined }
    ])
    curAssistant.current = null
    turnWasPlanRef.current = usePlan
    setPlan([]) // Faza-G/TOP3: nowa tura → czyść live checklist (agent re-emituje, gdy kontynuuje)
    setPlanPhase((p) => planReducer(p, { type: 'send', plan: usePlan }))
    setBusy(true)
    setInput('')
    att.clear()
    agentRef.current?.sendMessage(inlineTextFiles(text, atts), model, imageUris(atts), effMode, effort)
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
    agentRef.current?.sendMessage(text, model, [], 'accept-edits', effort)
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

  // M21: zacznij nową sesję — czyść transkrypt; serwer nada nowe id. Blokada w trakcie tury.
  function newSession(): void {
    if (busy) return
    setEntries([])
    curAssistant.current = null
    setTeamNodes({})
    setTeamReport(null)
    setPlanPhase('idle')
    setPlan([])
    setUsage(null) // nowa sesja → wyzeruj licznik tokenów
    agentRef.current?.setSession(null)
  }

  // M21: otwórz zapisaną sesję — odtwórz transkrypt z historii i zwiąż backend (resume z
  // pełnym kontekstem). Sesja z innego katalogu → przełącz workspace. Blokada w trakcie tury.
  async function openSession(meta: AgentSessionMeta): Promise<void> {
    if (busy || !connected) return
    try {
      const full = await getAgentSession(conn, meta.id)
      const cwd = full.cwd || meta.cwd
      const norm = (p: string): string => p.replace(/\\/g, '/').replace(/\/+$/, '')
      if (cwd && (!workspacePath || norm(cwd) !== norm(workspacePath))) onOpenWorkspace?.(cwd)
      setEntries(historyToEntries(full.history))
      curAssistant.current = null
      setTeamNodes({})
      setTeamReport(null)
      setPlanPhase('idle')
      setPlan([])
      setUsage(null) // wznowiona sesja → licznik narośnie od kolejnej tury (backend kumuluje od 0)
      setSessionId(meta.id)
      agentRef.current?.setSession(meta.id)
    } catch {
      pushInfo('Could not open the session.', 'warn')
    }
  }

  function focusCaret(pos: number): void {
    requestAnimationFrame(() => {
      const el = taRef.current
      if (el) {
        el.focus()
        el.setSelectionRange(pos, pos)
      }
    })
  }

  // Wstaw wybraną podpowiedź (slash-komenda → "/name "; plik → "@path ").
  function pickSuggestion(i: number): void {
    const tok = suggestTok
    const s = suggestions[i]
    if (!tok || !s) return
    if (tok.kind === 'slash') {
      const next = '/' + s.value + ' '
      setInput(next)
      setCaret(next.length)
      focusCaret(next.length)
    } else {
      const r = applyFileSuggest(input, tok, s.value)
      setInput(r.text)
      setCaret(r.caret)
      focusCaret(r.caret)
    }
    setSuggestDismissed(false)
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>): void {
    if (showSuggest) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSuggestIdx((i) => (i + 1) % suggestions.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSuggestIdx((i) => (i - 1 + suggestions.length) % suggestions.length)
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        pickSuggestion(suggestIdx)
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setSuggestDismissed(true)
        return
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  // M14/M19: composer autocomplete — slash-komendy (bez chat-only) + @-pliki.
  const codeCommands = useMemo(
    () => hub.slashCommands.filter((c) => (c.target ?? 'both') !== 'chat'),
    [hub.slashCommands]
  )
  const suggestTok = useMemo(() => detectSuggest(input, caret), [input, caret])
  const suggestions = useMemo<{ value: string; label: string; hint?: string }[]>(() => {
    if (!suggestTok) return []
    if (suggestTok.kind === 'slash') {
      return filterSlashCommands(codeCommands, suggestTok.query)
        .slice(0, 8)
        .map((c) => ({ value: c.name, label: '/' + c.name, hint: c.description }))
    }
    return fuzzyFiles(fileList, suggestTok.query, 8).map((p) => ({ value: p, label: p }))
  }, [suggestTok, codeCommands, fileList])
  const showSuggest = suggestions.length > 0 && !suggestDismissed
  useEffect(() => {
    setSuggestIdx(0)
  }, [input, caret])

  const showApproveRun = canApproveRun(planPhase, busy)
  const banner = modeBanner(mode)
  // #3: etykieta bieżącej aktywności agenta — z ostatniego wpisu transkryptu.
  const lastEntry = entries[entries.length - 1]
  let workLabel = 'Thinking…'
  if (lastEntry?.kind === 'tool') {
    if (lastEntry.status === 'awaiting') workLabel = 'Waiting for your approval…'
    else if (lastEntry.status === 'pending') workLabel = `Running ${lastEntry.name}…`
  } else if (lastEntry?.kind === 'assistant') {
    workLabel = 'Writing…'
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-3">
        <span className="text-sm font-semibold">Agent</span>
        <div className="ml-1 min-w-0 flex-1">
          <ModelSelect value={model} models={models} onChange={onModelChange} />
        </div>
        <Popover
          align="end"
          label="Sessions"
          trigger={({ toggle, open, triggerProps }) => (
            <IconButton
              label="Saved sessions"
              icon={<MessagesSquare size={18} />}
              active={open}
              tooltip={!open}
              tooltipSide="bottom-end"
              onClick={toggle}
              {...triggerProps}
            />
          )}
        >
          {(close) => (
            <SessionsMenu
              conn={conn}
              workspacePath={workspacePath}
              activeId={sessionId}
              busy={busy}
              onNew={() => {
                newSession()
                close()
              }}
              onOpen={(m) => {
                void openSession(m)
                close()
              }}
            />
          )}
        </Popover>
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
        {usage ? <ContextMeter usage={usage} /> : null}
        <span
          title={connected ? 'connected' : 'disconnected'}
          className={cn('h-2 w-2 shrink-0 rounded-full', connected ? 'bg-success' : 'bg-muted')}
        />
      </header>

      <div className="relative flex min-h-0 flex-1 flex-col">
        {plan.length > 0 ? <PlanWidget items={plan} /> : null}
        <div
          className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3"
          ref={scrollRef}
          onScroll={onScroll}
          role="log"
          aria-live="polite"
          aria-label="Agent activity"
        >
          {entries.length === 0 ? (
            <p className="text-xs text-muted">
              Ask the agent to read, edit or run code in the workspace.
            </p>
          ) : (
            // `shrink-0`: bez tego dzieci kontenera flex-col KURCZĄ się (flex-shrink:1),
            // więc przy wielu wpisach „ściskają się jak prasą" i lista nie przewija —
            // zamiast tego mają zachować naturalną wysokość i przepełnić (scroll).
            entries.map((e) => (
              <div key={e.id} className="shrink-0">
                <EntryView
                  entry={e}
                  onApprove={approve}
                  streaming={busy && e.kind === 'assistant' && e.id === curAssistant.current}
                />
              </div>
            ))
          )}
        </div>
        {!atBottom ? (
          <button
            onClick={() => scrollToBottom(true)}
            className="absolute bottom-2 left-1/2 -translate-x-1/2 rounded-full border border-border bg-surface px-3 py-1 text-xs text-muted shadow-[var(--shadow)] outline-none hover:text-fg focus-visible:ring-2 focus-visible:ring-accent"
          >
            Jump to bottom
          </button>
        ) : null}
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

      {/* #3: trwały wskaźnik pracy — widoczny przez całą turę, z licznikiem czasu, by
          było jasne, że agent pracuje (a nie zaciął się), także między narzędziami. */}
      {busy ? (
        <div className="flex shrink-0 items-center gap-2 border-t border-border bg-surface-2/60 px-3 py-1.5 text-[11.5px] text-muted">
          <Loader2 size={13} className="shrink-0 animate-spin text-accent" />
          <span className="min-w-0 truncate">{workLabel}</span>
          <span className="ml-auto shrink-0 tabular-nums">{elapsed}s</span>
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
          'relative shrink-0 border-t p-2.5 transition-colors',
          dragging ? 'border-accent' : 'border-border'
        )}
      >
        {showSuggest ? (
          <div className="absolute inset-x-2 bottom-full z-20 mb-1 overflow-hidden rounded-lg border border-border bg-surface shadow-lg">
            <div className="border-b border-border px-3 py-1 text-[10px] font-medium uppercase tracking-wide text-muted">
              {suggestTok?.kind === 'slash' ? 'Commands' : 'Files'}
            </div>
            <ul className="max-h-56 overflow-y-auto py-1" role="listbox" aria-label={suggestTok?.kind === 'slash' ? 'Commands' : 'Files'}>
              {suggestions.map((s, i) => (
                <li key={s.value} role="option" aria-selected={i === suggestIdx}>
                  <button
                    type="button"
                    tabIndex={-1}
                    onMouseDown={(e) => {
                      e.preventDefault()
                      pickSuggestion(i)
                    }}
                    onMouseEnter={() => setSuggestIdx(i)}
                    className={cn(
                      'flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12.5px]',
                      i === suggestIdx ? 'bg-surface-2' : 'hover:bg-surface-2'
                    )}
                  >
                    {suggestTok?.kind === 'file' ? (
                      <FileText size={13} className="shrink-0 text-muted" />
                    ) : null}
                    <span className="truncate font-mono text-fg">{s.label}</span>
                    {s.hint ? (
                      <span className="ml-auto truncate pl-2 text-[11px] text-muted">{s.hint}</span>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
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
        <div className="flex items-center gap-2">
          <ModeSelector mode={mode} disabled={false} onSelect={setMode} />
          <EffortSelect effort={effort} onSelect={setEffort} align="end" />
          <AttachButton onPick={att.addFiles} disabled={!connected} className="h-8 w-8 rounded-lg" />
          <Textarea
            ref={taRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value)
              setCaret(e.target.selectionStart ?? e.target.value.length)
              setSuggestDismissed(false)
            }}
            onSelect={(e) => setCaret((e.target as HTMLTextAreaElement).selectionStart ?? 0)}
            onKeyDown={onKeyDown}
            onPaste={(e) => {
              // Wklej zrzut/obraz ze schowka jako załącznik (Ctrl+V) — parytet z czatem.
              // Obrazy ze schowka nie mają nazwy pliku → nadajemy domyślną.
              if (!connected) return
              const items = e.clipboardData?.items
              if (!items) return
              const imgs: File[] = []
              for (const it of Array.from(items)) {
                if (it.kind === 'file' && it.type.startsWith('image/')) {
                  const f = it.getAsFile()
                  if (f)
                    imgs.push(
                      f.name ? f : new File([f], 'pasted-image.png', { type: f.type || 'image/png' })
                    )
                }
              }
              if (imgs.length) {
                e.preventDefault()
                void att.addFiles(imgs)
              }
            }}
            placeholder={
              workspacePath
                ? mode === 'plan'
                  ? 'Describe the change — get a plan first…'
                  : 'Ask the agent…   ·   / commands   ·   @ files'
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

function fmtTime(epochSeconds: number): string {
  if (!epochSeconds) return ''
  try {
    return new Date(epochSeconds * 1000).toLocaleString()
  } catch {
    return ''
  }
}

// M21: lista zapisanych sesji agenta z filtrem po projekcie. Sesje zapisują się
// automatycznie po każdej turze (backend); tu można je wznowić, zacząć nową lub usunąć.
function SessionsMenu({
  conn,
  workspacePath,
  activeId,
  busy,
  onNew,
  onOpen
}: {
  conn: Conn
  workspacePath: string | null
  activeId: string | null
  busy: boolean
  onNew: () => void
  onOpen: (meta: AgentSessionMeta) => void
}) {
  const [sessions, setSessions] = useState<AgentSessionMeta[]>([])
  const [loading, setLoading] = useState(true)
  const [scope, setScope] = useState<'project' | 'all'>(workspacePath ? 'project' : 'all')
  const [deleting, setDeleting] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  // Pobieramy WSZYSTKIE sesje; zawężenie „this project" robimy po stronie klienta —
  // bieżący projekt w module Code wynika z OTWARTEGO FOLDERU (folder = projekt:
  // set_workspace → ensure_project_for_root), nie z (bywa nieaktualny) hub.currentProjectId.
  const refresh = useCallback((): void => {
    setLoading(true)
    void listAgentSessions(conn)
      .then((r) => setSessions(r.sessions))
      .catch(() => setSessions([]))
      .finally(() => setLoading(false))
  }, [conn])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function remove(id: string): Promise<void> {
    setDeleting(id)
    try {
      await deleteAgentSession(conn, id)
      setSessions((prev) => prev.filter((s) => s.id !== id))
    } catch {
      /* ignore */
    } finally {
      setDeleting(null)
    }
  }

  const scoped = scope === 'project' ? sessionsForWorkspace(sessions, workspacePath) : sessions
  const shown = filterSessions(scoped, query)

  return (
    <div className="flex w-80 flex-col gap-2">
      <div className="flex items-center justify-between px-1 pt-1">
        <span className="text-xs font-semibold text-muted">Sessions</span>
        <Button
          variant="outline"
          size="sm"
          icon={<Plus size={13} />}
          disabled={busy}
          onClick={onNew}
        >
          New
        </Button>
      </div>
      {workspacePath ? (
        <div className="flex gap-1 px-1">
          {(['project', 'all'] as const).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setScope(s)}
              className={cn(
                'rounded-md px-2 py-0.5 text-[11px] transition-colors',
                scope === s ? 'bg-surface-3 text-fg' : 'text-muted hover:bg-surface-2'
              )}
            >
              {s === 'project' ? 'This project' : 'All projects'}
            </button>
          ))}
        </div>
      ) : null}
      {!loading && sessions.length > 0 ? (
        <div className="relative px-1">
          <Search
            size={13}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter sessions…"
            aria-label="Filter sessions"
            spellCheck={false}
            className="w-full rounded-md border border-border bg-surface-2 py-1 pl-7 pr-2 text-xs text-fg outline-none focus:border-accent"
          />
        </div>
      ) : null}
      {loading ? (
        <div className="px-1 pb-1 text-xs text-muted">Loading…</div>
      ) : sessions.length === 0 ? (
        <div className="px-1 pb-1 text-xs text-muted">
          No saved sessions yet. Sessions are saved automatically as you work with the agent.
        </div>
      ) : shown.length === 0 ? (
        <div className="px-1 pb-1 text-xs text-muted">
          {query ? `No sessions match “${query}”.` : 'No sessions for this project yet.'}
        </div>
      ) : (
        <div className="flex max-h-72 flex-col gap-1 overflow-auto">
          {shown.map((s) => (
            <div
              key={s.id}
              className={cn(
                'flex items-center gap-2 rounded-lg px-2.5 py-1.5',
                s.id === activeId ? 'bg-accent/10' : 'bg-surface-2'
              )}
            >
              <button
                type="button"
                disabled={busy}
                onClick={() => onOpen(s)}
                title={s.cwd || s.title}
                className="min-w-0 flex-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-50"
              >
                <div className="truncate text-[13px] text-fg">{s.title}</div>
                <div className="text-[11px] text-muted">
                  {s.message_count} msg · {fmtTime(s.updated_at)}
                </div>
              </button>
              <button
                type="button"
                aria-label="Delete session"
                disabled={deleting === s.id}
                onClick={() => void remove(s.id)}
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted outline-none transition-colors hover:bg-surface-3 hover:text-error focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function EntryView({
  entry,
  onApprove,
  streaming = false
}: {
  entry: Entry
  onApprove: (id: string, decision: 'accept' | 'reject' | 'always') => void
  streaming?: boolean
}) {
  if (entry.kind === 'user') {
    // #4: wiadomości użytkownika wyrównane w PRAWO + wyraźny dymek (akcent), żeby
    // odróżniały się od odpowiedzi/narzędzi agenta (lewa strona, pełna szerokość).
    return (
      <div className="flex flex-col items-end">
        {entry.text ? (
          <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-sm border border-accent/30 bg-accent/15 px-3 py-2 text-[13px] text-fg">
            {entry.text}
          </div>
        ) : null}
        {entry.attachments?.length ? (
          <AttachmentChips items={entry.attachments} className="mt-1.5 justify-end" />
        ) : null}
      </div>
    )
  }
  if (entry.kind === 'assistant') {
    return (
      <div>
        <div className="mb-1 text-[10px] font-bold uppercase tracking-wide text-muted">Caelo</div>
        {entry.text ? (
          // Podczas streamingu renderuj TEKST ZWYKŁY (pre-wrap). Markdown re-parsowany
          // co chunk pokazuje puste wiersze tabel / <hr> z częściowych „---" jako „paski"
          // (potwierdzone wizualnie). Pełny markdown dopiero po zakończeniu tury.
          streaming ? (
            <div className="whitespace-pre-wrap break-words text-[13px] leading-relaxed">
              {entry.text}
            </div>
          ) : (
            <Markdown text={entry.text} />
          )
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

  // tool — własny komponent (kompaktowy, zwijany; trzyma stan rozwinięcia).
  return <ToolEntryView entry={entry} onApprove={onApprove} />
}

type ToolEntry = Extract<Entry, { kind: 'tool' }>

// Ikona per-narzędzie — czytelniejszy strumień niż sama nazwa (read/list/grep/edit/run…).
function toolIcon(name: string, size = 13): ReactNode {
  if (name.startsWith('mcp__')) return <Plug size={size} />
  switch (name) {
    case 'read_file':
      return <FileText size={size} />
    case 'list_dir':
      return <FolderTree size={size} />
    case 'glob':
    case 'grep':
      return <Search size={size} />
    case 'write_file':
    case 'edit_file':
      return <Pencil size={size} />
    case 'run_command':
      return <Terminal size={size} />
    case 'web_fetch':
    case 'web_search':
      return <Globe size={size} />
    default:
      return <FileText size={size} />
  }
}

function ToolStatus({ status }: { status: ToolEntry['status'] }): ReactNode {
  switch (status) {
    case 'pending':
      return <Loader2 size={13} className="shrink-0 animate-spin text-muted" />
    case 'awaiting':
      return (
        <span className="shrink-0 rounded bg-warn/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-warn">
          approve
        </span>
      )
    case 'error':
      return <AlertTriangle size={13} className="shrink-0 text-error" />
    default: // done
      return <Check size={13} className="shrink-0 text-success/70" />
  }
}

/**
 * Pojedyncze wywołanie narzędzia. Domyślnie **kompaktowe** (jeden wiersz: ikona + nazwa
 * + argument + status), żeby seria odczytów plików nie zalewała transkryptu. Output i
 * podsumowanie chowamy pod rozwijaniem (klik w nagłówek). Wpisy oczekujące na
 * zatwierdzenie oraz błędy są zawsze rozwinięte — wymagają uwagi.
 */
function ToolEntryView({
  entry,
  onApprove
}: {
  entry: ToolEntry
  onApprove: (id: string, decision: 'accept' | 'reject' | 'always') => void
}) {
  const [expanded, setExpanded] = useState(false)

  const argSummary =
    entry.name === 'run_command'
      ? String(entry.args.command ?? '')
      : String(entry.args.path ?? JSON.stringify(entry.args))

  const isAwaiting = entry.status === 'awaiting'
  const isError = entry.status === 'error'
  const hasOutput = !!entry.output
  const hasSummary = !!entry.summary && !isAwaiting
  const hasDetails = hasOutput || hasSummary
  const showDetails = isAwaiting || isError || (expanded && hasDetails)
  // Oczekujące zatwierdzenie i błąd są wymuszenie rozwinięte → bez chevrona/przełączania.
  const canToggle = !isAwaiting && !isError && hasDetails

  return (
    <div
      className={cn(
        'overflow-hidden rounded-lg border text-xs',
        isAwaiting ? 'border-warn' : isError ? 'border-error' : 'border-border'
      )}
    >
      <button
        type="button"
        onClick={canToggle ? () => setExpanded((v) => !v) : undefined}
        aria-expanded={canToggle ? showDetails : undefined}
        className={cn(
          'flex w-full items-center gap-2 bg-surface-2 px-2.5 py-1.5 text-left outline-none',
          canToggle
            ? 'cursor-pointer hover:bg-surface-3/60 focus-visible:ring-2 focus-visible:ring-accent'
            : 'cursor-default'
        )}
      >
        <span className="shrink-0 text-muted">{toolIcon(entry.name)}</span>
        <span className="shrink-0 font-semibold text-accent">{entry.name}</span>
        <span className="min-w-0 flex-1 truncate font-mono text-muted" title={argSummary}>
          {argSummary}
        </span>
        {entry.detail?.created && isAwaiting ? (
          <span className="shrink-0 rounded bg-success/15 px-1 text-[10px] text-success">new</span>
        ) : null}
        <ToolStatus status={entry.status} />
        {canToggle ? (
          showDetails ? (
            <ChevronDown size={13} className="shrink-0 text-muted" />
          ) : (
            <ChevronRight size={13} className="shrink-0 text-muted" />
          )
        ) : null}
      </button>

      {showDetails ? (
        <>
          {isAwaiting && entry.detail ? (
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
              ) : entry.detail.kind === 'web_fetch' ? (
                <div className="rounded-md bg-surface-2 px-2.5 py-2">
                  <div className="mb-1 flex items-center gap-2 text-xs">
                    <span className="rounded bg-accent/15 px-1.5 py-0.5 font-medium text-accent">
                      Web
                    </span>
                    <span className="text-muted">fetch URL (network)</span>
                  </div>
                  <pre className="m-0 whitespace-pre-wrap break-all font-mono text-[11.5px] text-fg/90">
                    {entry.detail.url}
                  </pre>
                </div>
              ) : entry.detail.kind === 'mcp_tool_call' ? (
                <div className="rounded-md bg-surface-2 px-2.5 py-2">
                  <div className="mb-1 flex items-center gap-2 text-xs">
                    <span className="rounded bg-accent/15 px-1.5 py-0.5 font-medium text-accent">
                      MCP
                    </span>
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

          {hasOutput ? (
            <pre className="m-0 max-h-44 overflow-auto whitespace-pre-wrap bg-surface-3/40 px-2.5 py-2 font-mono text-[11.5px]">
              {entry.output.slice(-4000)}
            </pre>
          ) : null}
          {hasSummary ? (
            <div className="whitespace-pre-wrap border-t border-border px-2.5 py-1.5 font-mono text-[11.5px] text-muted">
              {entry.summary}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  )
}
