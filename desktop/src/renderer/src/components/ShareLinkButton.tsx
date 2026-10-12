import { useState } from 'react'
import { Check, Copy, Link2 } from 'lucide-react'
import {
  createArtifactPublicUrl,
  revokeArtifactPublicUrl,
  type Conn,
  type HubArtifact
} from '../lib/api'
import { copyText } from '../lib/clipboard'
import { Button } from './ui/Button'
import { IconButton } from './ui/IconButton'
import { Popover } from './ui/Popover'
import { Select } from './ui/Select'

// Typy i rozmiar, które xAI Files API potrafi upublicznić (docs.x.ai „Public URLs").
const SHAREABLE_MIME = new Set([
  'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'video/mp4', 'video/webm', 'application/pdf'
])
// Wygaśnięcie linku: 1 h – 30 dni albo brak (do odwołania).
const EXPIRY_OPTIONS: { label: string; seconds: number | null }[] = [
  { label: '1 hour', seconds: 3600 },
  { label: '24 hours', seconds: 86_400 },
  { label: '7 days', seconds: 604_800 },
  { label: '30 days', seconds: 2_592_000 },
  { label: 'Until revoked', seconds: null }
]

export function canSharePublicly(art: HubArtifact): boolean {
  return !!art.path && SHAREABLE_MIME.has((art.mime || '').toLowerCase())
}

function stringMeta(art: HubArtifact, key: string): string | null {
  const value = art.meta?.[key]
  return typeof value === 'string' && value ? value : null
}

function numberMeta(art: HubArtifact, key: string): number | null {
  const value = art.meta?.[key]
  return typeof value === 'number' ? value : null
}

function expiryLabel(expiresAt: number | null): string {
  if (!expiresAt) return 'No expiry — works until you revoke it.'
  return `Expires ${new Date(expiresAt * 1000).toLocaleString()}.`
}

/** „Share link": upublicznia artefakt przez xAI Files API. Pierwsze kliknięcie pokazuje
 *  kartę zgody (plik trafia do xAI, link jest publiczny); potem link + Copy + Revoke. */
export function ShareLinkButton({ conn, art }: { conn: Conn; art: HubArtifact }) {
  const [url, setUrl] = useState<string | null>(() => stringMeta(art, 'public_url'))
  const [expiresAt, setExpiresAt] = useState<number | null>(() => numberMeta(art, 'public_url_expires_at'))
  const [expiry, setExpiry] = useState<number | null>(86_400)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Link, który już wygasł, traktujemy jak brak linku (xAI zwraca wtedy 404).
  const active = url && (!expiresAt || expiresAt * 1000 > Date.now()) ? url : null

  async function create(): Promise<void> {
    setBusy(true)
    setError(null)
    try {
      const result = await createArtifactPublicUrl(conn, art.id, expiry)
      setUrl(result.public_url)
      setExpiresAt(result.expires_at)
    } catch (e) {
      setError(String((e as Error).message || e))
    } finally {
      setBusy(false)
    }
  }

  async function revoke(): Promise<void> {
    setBusy(true)
    setError(null)
    try {
      await revokeArtifactPublicUrl(conn, art.id)
      setUrl(null)
      setExpiresAt(null)
    } catch (e) {
      setError(String((e as Error).message || e))
    } finally {
      setBusy(false)
    }
  }

  async function copy(link: string): Promise<void> {
    if (await copyText(link)) {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    }
  }

  return (
    <Popover
      side="top"
      align="end"
      label="Share public link"
      trigger={({ toggle, open, triggerProps }) => (
        <IconButton
          label={active ? 'Public link' : 'Share link'}
          icon={<Link2 size={15} />}
          active={open || !!active}
          tooltip={!open}
          tooltipSide="top"
          onClick={toggle}
          {...triggerProps}
        />
      )}
    >
      {() => (
        <div className="w-72 p-2">
          {active ? (
            <>
              <p className="px-1 pb-1 text-sm font-medium text-fg">Public link</p>
              <div className="flex items-center gap-1 px-1">
                <input readOnly value={active} aria-label="Public link"
                  className="h-8 min-w-0 flex-1 rounded-md border border-border bg-surface-2 px-2 text-xs text-fg" />
                <IconButton label={copied ? 'Copied' : 'Copy link'} size="sm"
                  icon={copied ? <Check size={14} /> : <Copy size={14} />} onClick={() => void copy(active)} />
              </div>
              <p className="px-1 pt-1.5 text-xs text-muted">Anyone with this link can view the file. {expiryLabel(expiresAt)}</p>
              <div className="flex justify-end pt-2">
                <Button variant="danger" size="sm" onClick={() => void revoke()} disabled={busy}>
                  Revoke link
                </Button>
              </div>
            </>
          ) : (
            <>
              <p className="px-1 pb-1 text-sm font-medium text-fg">Create a public link?</p>
              <p className="px-1 pb-2 text-xs text-muted">
                This uploads the {art.type} to your xAI Files storage and creates a link on xAI&apos;s CDN.
                Anyone with the link can view it without signing in. You can revoke it at any time.
              </p>
              <label className="flex items-center justify-between gap-2 px-1 pb-2 text-xs text-muted">
                Link expires
                <Select size="sm" className="w-36" value={expiry === null ? 'never' : String(expiry)}
                  onChange={(e) => setExpiry(e.target.value === 'never' ? null : Number(e.target.value))}>
                  {EXPIRY_OPTIONS.map((option) => (
                    <option key={option.label} value={option.seconds === null ? 'never' : String(option.seconds)}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              </label>
              <div className="flex justify-end">
                <Button size="sm" onClick={() => void create()} disabled={busy}>
                  {busy ? 'Sharing…' : 'Create public link'}
                </Button>
              </div>
            </>
          )}
          {error ? <p className="px-1 pt-1 text-xs text-error">{error}</p> : null}
        </div>
      )}
    </Popover>
  )
}
