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
  listArtifacts: vi.fn().mockResolvedValue({ artifacts: [] }),
  getProviders: vi.fn().mockResolvedValue({ default: 'xai', providers: [
    { id: 'xai', label: 'xAI', modalities: ['video'], auth_modes: ['api_key'], no_cost: false, status: 'stable' }
  ] }),
  getCapabilities: vi.fn().mockImplementation(() => Promise.resolve({ capabilities: models.value.video.map((id) => ({
    id, provider: 'xai', label: id, media_type: 'video', status: 'stable', tier: 'standard',
    is_default: id === models.value.default_video, notes: '', capabilities: {
      operations: id.includes('1.5') ? ['text2video', 'img2video', 'reference_to_video'] : ['text2video', 'img2video', 'edit', 'extend'],
      input_modalities: ['text', 'image', 'video'], output_modalities: ['video'],
      aspect_ratios: ['16:9'], resolutions: ['720p'], duration_min: 1, duration_max: 15,
      durations: [], supports_quality: false, quality_levels: [],
      max_reference_images: id.includes('1.5') ? 3 : 0, supports_streaming: false,
      supports_tools: false, thinking: false, thinking_levels: [], search_grounding: false,
      multi_turn: false, native_audio: false, supports_seed: false, first_last_frame: false,
      video_extension: !id.includes('1.5'), extension_seconds: null, extension_resolutions: [],
      edit_uploaded_video: false, supports_negative_prompt: false, notes: []
    }
  })) }))
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

let conn = { baseUrl: '', token: '' }

describe('Video — obrazy referencyjne (reference-to-video)', () => {
  beforeEach(() => {
    // A real backend restart produces a new Conn object; doing the same here
    // keeps the per-connection capabilities cache isolated between examples.
    conn = { baseUrl: '', token: '' }
    hub.videoRefs = []
    models.value = { video: ['grok-imagine-video-1.5', 'grok-imagine-video'],
                     default_video: 'grok-imagine-video-1.5' }
  })

  it('model 1.5 → taca referencji jest widoczna (0/3)', async () => {
    render(<Video conn={conn} />)
    expect(await screen.findByText(/Reference images · 0\/3/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Library' })).toBeInTheDocument()
    expect(screen.getByText('From disk')).toBeInTheDocument()
  })

  it('model bazowy bez wgranych referencji → taca ukryta', async () => {
    models.value = { video: ['grok-imagine-video'], default_video: 'grok-imagine-video' }
    render(<Video conn={conn} />)
    await screen.findByLabelText('Provider')
    expect(screen.queryByText(/Reference images/)).toBeNull()
  })

  it('referencje automatycznie wybierają model zdolny do reference-to-video', async () => {
    models.value = { video: ['grok-imagine-video', 'grok-imagine-video-1.5'], default_video: 'grok-imagine-video' }
    hub.videoRefs = [{ name: 'hero.png', uri: 'data:image/png;base64,AA' }]
    render(<Video conn={conn} />)
    expect(await screen.findByText(/Reference images · 1\/3/)).toBeInTheDocument()
    expect(await screen.findByDisplayValue('grok-imagine-video-1.5')).toBeInTheDocument()
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
