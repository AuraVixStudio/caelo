import type { InputHTMLAttributes, Ref } from 'react'
import { cn } from '../../lib/cn'

export function Input({
  className,
  ref,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & { ref?: Ref<HTMLInputElement> }) {
  return (
    <input
      ref={ref}
      className={cn(
        'h-9 w-full rounded-lg border border-border bg-surface-2 px-3 text-sm text-fg',
        'placeholder:text-muted transition-colors focus:border-accent focus:outline-none',
        'disabled:cursor-not-allowed disabled:opacity-60',
        className
      )}
      {...rest}
    />
  )
}
