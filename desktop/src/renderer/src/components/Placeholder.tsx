import { useEffect, useState } from 'react'
import type { CoreConnection } from '../types'
import { cn } from '../lib/cn'
import { Card } from './ui/Card'
import { Page } from './ui/Page'

const STATUS_TEXT: Record<CoreConnection['status'], string> = {
  starting: 'text-warn',
  ready: 'text-success',
  error: 'text-error',
  stopped: 'text-muted'
}

/** Widok zastępczy modułów wdrażanych w kolejnych fazach + status backendu. */
export function Placeholder({ name, conn }: { name: string; conn: CoreConnection }) {
  const [roundTrip, setRoundTrip] = useState('—')

  useEffect(() => {
    if (conn.status === 'ready' && conn.baseUrl && conn.token) {
      fetch(`${conn.baseUrl}/whoami`, { headers: { Authorization: `Bearer ${conn.token}` } })
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((d) => setRoundTrip(`caelo-core v${d.version} · port ${d.port}`))
        .catch((e) => setRoundTrip(`error: ${String(e)}`))
    }
  }, [conn.status, conn.baseUrl, conn.token])

  return (
    <Page title={name} subtitle="Coming in a later phase." maxWidth="max-w-2xl">
      <Card title="Backend (caelo-core)">
        <dl className="grid grid-cols-[140px_1fr] gap-y-2.5 text-sm">
          <dt className="text-muted">Status</dt>
          <dd className={cn('m-0 font-mono', STATUS_TEXT[conn.status])}>{conn.status}</dd>
          <dt className="text-muted">Base URL</dt>
          <dd className="m-0 break-all font-mono">{conn.baseUrl ?? '—'}</dd>
          <dt className="text-muted">Round-trip</dt>
          <dd className="m-0 break-all font-mono">{roundTrip}</dd>
        </dl>
        {conn.error ? <p className="mt-3 text-sm text-error">{conn.error}</p> : null}
      </Card>
    </Page>
  )
}
