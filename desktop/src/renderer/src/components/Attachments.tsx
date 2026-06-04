import type { ChangeEvent } from 'react'
import { Paperclip, X } from 'lucide-react'
import type { ChatAttachment } from '../lib/api'
import { cn } from '../lib/cn'

/** Przycisk dołączania plików (spinacz) z ukrytym <input type=file multiple>. */
export function AttachButton({
  onPick,
  disabled,
  className
}: {
  onPick: (files: FileList | null) => void
  disabled?: boolean
  className?: string
}) {
  return (
    // P2-6: input jest `sr-only` (nie `hidden`), więc pozostaje fokusowalny z klawiatury;
    // etykieta dostaje pierścień fokusu, gdy input jest aktywny.
    <label
      title="Attach images or text files"
      className={cn(
        'flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-xl text-muted transition-colors hover:bg-surface-2 hover:text-fg',
        'focus-within:ring-2 focus-within:ring-accent',
        disabled && 'pointer-events-none opacity-50',
        className
      )}
    >
      <Paperclip size={18} />
      <input
        type="file"
        multiple
        className="sr-only"
        aria-label="Attach images or text files"
        disabled={disabled}
        onChange={(e: ChangeEvent<HTMLInputElement>) => {
          onPick(e.target.files)
          e.target.value = ''
        }}
      />
    </label>
  )
}

/** Wiersz „chipów" załączników (miniatura obrazu / nazwa pliku) z opcją usunięcia. */
export function AttachmentChips({
  items,
  onRemove,
  className
}: {
  items: ChatAttachment[]
  onRemove?: (id: string) => void
  className?: string
}) {
  if (!items.length) return null
  return (
    <div className={cn('flex flex-wrap gap-2', className)}>
      {items.map((a) => (
        <div
          key={a.id}
          className="flex items-center gap-1.5 rounded-lg border border-border bg-surface-2 py-1 pl-1.5 pr-2 text-xs"
        >
          {a.kind === 'image' && a.uri ? (
            <img src={a.uri} alt={a.name} className="h-6 w-6 rounded object-cover" />
          ) : (
            <span className="flex h-6 w-6 items-center justify-center rounded bg-surface text-[9px] font-bold uppercase text-muted">
              Txt
            </span>
          )}
          <span className="max-w-[140px] truncate">{a.name}</span>
          {onRemove ? (
            <button
              onClick={() => onRemove(a.id)}
              aria-label={`Remove ${a.name}`}
              className="ml-0.5 rounded text-muted outline-none transition-colors hover:text-error focus-visible:ring-2 focus-visible:ring-accent"
              title="Remove"
            >
              <X size={12} />
            </button>
          ) : null}
        </div>
      ))}
    </div>
  )
}
