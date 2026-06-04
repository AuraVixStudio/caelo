import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Łączy klasy warunkowo (clsx) i scala kolizje Tailwinda (tailwind-merge). */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
