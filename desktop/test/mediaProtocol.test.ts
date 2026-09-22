import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { getArtifactMediaUrl, getArtifactThumbnailUrl } from '../src/renderer/src/lib/api'

describe('caelo-media protocol (Phase 3)', () => {
  it('builds a token-free artifact URL', () => {
    expect(getArtifactMediaUrl('abc_123')).toBe('caelo-media://artifact/abc_123')
    expect(getArtifactThumbnailUrl('abc_123')).toBe('caelo-media://thumbnail/abc_123')
  })

  it('forwards Range through a streaming net.fetch bridge', () => {
    const source = readFileSync(new URL('../src/main/mediaProtocol.ts', import.meta.url), 'utf8')
    expect(source).toContain("request.headers.get('range')")
    expect(source).toContain("headers.set('Range', range)")
    expect(source).toContain('net.fetch')
    expect(source).not.toContain('.blob()')
  })
})
