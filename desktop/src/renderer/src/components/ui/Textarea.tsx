import type { Ref, TextareaHTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

export function Textarea({
  className,
  ref,
  ...rest
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { ref?: Ref<HTMLTextAreaElement> }) {
  return (
    <textarea
      ref={ref}
      className={cn(
        'w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-fg',
        'placeholder:text-muted transition-colors focus:border-accent focus:outline-none',
        'disabled:cursor-not-allowed disabled:opacity-60',
        className
      )}
      {...rest}
    />
  )
}
