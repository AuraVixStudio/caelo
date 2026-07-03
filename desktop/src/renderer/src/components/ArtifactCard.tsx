import { useState, type ReactNode } from 'react'
import { Check, Copy, RotateCcw, Trash2 } from 'lucide-react'
import { artifactPrompt, deleteArtifact, type Conn, type HubArtifact } from '../lib/api'
import { copyText } from '../lib/clipboard'
import { useHub } from '../lib/hub'
import type { HubModule } from '../lib/hubQuery'
import { ArtifactMedia } from './ArtifactMedia'
import { SendToMenu } from './SendToMenu'
import { VideoSendMenu } from './VideoSendMenu'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'
import { IconButton } from './ui/IconButton'
import { Popover } from './ui/Popover'

function modelOf(art: HubArtifact): string {
  const m = art.meta?.model
  return typeof m === 'string' ? m : ''
}

/** Moduł twórczy, do którego „Reuse prompt" wstawi prompt (obraz→Image, wideo→Video).
 *  Null dla pozostałych typów (audio itp.) — wtedy pokazujemy tylko „Copy". */
function reuseTargetOf(art: HubArtifact): HubModule | null {
  if (art.type === 'image') return 'Image'
  if (art.type === 'video') return 'Video'
  return null
}

// Powyżej tej długości prompt jest w galerii skracany (pokazujemy początek) —
// z afordancją „Show more" do rozwinięcia całości.
const PROMPT_CLAMP_CHARS = 90

/** Prompt zapisany przy generacji: skrócony podgląd (rozwijany „Show more") +
 *  „Reuse prompt" (wstawia do panelu Image/Video i przechodzi tam) + „Copy".
 *  Nie renderuje się, gdy artefakt nie ma promptu (np. wgrane medium). */
function PromptBar({ art }: { art: HubArtifact }) {
  const { reusePrompt } = useHub()
  const [copied, setCopied] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const prompt = artifactPrompt(art)
  const target = reuseTargetOf(art)
  if (!prompt) return null

  const long = prompt.length > PROMPT_CLAMP_CHARS

  async function copy(): Promise<void> {
    if (await copyText(prompt)) {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    }
  }

  return (
    <div className="flex flex-col gap-1.5 border-t border-border pt-2">
      <p
        className={expanded ? 'text-xs leading-snug text-muted' : 'line-clamp-2 text-xs leading-snug text-muted'}
        title={long && !expanded ? prompt : undefined}
      >
        {prompt}
      </p>
      {long ? (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="self-start text-[11px] font-medium text-accent hover:underline"
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      ) : null}
      <div className="flex items-center gap-1">
        {target ? (
          <Button
            variant="ghost"
            size="sm"
            icon={<RotateCcw size={14} />}
            onClick={() => reusePrompt(target, prompt)}
          >
            Reuse prompt
          </Button>
        ) : null}
        <IconButton
          label={copied ? 'Copied' : 'Copy prompt'}
          size="sm"
          icon={copied ? <Check size={14} /> : <Copy size={14} />}
          onClick={copy}
        />
      </div>
    </div>
  )
}

/** Przycisk usuwania artefaktu z potwierdzeniem (Popover) — kasuje rekord + plik.
 *  Po sukcesie woła `onDeleted(id)`, by rodzic zdjął kartę z listy. */
function DeleteButton({
  conn,
  art,
  onDeleted
}: {
  conn: Conn
  art: HubArtifact
  onDeleted: (id: string) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function remove(close: () => void): Promise<void> {
    setBusy(true)
    setError(null)
    try {
      await deleteArtifact(conn, art.id)
      onDeleted(art.id)
      close()
    } catch (e) {
      setError(String((e as Error).message || e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Popover
      side="top"
      align="end"
      label="Delete artifact"
      trigger={({ toggle, open, triggerProps }) => (
        <IconButton
          label="Delete"
          icon={<Trash2 size={15} />}
          active={open}
          tooltip={!open}
          tooltipSide="top"
          onClick={toggle}
          {...triggerProps}
        />
      )}
    >
      {(close) => (
        <div className="w-52 p-2">
          <p className="px-1 pb-2 text-sm text-fg">
            Delete this {art.type}? This removes the file and can&apos;t be undone.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={close} disabled={busy}>
              Cancel
            </Button>
            <Button variant="danger" size="sm" onClick={() => remove(close)} disabled={busy}>
              Delete
            </Button>
          </div>
          {error ? <p className="px-1 pt-1 text-xs text-error">{error}</p> : null}
        </div>
      )}
    </Popover>
  )
}

/** Karta artefaktu (M11-F4): podgląd + „Open" + „Send to…" (obraz: czat/edit/animate;
 *  wideo: edit/extend) + usuń (gdy podano `onDeleted`) + miejsce na akcje (np. „Variations"). */
export function ArtifactCard({
  conn,
  art,
  mediaClassName,
  onDeleted,
  children
}: {
  conn: Conn
  art: HubArtifact
  mediaClassName?: string
  onDeleted?: (id: string) => void
  children?: ReactNode
}) {
  const isImage = art.type === 'image'
  const isVideo = art.type === 'video'
  const model = modelOf(art)
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-2.5 shadow-[var(--shadow)]">
      <ArtifactMedia conn={conn} art={art} className={mediaClassName ?? 'h-44 w-full rounded-lg'} />
      <div className="flex items-center justify-between gap-2">
        <Badge tone={art.type === 'video' ? 'accent' : 'success'}>{art.type}</Badge>
        {model ? (
          <span className="truncate text-[11px] text-muted" title={model}>
            {model}
          </span>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-1">
        {art.path ? (
          <Button variant="outline" size="sm" onClick={() => window.caelo.openPath(art.path)}>
            Open
          </Button>
        ) : null}
        {isImage ? <SendToMenu conn={conn} artifactId={art.id} imageActions side="top" /> : null}
        {isVideo ? <VideoSendMenu conn={conn} art={art} /> : null}
        {children}
        {onDeleted ? (
          <span className="ml-auto">
            <DeleteButton conn={conn} art={art} onDeleted={onDeleted} />
          </span>
        ) : null}
      </div>
      <PromptBar art={art} />
    </div>
  )
}
