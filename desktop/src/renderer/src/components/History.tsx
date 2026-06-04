import { useEffect, useState } from 'react'
import { RotateCw } from 'lucide-react'
import { getHistory, type Conn, type HistoryEntry } from '../lib/api'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'
import { Page } from './ui/Page'

const MODE_TONE: Record<string, 'success' | 'info' | 'accent' | 'neutral'> = {
  generate: 'success',
  edit: 'info',
  video: 'accent'
}

export function History({ conn }: { conn: Conn }) {
  const [entries, setEntries] = useState<HistoryEntry[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  function load(): void {
    setLoading(true)
    setError(null)
    getHistory(conn)
      .then((r) => setEntries(r.entries))
      .catch((e) => setError(String((e as Error).message || e)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const open = (target: string): void => {
    if (/^https?:/i.test(target)) window.open(target, '_blank')
    else void window.grok.openPath(target)
  }

  const fmt = (iso: string): string => {
    try {
      return new Date(iso).toLocaleString()
    } catch {
      return iso
    }
  }

  return (
    <Page
      title="History"
      subtitle="Past generations (newest first)."
      actions={
        <Button variant="outline" size="sm" icon={<RotateCw size={14} />} onClick={load}>
          Refresh
        </Button>
      }
    >
      {error ? <p className="mb-4 text-sm text-error">{error}</p> : null}
      {loading ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : entries.length === 0 ? (
        <p className="text-sm text-muted">No generations yet.</p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {entries.map((e, i) => (
            <div
              key={i}
              className="grid grid-cols-[84px_1fr_auto_auto] items-center gap-3 rounded-xl border border-border bg-surface px-4 py-2.5"
            >
              <Badge tone={MODE_TONE[e.mode] || 'neutral'}>{e.mode}</Badge>
              <span className="truncate text-sm" title={e.prompt}>
                {e.prompt}
              </span>
              <span className="text-xs text-muted">{fmt(e.timestamp)}</span>
              <Button variant="ghost" size="sm" onClick={() => open(e.url)}>
                Open
              </Button>
            </div>
          ))}
        </div>
      )}
    </Page>
  )
}
