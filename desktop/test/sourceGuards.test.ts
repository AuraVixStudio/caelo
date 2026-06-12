import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import { dirname, resolve } from 'path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (rel: string): string => readFileSync(resolve(here, rel), 'utf8')

// Strażniki źródłowe dla zmian trudnych do unit-testu bez ciężkich zależności
// (xterm / proces główny Electron).
describe('Terminal (S35-d)', () => {
  const src = read('../src/renderer/src/components/code/Terminal.tsx')
  it('ResizeObserver — refit przy separatorze paneli', () => {
    expect(src).toMatch(/new ResizeObserver/)
  })
  it('initial resize na onopen (pty ≠ 80×24)', () => {
    expect(src).toMatch(/onopen[\s\S]{0,200}type:\s*'resize'/)
  })
  it('live theme przez options.theme (bez recreate WS)', () => {
    expect(src).toMatch(/\.options\.theme\s*=/)
  })
  it('termTheme rozróżnia dark/light', () => {
    expect(src).toMatch(/0e0e10/)
    expect(src).toMatch(/ffffff/)
  })
})

describe('main handshake (S35-f)', () => {
  it('zepsuty handshake JSON ubija sidecar (killCoreForRestart z „bad handshake")', () => {
    const src = read('../src/main/index.ts')
    // kill wołany z komunikatem „bad handshake" = ścieżka odzysku przy złym JSON-ie handshake'u
    expect(src).toMatch(/killCoreForRestart\(`bad handshake/)
  })
})
