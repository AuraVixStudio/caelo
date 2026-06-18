import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, GitMerge, Users, X } from 'lucide-react'
import { teamMergeDiff, type Conn, type TeamMerge, type TeamReport } from '../../lib/api'
import {
  orderedNodes,
  statusTone,
  teamCostBadge,
  timeline,
  type SubAgentMap,
  type SubAgentNode,
  type SubApproval
} from '../../lib/teamView'
import { cn } from '../../lib/cn'
import { Button } from '../ui/Button'
import { DiffView } from './DiffView'

const toneClass: Record<ReturnType<typeof statusTone>, string> = {
  ok: 'bg-success/15 text-success',
  warn: 'bg-warn/15 text-warn',
  error: 'bg-error/15 text-error',
  active: 'bg-accent/15 text-accent',
  idle: 'bg-surface-2 text-muted'
}

/**
 * M17-F1/F2/F3/F5: widok zespołu subagentów — drzewo (rola/status/aktywność),
 * przegląd scalenia worktree jako jeden diff (accept/reject + konflikt),
 * routing zatwierdzeń per subagent, koszt + oś czasu.
 */
export function TeamView({
  nodes: nodeMap,
  merges,
  report,
  conn,
  onApprove,
  onApplyMerge,
  onRejectMerge,
  busy
}: {
  nodes: SubAgentMap
  merges: TeamMerge[]
  report: TeamReport | null
  conn: Conn
  onApprove: (id: string, decision: 'accept' | 'reject' | 'always') => void
  onApplyMerge: (id: string) => void
  onRejectMerge: (id: string) => void
  busy: boolean
}) {
  const [collapsed, setCollapsed] = useState(false)
  const nodes = orderedNodes(nodeMap)
  // scalenia bez żywego węzła (np. po reconnect) — pokaż osobno, by nic nie zginęło.
  const nodeAgentIds = new Set(nodes.map((n) => n.agent_id))
  const orphanMerges = merges.filter((m) => !nodeAgentIds.has(m.agent_id))

  if (nodes.length === 0 && merges.length === 0 && !report) return null

  return (
    <div className="shrink-0 border-t border-border bg-surface-2/40">
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[11px] font-semibold text-muted transition-colors hover:text-fg"
        title={collapsed ? 'Expand the team panel' : 'Collapse the team panel'}
      >
        {collapsed ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
        <Users size={13} />
        <span>Team</span>
        {/* zwinięty: pokaż skrót (liczba agentów + koszt), by panel nadal coś mówił */}
        {collapsed && nodes.length > 0 ? (
          <span className="font-normal">· {nodes.length} agent{nodes.length === 1 ? '' : 's'}</span>
        ) : null}
        {report ? <span className="font-normal">· {teamCostBadge(report.totals)}</span> : null}
      </button>

      {collapsed ? null : (
      <div className="flex max-h-80 flex-col gap-1.5 overflow-y-auto px-2 pb-2">
        {nodes.map((node) => (
          <SubAgentCard
            key={node.agent_id}
            node={node}
            merge={merges.find((m) => m.agent_id === node.agent_id) ?? null}
            conn={conn}
            onApprove={onApprove}
            onApplyMerge={onApplyMerge}
            onRejectMerge={onRejectMerge}
            busy={busy}
          />
        ))}
        {orphanMerges.map((m) => (
          <MergeReview
            key={m.id}
            merge={m}
            conn={conn}
            onApply={onApplyMerge}
            onReject={onRejectMerge}
            busy={busy}
          />
        ))}
        {report ? <Timeline report={report} /> : null}
      </div>
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={cn('shrink-0 rounded px-1.5 py-0.5 text-[10px] uppercase', toneClass[statusTone(status)])}>
      {status}
    </span>
  )
}

function SubAgentCard({
  node,
  merge,
  conn,
  onApprove,
  onApplyMerge,
  onRejectMerge,
  busy
}: {
  node: SubAgentNode
  merge: TeamMerge | null
  conn: Conn
  onApprove: (id: string, decision: 'accept' | 'reject' | 'always') => void
  onApplyMerge: (id: string) => void
  onRejectMerge: (id: string) => void
  busy: boolean
}) {
  const [open, setOpen] = useState(false)
  const hasDetail = node.tools.length > 0 || node.approvals.length > 0 || !!node.summary
  return (
    <div className="shrink-0 overflow-hidden rounded-lg border border-border bg-surface text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left transition-colors hover:bg-surface-2"
      >
        {hasDetail ? (
          open ? (
            <ChevronDown size={13} className="shrink-0 text-muted" />
          ) : (
            <ChevronRight size={13} className="shrink-0 text-muted" />
          )
        ) : (
          <span className="w-[13px] shrink-0" />
        )}
        <span className="shrink-0 font-bold text-accent">{node.role}</span>
        <span className="min-w-0 flex-1 truncate text-muted" title={node.task}>
          {node.activity || node.task}
        </span>
        {node.approvals.length > 0 ? (
          <span className="shrink-0 rounded bg-warn/20 px-1 text-[10px] text-warn">
            {node.approvals.length} to approve
          </span>
        ) : null}
        <StatusBadge status={node.status} />
      </button>

      {open && hasDetail ? (
        <div className="flex flex-col gap-1.5 border-t border-border px-2.5 py-2">
          {/* F3: zatwierdzenia przypisane do tego subagenta */}
          {node.approvals.map((a) => (
            <ApprovalCard key={a.id} approval={a} onApprove={onApprove} />
          ))}
          {/* transkrypt narzędzi subagenta */}
          {node.tools.map((t) => (
            <div key={t.id} className="rounded-md bg-surface-2 px-2 py-1">
              <div className="flex items-center gap-2">
                <span className="font-mono font-medium text-fg/90">{t.name}</span>
                <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-muted">
                  {t.name === 'run_command'
                    ? String(t.args.command ?? '')
                    : String(t.args.path ?? '')}
                </span>
                <span className="shrink-0 text-[10px] uppercase text-muted">{t.status}</span>
              </div>
              {t.summary ? (
                <div className="mt-0.5 whitespace-pre-wrap font-mono text-[10.5px] text-muted">
                  {t.summary.slice(0, 400)}
                </div>
              ) : null}
            </div>
          ))}
          {node.summary ? (
            <div className="whitespace-pre-wrap rounded-md bg-surface-2 px-2 py-1 text-[11.5px] text-fg/80">
              {node.summary}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* F2: przegląd scalenia worktree (jeden diff) */}
      {merge ? (
        <MergeReview
          merge={merge}
          conn={conn}
          onApply={onApplyMerge}
          onReject={onRejectMerge}
          busy={busy}
          embedded
        />
      ) : null}
    </div>
  )
}

function ApprovalCard({
  approval,
  onApprove
}: {
  approval: SubApproval
  onApprove: (id: string, decision: 'accept' | 'reject' | 'always') => void
}) {
  const d = approval.detail
  return (
    <div className="rounded-md border border-warn/60 bg-warn/5 px-2 py-1.5">
      <div className="mb-1 text-[11px] text-warn">
        {/* F3: jasna atrybucja do subagenta-pytającego */}
        {d?.role ? `${d.role} subagent` : 'Subagent'} requests: <b>{approval.name}</b>
      </div>
      {d?.kind === 'command' ? (
        <pre className="m-0 mb-1 whitespace-pre-wrap rounded bg-surface-2 px-2 py-1 font-mono text-[11px]">
          $ {d.command}
        </pre>
      ) : d?.kind === 'diff' ? (
        <DiffView diff={d.diff ?? ''} />
      ) : null}
      <div className="flex gap-1.5">
        <Button size="sm" onClick={() => onApprove(approval.id, 'accept')}>
          Accept
        </Button>
        <Button variant="danger" size="sm" onClick={() => onApprove(approval.id, 'reject')}>
          Reject
        </Button>
        <Button variant="outline" size="sm" onClick={() => onApprove(approval.id, 'always')}>
          Always
        </Button>
      </div>
    </div>
  )
}

function MergeReview({
  merge,
  conn,
  onApply,
  onReject,
  busy,
  embedded
}: {
  merge: TeamMerge
  conn: Conn
  onApply: (id: string) => void
  onReject: (id: string) => void
  busy: boolean
  embedded?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [diff, setDiff] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open || diff !== null) return
    setLoading(true)
    void teamMergeDiff(conn, merge.id)
      .then((r) => setDiff(r.diff))
      .catch(() => setDiff(''))
      .finally(() => setLoading(false))
  }, [open, diff, conn, merge.id])

  // Esc zamyka modal (jak lightbox czatu).
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <div className={cn('shrink-0 px-2.5 py-2', embedded && 'border-t border-border bg-accent/5')}>
      <div className="flex items-center gap-2">
        <GitMerge size={13} className="shrink-0 text-accent" />
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="min-w-0 flex-1 truncate text-left text-[11.5px] text-fg hover:underline"
          title="Review the subagent's changes as one diff"
        >
          Review merge — {merge.file_count} file{merge.file_count === 1 ? '' : 's'}
        </button>
        {merge.conflicts.length > 0 ? (
          <span
            className="shrink-0 rounded bg-error/20 px-1 text-[10px] text-error"
            title={`Also changed by another subagent: ${merge.conflicts.join(', ')}`}
          >
            {merge.conflicts.length} conflict{merge.conflicts.length === 1 ? '' : 's'}
          </span>
        ) : null}
      </div>

      {/* F2: diff w MODALU (overlay) — długi diff przewija się we własnym obszarze,
          a przyciski Accept/Discard są w przyklejonej stopce, zawsze dostępne.
          Inline-expand uwięziony w `max-h-64` panelu Team uniemożliwiał ich kliknięcie. */}
      {open ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Review merge"
          onClick={() => setOpen(false)}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-2xl"
          >
            <div className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-2.5 text-sm font-semibold">
              <GitMerge size={15} className="text-accent" />
              <span>
                Review merge — {merge.file_count} file{merge.file_count === 1 ? '' : 's'}
              </span>
              {merge.conflicts.length > 0 ? (
                <span className="rounded bg-error/20 px-1.5 py-0.5 text-[10px] font-normal text-error">
                  {merge.conflicts.length} conflict{merge.conflicts.length === 1 ? '' : 's'}
                </span>
              ) : null}
              <span className="flex-1" />
              <button
                type="button"
                onClick={() => setOpen(false)}
                title="Close (Esc)"
                className="flex h-7 w-7 items-center justify-center rounded-md text-muted transition-colors hover:bg-surface-2 hover:text-fg"
              >
                <X size={15} />
              </button>
            </div>

            <div className="flex-1 overflow-auto px-4 py-3">
              {merge.conflicts.length > 0 ? (
                <div className="mb-2 rounded bg-error/10 px-2 py-1.5 text-[11px] text-error">
                  Conflicts (changed by another pending merge): {merge.conflicts.join(', ')}.
                  Merging will overwrite the other subagent's version of these files.
                </div>
              ) : null}
              {loading ? (
                <div className="text-[11px] text-muted">Loading diff…</div>
              ) : (
                <DiffView diff={diff ?? ''} />
              )}
            </div>

            <div className="flex shrink-0 gap-2 border-t border-border px-4 py-2.5">
              <Button
                size="sm"
                icon={<GitMerge size={13} />}
                disabled={busy}
                onClick={() => {
                  onApply(merge.id)
                  setOpen(false)
                }}
              >
                Accept &amp; merge
              </Button>
              <Button
                variant="danger"
                size="sm"
                disabled={busy}
                onClick={() => {
                  onReject(merge.id)
                  setOpen(false)
                }}
              >
                Discard
              </Button>
              <span className="flex-1" />
              <Button variant="outline" size="sm" onClick={() => setOpen(false)}>
                Cancel
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function Timeline({ report }: { report: TeamReport }) {
  const [open, setOpen] = useState(false)
  const rows = timeline(report)
  if (rows.length === 0) return null
  return (
    <div className="shrink-0 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 text-left text-[11px] text-muted hover:text-fg"
      >
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <span>Last run · {teamCostBadge(report.totals)}</span>
      </button>
      {open ? (
        <div className="mt-1.5 flex flex-col gap-1">
          {rows.map((r) => (
            <div key={r.agent_id} className="flex items-center gap-2">
              <span className="w-16 shrink-0 truncate font-medium text-fg/80">{r.role}</span>
              <StatusBadge status={r.status} />
              <span className="flex-1" />
              <span className="shrink-0 text-[10.5px] text-muted">
                {r.duration ? `${r.duration.toFixed(1)}s` : '—'}
                {r.tokens ? ` · ${r.tokens} tok` : ''}
              </span>
            </div>
          ))}
          {report.errors.length > 0 ? (
            <div className="mt-0.5 text-[10.5px] text-warn">{report.errors.join('; ')}</div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
