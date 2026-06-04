import type { InputHTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

/**
 * Suwak (range) spójny z motywem — używa natywnego `accent-color` (zmienna --accent),
 * więc działa w trybie jasnym i ciemnym bez dodatkowego CSS.
 */
export function Slider({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      type="range"
      className={cn(
        'h-1.5 w-full cursor-pointer appearance-none rounded-full bg-surface-2 accent-accent',
        className
      )}
      {...rest}
    />
  )
}
