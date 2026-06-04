import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '../../lib/cn'

export function Card({
  title,
  subtitle,
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { title?: ReactNode; subtitle?: ReactNode }) {
  return (
    <div
      className={cn('rounded-2xl border border-border bg-surface p-6 shadow-[var(--shadow)]', className)}
      {...rest}
    >
      {title ? <h2 className="mb-1 text-base font-semibold text-fg">{title}</h2> : null}
      {subtitle ? <p className="mb-4 text-sm text-muted">{subtitle}</p> : null}
      {children}
    </div>
  )
}
