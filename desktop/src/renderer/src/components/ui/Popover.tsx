import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode
} from 'react'
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

/**
 * Popover z zamykaniem po kliknięciu poza / Esc. Trigger i treść jako render-propsy.
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
  const ref = useRef<HTMLDivElement | null>(null)
  const panelRef = useRef<HTMLDivElement | null>(null)
  const wasOpen = useRef(false)
  const close = (): void => setOpen(false)
  const toggle = (): void => setOpen((v) => !v)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent): void => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onEsc = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onEsc)
    }
  }, [open])

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
      {open ? (
        <div
          ref={panelRef}
          role="dialog"
          aria-label={label}
          tabIndex={-1}
          onKeyDown={onPanelKeyDown}
          className={cn(
            'absolute z-50 min-w-48 rounded-xl border border-border bg-surface p-1.5 outline-none',
            'shadow-[var(--shadow-pop)]',
            align === 'end' ? 'right-0' : 'left-0',
            side === 'top' ? 'bottom-full mb-1.5' : 'top-full mt-1.5',
            className
          )}
        >
          {typeof children === 'function' ? children(close) : children}
        </div>
      ) : null}
    </div>
  )
}
