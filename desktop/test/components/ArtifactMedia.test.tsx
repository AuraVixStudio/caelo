// @vitest-environment jsdom
// Regresja miniatur: podgląd musi żądać bajtów OD RAZU po zamontowaniu karty
// (bez `loading="lazy"`, które dla świeżo dołożonej karty potrafiło nigdy nie
// wystartować) i ponawiać próbę po błędzie protokołu `caelo-media://`
// (503, gdy sidecar akurat się restartuje) — inaczej kafelek zostawał pusty
// aż do restartu aplikacji.
import '@testing-library/jest-dom/vitest'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, act } from '@testing-library/react'

import { ArtifactMedia } from '../../src/renderer/src/components/ArtifactMedia'
import type { Conn, HubArtifact } from '../../src/renderer/src/lib/api'

const conn = { port: 1, token: 't' } as unknown as Conn
const image = { id: 'abc123', type: 'image', mime: 'image/png' } as unknown as HubArtifact
const video = { id: 'vid456', type: 'video', mime: 'video/mp4' } as unknown as HubArtifact

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('ArtifactMedia', () => {
  it('ładuje miniaturę zachłannie (bez lazy) spod caelo-media://', () => {
    const { container } = render(<ArtifactMedia conn={conn} art={image} />)
    const img = container.querySelector('img')!
    expect(img.getAttribute('src')).toBe('caelo-media://thumbnail/abc123')
    expect(img.getAttribute('loading')).toBeNull()
  })

  it('ponawia po błędzie, omijając cache przez parametr retry', () => {
    const { container } = render(<ArtifactMedia conn={conn} art={image} />)
    act(() => {
      container.querySelector('img')!.dispatchEvent(new Event('error'))
      vi.advanceTimersByTime(1000)
    })
    expect(container.querySelector('img')!.getAttribute('src')).toBe(
      'caelo-media://thumbnail/abc123?retry=1'
    )
  })

  it('przestaje ponawiać po limicie prób', () => {
    const { container } = render(<ArtifactMedia conn={conn} art={image} />)
    for (let i = 0; i < 5; i += 1) {
      act(() => {
        container.querySelector('img')!.dispatchEvent(new Event('error'))
        vi.advanceTimersByTime(5000)
      })
    }
    expect(container.querySelector('img')!.getAttribute('src')).toBe(
      'caelo-media://thumbnail/abc123?retry=2'
    )
  })

  it('wideo pobiera klatkę podglądu przez fragment #t', () => {
    const { container } = render(<ArtifactMedia conn={conn} art={video} />)
    expect(container.querySelector('video')!.getAttribute('src')).toBe(
      'caelo-media://artifact/vid456#t=0.1'
    )
  })
})
