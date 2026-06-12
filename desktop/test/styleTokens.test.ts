import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import { dirname, resolve } from 'path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (rel: string): string => readFileSync(resolve(here, rel), 'utf8')

// S35-b: klasy Tailwind nie są walidowane przez tsc/ESLint — strażnik źródłowy pilnuje,
// że Settings używa istniejącego tokenu `text-warn`, nie literówki `text-warning`.
describe('design tokens (S35-b)', () => {
  it('Settings.tsx nie używa nieistniejącego text-warning', () => {
    const src = read('../src/renderer/src/components/Settings.tsx')
    expect(src).not.toMatch(/\btext-warning\b/)
    expect(src).toMatch(/\btext-warn\b/)
  })
})
