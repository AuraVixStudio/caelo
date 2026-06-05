import { useState } from 'react'
import { Film, Share2, Wand2 } from 'lucide-react'
import { getArtifactDataUri, type Conn, type HubArtifact } from '../lib/api'
import { useHub } from '../lib/hub'
import { IconButton } from './ui/IconButton'
import { Popover } from './ui/Popover'

/** „Send to…" dla artefaktu-wideo (M11): załaduj wideo jako źródło do edycji lub
 *  rozszerzenia w panelu Video. Wideo nie ma bloku wejściowego LLM (B4 → 415), więc
 *  pobieramy jego bajty jako data-URI (`getArtifactDataUri`) i przekazujemy przez Hub.
 *  Otwiera się W GÓRĘ (`side="top"`) — karty bywają przy dole, by nie uciekał z ekranu. */
export function VideoSendMenu({ conn, art }: { conn: Conn; art: HubArtifact }) {
  const hub = useHub()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const prompt = typeof art.meta?.prompt === 'string' ? art.meta.prompt : ''
  const name = (prompt && prompt.slice(0, 40)) || 'Recent video'

  async function go(mode: 'edit' | 'extend', close: () => void): Promise<void> {
    setBusy(true)
    setError(null)
    try {
      const uri = await getArtifactDataUri(conn, art.id)
      hub.sendVideoToVideo({ name, uri, mode })
      close()
    } catch (e) {
      const status = (e as { status?: number }).status
      setError(status === 413 ? 'Video too large to reuse.' : 'Could not load this video.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Popover
      side="top"
      align="end"
      label="Send video to"
      trigger={({ toggle, open, triggerProps }) => (
        <IconButton
          label="Send to…"
          icon={<Share2 size={16} />}
          active={open}
          tooltip={!open}
          tooltipSide="top"
          onClick={toggle}
          {...triggerProps}
        />
      )}
    >
      {(close) => (
        <div className="w-44 p-1">
          <p className="px-2 pb-1 pt-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
            Send to
          </p>
          <button
            disabled={busy}
            onClick={() => go('edit', close)}
            className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-sm text-fg outline-none transition-colors hover:bg-surface-2 focus-visible:bg-surface-2 disabled:opacity-50"
          >
            <span className="text-muted">
              <Wand2 size={15} />
            </span>
            Edit video
          </button>
          <button
            disabled={busy}
            onClick={() => go('extend', close)}
            className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-sm text-fg outline-none transition-colors hover:bg-surface-2 focus-visible:bg-surface-2 disabled:opacity-50"
          >
            <span className="text-muted">
              <Film size={15} />
            </span>
            Extend video
          </button>
          {error ? <p className="px-2 pb-1 pt-1 text-xs text-error">{error}</p> : null}
        </div>
      )}
    </Popover>
  )
}
