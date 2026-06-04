import { Separator } from 'react-resizable-panels'
import { cn } from '../../lib/cn'

/**
 * Uchwyt do zmiany rozmiaru paneli (react-resizable-panels v4 `Separator`).
 * `orientation` = orientacja grupy: 'horizontal' → pionowa kreska (col-resize),
 * 'vertical' → pozioma kreska (row-resize). Akcent na hover/drag.
 */
export function ResizeHandle({
  orientation = 'horizontal',
  className
}: {
  orientation?: 'horizontal' | 'vertical'
  className?: string
}) {
  const horizontal = orientation === 'horizontal'
  return (
    <Separator
      className={cn(
        'group/rh relative flex items-center justify-center bg-transparent',
        horizontal ? 'w-1.5 cursor-col-resize' : 'h-1.5 cursor-row-resize',
        className
      )}
    >
      <span
        className={cn(
          'bg-border transition-colors group-hover/rh:bg-accent group-active/rh:bg-accent',
          horizontal ? 'h-full w-px' : 'h-px w-full'
        )}
      />
    </Separator>
  )
}
