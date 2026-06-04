import { useCallback, useEffect, useState } from 'react'
import { GitBranch, RotateCw } from 'lucide-react'
import { gitCommit, gitStage, gitStatus, type Conn, type GitStatus } from '../../lib/api'
import { cn } from '../../lib/cn'
import { Button } from '../ui/Button'
import { IconButton } from '../ui/IconButton'
import { Textarea } from '../ui/Textarea'

// Czytelna etykieta dwuznakowego statusu porcelain (XY).
function statusLabel(code: string): { tag: string; cls: string } {
  const c = code.trim()
  if (c === '??') return { tag: 'U', cls: 'bg-warn/15 text-warn' }
  if (c.includes('A')) return { tag: 'A', cls: 'bg-success/15 text-success' }
  if (c.includes('D')) return { tag: 'D', cls: 'bg-error/15 text-error' }
  if (c.includes('R')) return { tag: 'R', cls: 'bg-info/15 text-info' }
  if (c.includes('M')) return { tag: 'M', cls: 'bg-info/15 text-info' }
  return { tag: c || '•', cls: 'bg-info/15 text-info' }
}

export function GitPanel({
  conn,
  refreshKey,
  onCommitted
}: {
  conn: Conn
  refreshKey: number
  onCommitted: () => void
}) {
  const [status, setStatus] = useState<GitStatus | null>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string>('')

  const refresh = useCallback(() => {
    void gitStatus(conn)
      .then(setStatus)
      .catch(() => setStatus({ is_repo: false }))
  }, [conn])

  useEffect(() => {
    refresh()
  }, [refresh, refreshKey])

  async function stageAll(): Promise<void> {
    setBusy(true)
    setNote('')
    try {
      await gitStage(conn)
      setNote('Staged all changes.')
      refresh()
    } catch (e) {
      setNote((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function commit(): Promise<void> {
    const msg = message.trim()
    if (!msg) return
    setBusy(true)
    setNote('')
    try {
      await gitCommit(conn, msg, true) // stage_all: obejmij też nowe pliki
      setMessage('')
      setNote('Committed.')
      refresh()
      onCommitted()
    } catch (e) {
      setNote((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (status && !status.is_repo) {
    return (
      <div className="flex shrink-0 flex-col border-t border-border bg-surface">
        <div className="border-b border-border px-3 py-2 text-xs font-semibold">Git</div>
        <p className="px-3 py-2 text-xs text-muted">{status.detail || 'Not a git repository.'}</p>
      </div>
    )
  }

  const files = status?.files ?? []
  return (
    <div className="flex min-h-0 max-h-[55%] shrink-0 flex-col border-t border-border bg-surface">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2 text-xs font-semibold">
        <span>Git</span>
        {status?.branch ? (
          <span className="flex items-center gap-1 font-medium text-success">
            <GitBranch size={12} /> {status.branch}
          </span>
        ) : null}
        <IconButton
          size="sm"
          label="Refresh"
          icon={<RotateCw size={14} />}
          onClick={refresh}
          className="ml-auto"
        />
      </div>

      <div className="min-h-0 flex-1 overflow-auto py-1">
        {files.length === 0 ? (
          <p className="px-3 py-2 text-xs text-muted">Working tree clean.</p>
        ) : (
          files.map((f) => {
            const s = statusLabel(f.status)
            return (
              <div
                key={f.path}
                className="flex items-center gap-2 px-3 py-0.5 text-xs text-muted"
                title={f.path}
              >
                <span
                  className={cn(
                    'inline-flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px] font-bold',
                    s.cls
                  )}
                >
                  {s.tag}
                </span>
                <span className="truncate font-mono">{f.path}</span>
              </div>
            )
          })
        )}
      </div>

      <div className="flex flex-col gap-2 border-t border-border p-2">
        <Textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Commit message…"
          rows={2}
          disabled={busy}
          className="text-xs"
        />
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={stageAll} disabled={busy || files.length === 0}>
            Stage all
          </Button>
          <Button
            size="sm"
            onClick={commit}
            disabled={busy || !message.trim() || files.length === 0}
          >
            Commit
          </Button>
        </div>
        {note ? <div className="break-words text-xs text-muted">{note}</div> : null}
      </div>
    </div>
  )
}
