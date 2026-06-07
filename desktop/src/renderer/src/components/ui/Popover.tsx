import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode
} from 'react'
import { createPortal } from 'react-dom'
import { cn } from '../../lib/cn'

/** Propsy do rozłożenia na wyzwalaczu (P2-6: `aria-expanded`/`aria-haspopup`). */
export interface PopoverTriggerProps {
  'aria-haspopup': 'dialog'
  'aria-expanded': boolean
}

interface TriggerArgs {
  open: boolean
  toggle: () => void
  close: () => void
  triggerProps: PopoverTriggerProps
}

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

const GAP = 6 // odstęp panel↔wyzwalacz
const MARGIN = 8 // minimalny margines od krawędzi viewportu

/**
 * Popover z zamykaniem po kliknięciu poza / Esc. Trigger i treść jako render-propsy.
 *
 * Panel renderowany jest w **portalu do `document.body`** z pozycjonowaniem `fixed`
 * liczonym z prostokąta wyzwalacza — dzięki temu nie jest przycinany przez przodków z
 * `overflow: hidden` (np. panele `react-resizable-panels`, które mają wymuszony
 * `overflow: hidden`). Pozycja jest klampowana do viewportu i odświeżana przy
 * scrollu/resize; gdy na wybranej stronie (`side`) brak miejsca — panel jest odbijany.
 *
 * Dostępność (P2-6): panel ma `role="dialog"` + `aria-label`; przy otwarciu fokus
 * wchodzi do panelu, Tab jest w nim uwięziony (focus-trap), a po zamknięciu wraca na
 * wyzwalacz. Wyzwalacz dostaje `triggerProps` (`aria-expanded`/`aria-haspopup`).
 */
export function Popover({
  trigger,
  children,
  align = 'start',
  side = 'bottom',
  className,
  label = 'Menu'
}: {
  trigger: (args: TriggerArgs) => ReactNode
  children: ReactNode | ((close: () => void) => ReactNode)
  align?: 'start' | 'end'
  side?: 'bottom' | 'top'
  className?: string
  label?: string
}) {
  const [open, setOpen] = useState(false)
  // null = jeszcze niezmierzony (panel ukryty, by uniknąć mignięcia w lewym górnym rogu).
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)
  const ref = useRef<HTMLDivElement | null>(null) // opakowanie wyzwalacza
  const panelRef = useRef<HTMLDivElement | null>(null) // pływający panel (w portalu)
  const wasOpen = useRef(false)
  const close = (): void => setOpen(false)
  const toggle = (): void => setOpen((v) => !v)

  // Wylicz pozycję `fixed` z prostokąta wyzwalacza; klampuj do viewportu, odbij gdy brak miejsca.
  const reposition = useCallback((): void => {
    const trigger = ref.current
    const panel = panelRef.current
    if (!trigger) return
    const r = trigger.getBoundingClientRect()
    const pw = panel?.offsetWidth ?? 0
    const ph = panel?.offsetHeight ?? 0

    let left = align === 'end' ? r.right - pw : r.left
    left = Math.max(MARGIN, Math.min(left, window.innerWidth - pw - MARGIN))

    let top = side === 'top' ? r.top - ph - GAP : r.bottom + GAP
    if (side === 'top' && top < MARGIN && r.bottom + GAP + ph <= window.innerHeight - MARGIN) {
      top = r.bottom + GAP // brak miejsca u góry → otwórz w dół
    } else if (
      side === 'bottom' &&
      top + ph > window.innerHeight - MARGIN &&
      r.top - ph - GAP >= MARGIN
    ) {
      top = r.top - ph - GAP // brak miejsca u dołu → otwórz w górę
    }
    top = Math.max(MARGIN, Math.min(top, window.innerHeight - ph - MARGIN))
    setPos({ top, left })
  }, [align, side])

  // Pomiar po zamontowaniu panelu (layout effect = przed malowaniem, brak mignięcia).
  useLayoutEffect(() => {
    if (!open) {
      setPos(null)
      return
    }
    reposition()
  }, [open, reposition])

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent): void => {
      const t = e.target as Node
      if (ref.current?.contains(t)) return
      if (panelRef.current?.contains(t)) return
      setOpen(false)
    }
    const onEsc = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') setOpen(false)
    }
    const onReflow = (): void => reposition()
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onEsc)
    // `true` (capture) łapie też scroll w wewnętrznych kontenerach, nie tylko window.
    window.addEventListener('scroll', onReflow, true)
    window.addEventListener('resize', onReflow)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onEsc)
      window.removeEventListener('scroll', onReflow, true)
      window.removeEventListener('resize', onReflow)
    }
  }, [open, reposition])

  // Zarządzanie fokusem: przy otwarciu fokus wchodzi do panelu; przy zamknięciu wraca
  // na wyzwalacz (pierwszy fokusowalny w korzeniu Popovera — stabilny, nawet gdy
  // wyzwalacz przemontuje się, np. IconButton zmieniający opakowanie Tooltip na `open`).
  // Przywracamy tylko, gdy fokus i tak by zniknął (był w panelu / uciekł do body) — nie
  // wyrywamy fokusu, gdy użytkownik kliknął inny element. Pomijamy montaż (wasOpen).
  useEffect(() => {
    if (open) {
      wasOpen.current = true
      const panel = panelRef.current
      const first = panel?.querySelector<HTMLElement>(FOCUSABLE)
      ;(first ?? panel)?.focus()
    } else if (wasOpen.current) {
      wasOpen.current = false
      const root = ref.current
      const active = document.activeElement
      if (root && (active === document.body || root.contains(active))) {
        root.querySelector<HTMLElement>(FOCUSABLE)?.focus()
      }
    }
  }, [open])

  function onPanelKeyDown(e: ReactKeyboardEvent<HTMLDivElement>): void {
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

  const triggerProps: PopoverTriggerProps = { 'aria-haspopup': 'dialog', 'aria-expanded': open }

  return (
    <div className="relative inline-flex" ref={ref}>
      {trigger({ open, toggle, close, triggerProps })}
      {open && typeof document !== 'undefined'
        ? createPortal(
            <div
              ref={panelRef}
              role="dialog"
              aria-label={label}
              tabIndex={-1}
              onKeyDown={onPanelKeyDown}
              style={{
                position: 'fixed',
                top: pos?.top ?? 0,
                left: pos?.left ?? 0,
                visibility: pos ? 'visible' : 'hidden'
              }}
              className={cn(
                'z-50 min-w-48 rounded-xl border border-border bg-surface p-1.5 outline-none',
                'shadow-[var(--shadow-pop)]',
                className
              )}
            >
              {typeof children === 'function' ? children(close) : children}
            </div>,
            document.body
          )
        : null}
    </div>
  )
}
