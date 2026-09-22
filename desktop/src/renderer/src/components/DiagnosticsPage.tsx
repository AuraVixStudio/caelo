import { useCallback, useEffect, useState } from 'react'
import { Activity, CheckCircle2, RefreshCw } from 'lucide-react'
import { getMediaDiagnostics, validateProvider, type Conn, type MediaDiagnostics } from '../lib/api'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'
import { Card } from './ui/Card'
import { Page } from './ui/Page'

export function DiagnosticsPage({ conn }: { conn: Conn }) {
  const [data, setData] = useState<MediaDiagnostics | null>(null)
  const [checks, setChecks] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => getMediaDiagnostics(conn).then(setData).catch((e) => setError(String(e))), [conn])
  useEffect(() => { void load() }, [load])
  async function test(id: string): Promise<void> {
    setChecks((value) => ({ ...value, [id]: 'Testing…' }))
    try { const response = await validateProvider(conn, id); setChecks((value) => ({ ...value, [id]: String(response.message || response.status || 'Connected') })) }
    catch (e) { setChecks((value) => ({ ...value, [id]: String((e as Error).message || e) })) }
  }
  return (
    <Page title="Diagnostics" subtitle="Health of the unified media stack. Connection checks do not start a paid generation."
      actions={<Button variant="outline" size="sm" icon={<RefreshCw size={14} />} onClick={load}>Refresh</Button>}>
      {error ? <p className="mb-4 text-sm text-error">{error}</p> : null}
      {!data ? <p className="text-sm text-muted">Loading…</p> : <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Library" subtitle="Persistent media database">
          <div className="grid grid-cols-2 gap-3"><Stat label="Artifacts" value={data.artifacts} /><Stat label="Generations" value={data.generations} /></div>
          <p className="mt-4 break-all text-xs text-muted">{data.database}</p><p className="mt-1 break-all text-xs text-muted">Output: {data.output_directory}</p>
        </Card>
        <Card title="Providers" subtitle="Authentication and API reachability">
          <div className="space-y-3">{data.providers.map((provider) => <div key={provider.id} className="flex items-center gap-2">
            <Badge tone={provider.status === 'stable' ? 'success' : 'info'}>{provider.label}</Badge>
            <span className="min-w-0 flex-1 truncate text-xs text-muted">{checks[provider.id] ?? provider.status}</span>
            <Button variant="outline" size="sm" onClick={() => test(provider.id)}>Test</Button></div>)}</div>
        </Card>
        <Card title="Queue states" subtitle="Current persisted jobs">
          {Object.keys(data.job_states).length ? <div className="flex flex-wrap gap-2">{Object.entries(data.job_states).map(([state, count]) => <Badge key={state} tone="accent">{state} · {count}</Badge>)}</div> : <p className="text-sm text-muted">Queue is empty.</p>}
        </Card>
        <Card title="Schema" subtitle="Append-only migrations">
          <div className="space-y-2">{data.migrations.map((migration) => <div key={migration.version} className="flex items-center gap-2 text-sm"><CheckCircle2 size={15} className="text-success" /><span>v{migration.version} · {migration.name}</span></div>)}</div>
        </Card>
      </div>}
    </Page>
  )
}

function Stat({ label, value }: { label: string; value: number }) {
  return <div className="rounded-xl bg-surface-2 p-4"><Activity size={16} className="mb-2 text-accent" /><p className="text-2xl font-semibold">{value}</p><p className="text-xs text-muted">{label}</p></div>
}
