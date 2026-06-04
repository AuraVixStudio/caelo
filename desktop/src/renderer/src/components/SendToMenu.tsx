import { useState } from 'react'
import { Code2, MessageSquare, ScanText, Share2 } from 'lucide-react'
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

const ITEMS: Item[] = [
  { label: 'Chat', icon: <MessageSquare size={15} />, target: 'Chat' },
  { label: 'Describe', icon: <ScanText size={15} />, target: 'Chat', prompt: DESCRIBE_PROMPT },
  { label: 'Code', icon: <Code2 size={15} />, target: 'Code' }
]

/** „Send to…" — przenosi artefakt do innego trybu jako wejście (M9-F2). Pobiera
 *  gotowy blok z magistrali B4 i ustawia `pendingSend` w Hub context; tryb docelowy
 *  podnosi go w composerze. Artefakty bez bloku (np. wideo/audio → 415) pokazują błąd. */
export function SendToMenu({ conn, artifactId }: { conn: Conn; artifactId: string }) {
  const hub = useHub()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
      label="Send to"
      trigger={({ toggle, open, triggerProps }) => (
        <IconButton
          label="Send to…"
          icon={<Share2 size={16} />}
          active={open}
          tooltip={!open}
          tooltipSide="bottom-end"
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
          {ITEMS.map((item) => (
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
