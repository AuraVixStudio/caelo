import type { Ref, SelectHTMLAttributes } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '../../lib/cn'

type Size = 'sm' | 'md'

const SIZES: Record<Size, string> = {
  sm: 'h-8 pl-2.5 pr-7 text-xs rounded-md',
  md: 'h-9 pl-3 pr-8 text-sm rounded-lg'
}

/** Natywny <select> przestylowany (appearance-none + chevron). */
export function Select({
  className,
  size = 'md',
  ref,
  children,
  ...rest
}: Omit<SelectHTMLAttributes<HTMLSelectElement>, 'size'> & {
  size?: Size
  ref?: Ref<HTMLSelectElement>
}) {
  return (
    <div className="relative inline-flex w-full">
      <select
        ref={ref}
        className={cn(
          'w-full appearance-none border border-border bg-surface-2 font-medium text-fg',
          'transition-colors focus:border-accent focus:outline-none',
          'disabled:cursor-not-allowed disabled:opacity-60',
          SIZES[size],
          className
        )}
        {...rest}
      >
        {children}
      </select>
      <ChevronDown
        size={size === 'sm' ? 13 : 15}
        className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-muted"
      />
    </div>
  )
}
