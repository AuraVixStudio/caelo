// @vitest-environment jsdom
// Kompresja obrazów wejściowych: małe przechodzą bez zmian; zbyt duże są
// kompresowane, a gdy Canvas/WebP jest niedostępny — zwracamy oryginał (bez crasha).
import { describe, it, expect, vi, beforeEach } from 'vitest'

// fileToDataUri zależy od FileReader — mockujemy, by testy były deterministyczne
// i niezależne od kształtu Bloba w jsdom.
const readMock = vi.fn<[File], Promise<string>>()
vi.mock('../src/renderer/src/lib/files', () => ({
  fileToDataUri: (f: File) => readMock(f)
}))

import { compressImageIfNeeded } from '../src/renderer/src/lib/imageCompress'

function fakeFile(name = 'ref.png'): File {
  return new File([new Uint8Array([1, 2, 3])], name, { type: 'image/png' })
}

describe('compressImageIfNeeded', () => {
  beforeEach(() => {
    readMock.mockReset()
  })

  it('passes a small image through unchanged', async () => {
    readMock.mockResolvedValue('data:image/png;base64,AAAA')
    const r = await compressImageIfNeeded(fakeFile(), 1000)
    expect(r.compressed).toBe(false)
    expect(r.fitsBudget).toBe(true)
    expect(r.uri).toBe('data:image/png;base64,AAAA')
  })

  it('falls back to the original when the image cannot be decoded (no canvas path)', async () => {
    // Za duży oryginał; stub Image odpala onerror (jsdom sam nie ładuje obrazów).
    const big = 'data:image/png;base64,' + 'A'.repeat(200)
    readMock.mockResolvedValue(big)
    class FailImage {
      onload: (() => void) | null = null
      onerror: (() => void) | null = null
      set src(_v: string) {
        setTimeout(() => this.onerror?.(), 0)
      }
    }
    const prev = window.Image
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(window as any).Image = FailImage
    try {
      const r = await compressImageIfNeeded(fakeFile(), 100)
      // Nie może się skompresować w tym środowisku, ale nie rzuca — oddaje oryginał.
      expect(r.uri).toBe(big)
      expect(r.fitsBudget).toBe(false)
    } finally {
      window.Image = prev
    }
  })
})
