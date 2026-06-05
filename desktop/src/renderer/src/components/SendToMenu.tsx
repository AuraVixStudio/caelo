import { useState } from 'react'
import { Code2, ImagePlus, MessageSquare, ScanText, Share2, Video as VideoIcon } from 'lucide-react'
import { getArtifactInputBlock, type Conn } from '../lib/api'
import { useHub } from '../lib/hub'
import type { HubModule } from '../lib/hubQuery'
import { IconButton } from './ui/IconButton'
import { Popover } from './ui/Popover'

const DESCRIBE_PROMPT = 'Describe this image in detail.'

interface Item {
  label: string
  icon: React.ReactNode
  target: HubModule
  prompt?: string
}

const BASE_ITEMS: Item[] = [
  { label: 'Chat', icon: <MessageSquare size={15} />, target: 'Chat' },
  { label: 'Describe', icon: <ScanText size={15} />, target: 'Chat', prompt: DESCRIBE_PROMPT },
  { label: 'Code', icon: <Code2 size={15} />, target: 'Code' }
]

// M11: dla artefaktów-obrazów domknij pętlę twórczą — wyślij obraz jako referencję
// do edycji (Image) albo jako kadr startowy do animacji (Video).
const IMAGE_ITEMS: Item[] = [
  { label: 'Edit in Image', icon: <ImagePlus size={15} />, target: 'Image' },
  { label: 'Animate (Video)', icon: <VideoIcon size={15} />, target: 'Video' }
]

/** „Send to…" — przenosi artefakt do innego trybu jako wejście (M9-F2, M11). Pobiera
 *  gotowy blok z magistrali B4 i ustawia `pendingSend` w Hub context; tryb docelowy
 *  podnosi go w composerze / jako referencję. Artefakty bez bloku (wideo/audio → 415)
 *  pokazują błąd. `imageActions` dokłada „Edit in Image"/„Animate (Video)". */
export function SendToMenu({
  conn,
  artifactId,
  imageActions = false,
  side = 'bottom'
}: {
  conn: Conn
  artifactId: string
  imageActions?: boolean
  /** Strona otwarcia menu. W siatkach (galeria) ustaw 'top' — karty bywają przy dole. */
  side?: 'top' | 'bottom'
}) {
  const hub = useHub()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const items = imageActions ? [...BASE_ITEMS, ...IMAGE_ITEMS] : BASE_ITEMS

  async function go(item: Item, close: () => void): Promise<void> {
    setBusy(true)
    setError(null)
    try {
      const ib = await getArtifactInputBlock(conn, artifactId)
      hub.sendTo({ target: item.target, block: ib, label: ib.name, prompt: item.prompt })
      close()
    } catch (e) {
      const status = (e as { status?: number }).status
      setError(status === 415 ? "This artifact can't be used as input." : 'Send failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Popover
      align="end"
      side={side}
      label="Send to"
      trigger={({ toggle, open, triggerProps }) => (
        <IconButton
          label="Send to…"
          icon={<Share2 size={16} />}
          active={open}
          tooltip={!open}
          tooltipSide={side === 'top' ? 'top-end' : 'bottom-end'}
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
          {items.map((item) => (
            <button
              key={item.label}
              disabled={busy}
              onClick={() => go(item, close)}
              className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-sm text-fg outline-none transition-colors hover:bg-surface-2 focus-visible:bg-surface-2 disabled:opacity-50"
            >
              <span className="text-muted">{item.icon}</span>
              {item.label}
            </button>
          ))}
          {error ? <p className="px-2 pb-1 pt-1 text-xs text-error">{error}</p> : null}
        </div>
      )}
    </Popover>
  )
}
