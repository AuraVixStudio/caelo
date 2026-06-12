import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { Search } from 'lucide-react'
import { filterCommands, type Command } from '../lib/commands'
import { cn } from '../lib/cn'

// S35-m: selektor fokusowalnych (jak w ui/Popover) — Tab krąży w modalu, nie ucieka w tło.
const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
const LIST_ID = 'command-palette-list'
const optionId = (i: number): string => `command-palette-opt-${i}`

/** Paleta komend (M9-F5) — Ctrl/Cmd-K. Modal z fuzzy-search nad komendami; nawigacja
 *  klawiaturą (↑/↓/Enter/Esc). Prezentacyjny: komendy + open/onClose z App. */
export function CommandPalette({
  open,
  onClose,
  commands
}: {
  open: boolean
  onClose: () => void
  commands: Command[]
}) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const panelRef = useRef<HTMLDivElement | null>(null)
  const results = useMemo(() => filterCommands(commands, query), [commands, query])

  // Reset + autofocus przy otwarciu.
  useEffect(() => {
    if (!open) return
    setQuery('')
    setActive(0)
    const t = setTimeout(() => inputRef.current?.focus(), 0)
    return () => clearTimeout(t)
  }, [open])

  // Klamruj aktywny indeks do długości wyników (po filtrowaniu).
  useEffect(() => {
    setActive((a) => Math.min(a, Math.max(results.length - 1, 0)))
  }, [results.length])

  if (!open) return null

  function run(cmd?: Command): void {
    if (!cmd) return
    onClose()
    cmd.run()
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>): void {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((a) => Math.min(a + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => Math.max(a - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      run(results[active])
    } else if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    }
  }

  // S35-m: focus-trap — Tab/Shift+Tab krąży w obrębie modalu (jak ui/Popover).
  function onPanelKeyDown(e: KeyboardEvent<HTMLDivElement>): void {
    if (e.key !== 'Tab') return
    const panel = panelRef.current
    if (!panel) return
    const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE))
    if (items.length === 0) {
      e.preventDefault()
      return
    }
    const first = items[0]
    const last = items[items.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 px-4 pt-[15vh]"
      onClick={onClose}
      role="presentation"
    >
      <div
        ref={panelRef}
        className="w-full max-w-lg overflow-hidden rounded-xl border border-border bg-surface shadow-[var(--shadow)]"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onPanelKeyDown}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
      >
        <div className="flex items-center gap-2 border-b border-border px-3">
          <Search size={16} className="shrink-0 text-muted" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Jump to a mode or action…"
            aria-label="Command palette search"
            role="combobox"
            aria-expanded={results.length > 0}
            aria-controls={LIST_ID}
            aria-autocomplete="list"
            aria-activedescendant={results.length ? optionId(active) : undefined}
            className="w-full bg-transparent py-3 text-sm text-fg outline-none placeholder:text-muted"
          />
        </div>
        <div className="max-h-80 overflow-y-auto p-1" role="listbox" id={LIST_ID} aria-label="Commands">
          {results.length === 0 ? (
            <p className="px-3 py-6 text-center text-sm text-muted">No matching commands</p>
          ) : (
            results.map((c, i) => (
              <button
                key={c.id}
                id={optionId(i)}
                role="option"
                aria-selected={i === active}
                onMouseEnter={() => setActive(i)}
                onClick={() => run(c)}
                className={cn(
                  'flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm outline-none transition-colors',
                  i === active ? 'bg-surface-2 text-fg' : 'text-muted'
                )}
              >
                <span className="truncate">{c.title}</span>
                {c.hint ? <span className="shrink-0 text-xs text-muted">{c.hint}</span> : null}
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
