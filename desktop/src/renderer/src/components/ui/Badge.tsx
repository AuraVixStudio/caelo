import type { HTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

type Tone = 'neutral' | 'accent' | 'success' | 'error' | 'warn' | 'info'

const TONES: Record<Tone, string> = {
  neutral: 'bg-surface-2 text-muted',
  accent: 'bg-accent/12 text-accent',
  success: 'bg-success/15 text-success',
  error: 'bg-error/15 text-error',
  warn: 'bg-warn/15 text-warn',
  info: 'bg-info/15 text-info'
}

export function Badge({
  tone = 'neutral',
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide',
        TONES[tone],
        className
      )}
      {...rest}
    >
      {children}
    </span>
  )
}
