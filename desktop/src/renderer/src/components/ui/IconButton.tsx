import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cn } from '../../lib/cn'
import { Tooltip } from './Tooltip'

type Size = 'sm' | 'md'

const SIZES: Record<Size, string> = {
  sm: 'h-7 w-7 rounded-md',
  md: 'h-9 w-9 rounded-lg'
}

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Etykieta dostępności + treść tooltipu. */
  label: string
  icon: ReactNode
  active?: boolean
  size?: Size
  tooltip?: boolean
  tooltipSide?: 'top' | 'bottom' | 'left' | 'right' | 'bottom-end' | 'top-end'
}

export function IconButton({
  label,
  icon,
  active = false,
  size = 'md',
  tooltip = true,
  tooltipSide = 'bottom',
  className,
  ...rest
}: IconButtonProps) {
  const btn = (
    <button
      aria-label={label}
      aria-pressed={active}
      className={cn(
        'inline-flex items-center justify-center transition-colors',
        'disabled:cursor-not-allowed disabled:opacity-50',
        active
          ? 'bg-accent/12 text-accent'
          : 'text-muted hover:bg-surface-2 hover:text-fg',
        SIZES[size],
        className
      )}
      {...rest}
    >
      {icon}
    </button>
  )
  return tooltip ? (
    <Tooltip label={label} side={tooltipSide}>
      {btn}
    </Tooltip>
  ) : (
    btn
  )
}
