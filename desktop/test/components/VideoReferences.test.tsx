// @vitest-environment jsdom
// Reference-to-video (docs x.ai 2026-08): taca obrazów referencyjnych pokazuje się
// TYLKO na modelu, który je przyjmuje (1.5). Wysłanie ich do bazowego modelu kończy
// się 400 na całym żądaniu, więc ukrycie kontrolki jest zabezpieczeniem, nie kosmetyką.
import '@testing-library/jest-dom/vitest'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'

const models = { value: { video: ['grok-imagine-video-1.5', 'grok-imagine-video'],
                          default_video: 'grok-imagine-video-1.5' } }

vi.mock('../../src/renderer/src/lib/serverState', () => ({
  useModels: () => ({ models: models.value, error: null })
}))
vi.mock('../../src/renderer/src/lib/useGenJobs', () => ({
  useGenJobs: () => ({
    jobs: [], submitVideo: vi.fn(), cancel: vi.fn(), retry: vi.fn(),
    clearFinished: vi.fn(), dismiss: vi.fn(), error: null
  })
}))
vi.mock('../../src/renderer/src/lib/api', async (orig) => ({
  ...(await orig<Record<string, unknown>>()),
  listArtifacts: vi.fn().mockResolvedValue({ artifacts: [] })
}))

// Hub trzyma staged media (panel jest leniwy) — tu wystarczy minimalna atrapa.
const hub = {
  currentProjectId: null,
  pendingSend: null,
  setPendingSend: vi.fn(),
  videoFrame: null,
  setVideoFrame: vi.fn(),
  videoRefs: [] as { name: string; uri: string }[],
  setVideoRefs: vi.fn(),
  videoSource: null,
  setVideoSource: vi.fn(),
  videoCommandMode: null,
  setVideoCommandMode: vi.fn(),
  promptReuse: null,
  setPromptReuse: vi.fn()
}
vi.mock('../../src/renderer/src/lib/hub', () => ({
  useHub: () => hub,
  HubProvider: ({ children }: { children: ReactNode }) => children
}))

import { Video } from '../../src/renderer/src/components/Video'

const conn = { baseUrl: '', token: '' } as never

describe('Video — obrazy referencyjne (reference-to-video)', () => {
  beforeEach(() => {
    hub.videoRefs = []
    models.value = { video: ['grok-imagine-video-1.5', 'grok-imagine-video'],
                     default_video: 'grok-imagine-video-1.5' }
  })

  it('model 1.5 → taca referencji jest widoczna (0/3)', async () => {
    render(<Video conn={conn} />)
    expect(await screen.findByText(/Reference images · 0\/3/)).toBeInTheDocument()
    expect(screen.getByText(/Add reference/)).toBeInTheDocument()
  })

  it('model bazowy bez wgranych referencji → taca ukryta', async () => {
    models.value = { video: ['grok-imagine-video'], default_video: 'grok-imagine-video' }
    render(<Video conn={conn} />)
    // Panel renderuje się (kadr startowy nadal jest), ale referencji nie ma.
    expect(await screen.findByText(/image-to-video/i)).toBeInTheDocument()
    expect(screen.queryByText(/Reference images/)).toBeNull()
  })

  it('model bazowy z wgranymi referencjami → taca widoczna z ostrzeżeniem (nie cicha strata)', async () => {
    models.value = { video: ['grok-imagine-video'], default_video: 'grok-imagine-video' }
    hub.videoRefs = [{ name: 'hero.png', uri: 'data:image/png;base64,AA' }]
    render(<Video conn={conn} />)
    expect(await screen.findByText(/Reference images · 1\/3/)).toBeInTheDocument()
    expect(screen.getByText(/will not be sent/i)).toBeInTheDocument()
  })

  it('dodane referencje są otagowane <IMAGE_n> zgodnie z promptem', async () => {
    hub.videoRefs = [
      { name: 'hero.png', uri: 'data:image/png;base64,AA' },
      { name: 'coat.png', uri: 'data:image/png;base64,BB' }
    ]
    render(<Video conn={conn} />)
    expect(await screen.findByText(/Reference images · 2\/3/)).toBeInTheDocument()
    expect(screen.getByText('<IMAGE_1>')).toBeInTheDocument()
    expect(screen.getByText('<IMAGE_2>')).toBeInTheDocument()
  })
})
