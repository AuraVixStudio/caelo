import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '../../lib/cn'

/** Przewijalny kontener strony z nagłówkiem (h1 + podtytuł + opcjonalne akcje). */
export function Page({
  title,
  subtitle,
  actions,
  maxWidth = 'max-w-5xl',
  children
}: {
  title: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  maxWidth?: string
  children: ReactNode
}) {
  return (
    <main className="min-w-0 flex-1 overflow-y-auto">
      <div className={cn('mx-auto px-8 py-8', maxWidth)}>
        <header className="mb-6 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
            {subtitle ? <p className="mt-1 text-sm text-muted">{subtitle}</p> : null}
          </div>
          {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
        </header>
        {children}
      </div>
    </main>
  )
}

/** Etykietowane pole formularza (label nad kontrolką). */
export function Field({
  label,
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { label: ReactNode }) {
  return (
    <div className={cn('flex flex-col gap-1.5', className)} {...rest}>
      <span className="text-xs font-medium text-muted">{label}</span>
      {children}
    </div>
  )
}
