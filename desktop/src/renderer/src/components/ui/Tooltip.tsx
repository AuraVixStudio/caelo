import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

type Side =
  | 'top'
  | 'bottom'
  | 'left'
  | 'right'
  | 'bottom-end'
  | 'top-end'
  | 'bottom-start'
  | 'top-start'

const SIDE: Record<Side, string> = {
  bottom: 'top-full left-1/2 mt-1.5 -translate-x-1/2',
  top: 'bottom-full left-1/2 mb-1.5 -translate-x-1/2',
  right: 'left-full top-1/2 ml-1.5 -translate-y-1/2',
  left: 'right-full top-1/2 mr-1.5 -translate-y-1/2',
  // Wyrównane do prawej krawędzi przycisku — dla kontrolek przy prawej krawędzi
  // okna, gdzie wyśrodkowany tooltip zostałby ucięty.
  'bottom-end': 'top-full right-0 mt-1.5',
  'top-end': 'bottom-full right-0 mb-1.5',
  // Wyrównane do LEWEJ krawędzi przycisku — dla kontrolek przy lewej krawędzi
  // wąskiego panelu (np. composer agenta), gdzie wyśrodkowany tooltip był ucinany.
  'bottom-start': 'top-full left-0 mt-1.5',
  'top-start': 'bottom-full left-0 mb-1.5'
}

/** Lekki tooltip CSS-only (group-hover), odwrócony kolorystycznie (bg-fg/text-bg). */
export function Tooltip({
  label,
  side = 'bottom',
  children
}: {
  label: ReactNode
  side?: Side
  children: ReactNode
}) {
  return (
    <span className="group/tt relative inline-flex">
      {children}
      <span
        role="tooltip"
        className={cn(
          'pointer-events-none absolute z-50 whitespace-nowrap rounded-md bg-fg px-2 py-1',
          'text-xs font-medium text-bg opacity-0 shadow-[var(--shadow-pop)] transition-opacity duration-150',
          'group-hover/tt:opacity-100',
          SIDE[side]
        )}
      >
        {label}
      </span>
    </span>
  )
}
