import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUpRight, RotateCw, Search } from 'lucide-react'
import { listHistory, type Conn, type HubEvent } from '../lib/api'
import { useHub } from '../lib/hub'
import { buildHistoryQuery, eventTitle, isImageEvent, modeToModule, modeTone } from '../lib/hubQuery'
import { ArtifactThumb } from './ArtifactThumb'
import { ProjectSwitcher } from './ProjectSwitcher'
import { SendToMenu } from './SendToMenu'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'
import { Input } from './ui/Input'
import { Page } from './ui/Page'
import { Select } from './ui/Select'

const MODES = ['all', 'chat', 'image', 'video', 'voice', 'code'] as const

function fmtTime(epoch: number): string {
  try {
    return new Date(epoch * 1000).toLocaleString()
  } catch {
    return String(epoch)
  }
}

export function History({ conn }: { conn: Conn }) {
  const { navigate, currentProjectId } = useHub()
  const [q, setQ] = useState('')
  const [mode, setMode] = useState('all')
  const [events, setEvents] = useState<HubEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const reqId = useRef(0)

  const run = useCallback(
    (search: string, m: string, projectId: string | null) => {
      const id = ++reqId.current
      setLoading(true)
      setError(null)
      listHistory(conn, buildHistoryQuery({ q: search, mode: m, projectId }))
        .then((r) => {
          if (id === reqId.current) setEvents(r.events)
        })
        .catch((e) => {
          if (id === reqId.current) setError(String((e as Error).message || e))
        })
        .finally(() => {
          if (id === reqId.current) setLoading(false)
        })
    },
    [conn]
  )

  // Debounce typing (and mode/project changes) so we don't fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => run(q, mode, currentProjectId), 200)
    return () => clearTimeout(t)
  }, [q, mode, currentProjectId, run])

  const openInMode = (e: HubEvent): void => {
    const target = modeToModule(e.mode)
    if (target) navigate(target)
  }

  return (
    <Page
      title="History"
      subtitle="Everything across modes — search by content or prompt."
      actions={
        <Button
          variant="outline"
          size="sm"
          icon={<RotateCw size={14} />}
          onClick={() => run(q, mode, currentProjectId)}
        >
          Refresh
        </Button>
      }
    >
      <div className="mb-4 flex items-center gap-2">
        <ProjectSwitcher />
        <div className="relative flex-1">
          <Search
            size={15}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted"
          />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search history…"
            className="pl-9"
            aria-label="Search history"
          />
        </div>
        <Select
          value={mode}
          onChange={(e) => setMode(e.target.value)}
          aria-label="Filter by mode"
          className="w-36"
        >
          {MODES.map((m) => (
            <option key={m} value={m}>
              {m === 'all' ? 'All modes' : m[0].toUpperCase() + m.slice(1)}
            </option>
          ))}
        </Select>
      </div>

      {error ? <p className="mb-4 text-sm text-error">{error}</p> : null}
      {loading ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : events.length === 0 ? (
        <p className="text-sm text-muted">
          {q.trim() ? 'No matches.' : 'No history yet — chat, generate, or run the agent.'}
        </p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {events.map((e) => {
            const target = modeToModule(e.mode)
            return (
              <div
                key={e.id}
                className="grid grid-cols-[84px_1fr_auto_auto] items-center gap-3 rounded-xl border border-border bg-surface px-4 py-2.5"
              >
                <Badge tone={modeTone(e.mode)}>{e.mode}</Badge>
                <div className="flex min-w-0 items-center gap-2.5">
                  {isImageEvent(e) ? (
                    <ArtifactThumb
                      conn={conn}
                      artifactId={e.artifact_id!}
                      alt={e.text}
                      className="h-7 w-7 shrink-0 rounded"
                    />
                  ) : null}
                  <span className="truncate text-sm" title={e.text}>
                    {eventTitle(e)}
                  </span>
                </div>
                <span className="text-xs text-muted">{fmtTime(e.created_at)}</span>
                <div className="flex items-center gap-1">
                  {e.artifact_id ? <SendToMenu conn={conn} artifactId={e.artifact_id} /> : null}
                  {target ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<ArrowUpRight size={14} />}
                      onClick={() => openInMode(e)}
                    >
                      Open in {target}
                    </Button>
                  ) : null}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </Page>
  )
}
