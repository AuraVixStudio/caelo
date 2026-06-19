import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import { dirname, resolve } from 'path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (rel: string): string => readFileSync(resolve(here, rel), 'utf8')

// Regresja D3 (live): CSP `script-src` bez `blob:` blokuje AudioWorklet głosu
// (MicCapture ładuje procesor PCM16 z Blob URL — audioStream.ts). Bez tego Talk/Live/
// STT-stream padają z „Audio capture is unavailable in this environment." Strażnik
// źródłowy: meta CSP musi dopuszczać blob: w script-src.
describe('CSP — AudioWorklet (D3 regresja)', () => {
  const html = read('../src/renderer/index.html')

  it('istnieje dokładnie jedna meta CSP', () => {
    const matches = html.match(/http-equiv="Content-Security-Policy"/g) || []
    expect(matches).toHaveLength(1)
  })

  it('script-src dopuszcza blob: (AudioWorklet głosu)', () => {
    // Bierz `content` należące do meta CSP (nie pierwsze content="" w pliku = viewport).
    const m = html.match(/Content-Security-Policy"[\s\S]*?content="([^"]*)"/)
    expect(m).not.toBeNull()
    const csp = m![1]
    const scriptSrc = csp
      .split(';')
      .map((d) => d.trim())
      .find((d) => d.startsWith('script-src'))
    expect(scriptSrc, 'brak dyrektywy script-src w CSP').toBeTruthy()
    expect(scriptSrc).toContain('blob:')
  })
})
