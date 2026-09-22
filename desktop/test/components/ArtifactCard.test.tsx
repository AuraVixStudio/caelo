// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// ArtifactMedia pobiera treść przez fetch (blob) — stubujemy, by test nie ruszał sieci.
// Zostawiamy prawdziwe `artifactPrompt`/typy z modułu.
vi.mock('../../src/renderer/src/lib/api', async (orig) => {
  const actual = await orig<typeof import('../../src/renderer/src/lib/api')>()
  return {
    ...actual,
    // Odrzuć → ArtifactMedia zostaje na placeholderze (jsdom nie ma URL.revokeObjectURL).
    getArtifactContentUrl: vi.fn(async () => {
      throw new Error('no content in test')
    }),
    deleteArtifact: vi.fn(async () => undefined)
  }
})

// Kopiowanie idzie przez odporny util (jsdom nie ma prawdziwego schowka).
vi.mock('../../src/renderer/src/lib/clipboard', () => ({
  copyText: vi.fn(async () => true)
}))

import { ArtifactCard } from '../../src/renderer/src/components/ArtifactCard'
import { HubProvider } from '../../src/renderer/src/lib/hub'
import { copyText } from '../../src/renderer/src/lib/clipboard'
import type { Conn, HubArtifact } from '../../src/renderer/src/lib/api'

const conn = { port: 1, token: 't' } as unknown as Conn

function artifact(over: Partial<HubArtifact> = {}): HubArtifact {
  return {
    id: 'a1',
    type: 'image',
    mode: 'image',
    mime: 'image/png',
    path: '/tmp/a1.png',
    thumb_path: '',
    meta: { prompt: 'A neon city at night' },
    project_id: null,
    created_at: 0,
    ...over
  }
}

function renderCard(art: HubArtifact, navigate = vi.fn()) {
  // conn=null → HubProvider pomija sieć (reloadProjects/reloadCommands); ArtifactCard
  // dostaje osobny fałszywy `conn` dla podglądu (stubowany wyżej).
  render(
    <HubProvider conn={null} navigate={navigate}>
      <ArtifactCard conn={conn} art={art} />
    </HubProvider>
  )
  return navigate
}

describe('ArtifactCard — reuse prompt', () => {
  it('używa małej miniatury dla obrazu zamiast pełnego pliku', () => {
    renderCard(artifact())
    expect(screen.getByRole('presentation')).toHaveAttribute('src', 'caelo-media://thumbnail/a1')
  })

  it('pokazuje zapisany prompt', () => {
    renderCard(artifact())
    expect(screen.getByText('A neon city at night')).toBeInTheDocument()
  })

  it('„Reuse prompt" na obrazie nawiguje do panelu Image', async () => {
    const navigate = renderCard(artifact())
    await userEvent.click(screen.getByRole('button', { name: /reuse prompt/i }))
    expect(navigate).toHaveBeenCalledWith('Image')
  })

  it('„Reuse prompt" na wideo nawiguje do panelu Video', async () => {
    const navigate = renderCard(artifact({ id: 'v1', type: 'video', mime: 'video/mp4' }))
    await userEvent.click(screen.getByRole('button', { name: /reuse prompt/i }))
    expect(navigate).toHaveBeenCalledWith('Video')
  })

  it('bez promptu nie renderuje paska (brak przycisku Reuse)', () => {
    renderCard(artifact({ meta: {} }))
    expect(screen.queryByRole('button', { name: /reuse prompt/i })).not.toBeInTheDocument()
  })

  it('„Copy" kopiuje prompt przez util schowka', async () => {
    renderCard(artifact())
    await userEvent.click(screen.getByRole('button', { name: /copy prompt/i }))
    expect(copyText).toHaveBeenCalledWith('A neon city at night')
  })

  it('długi prompt ma „Show more" i rozwija się w całości', async () => {
    const longPrompt =
      'A sweeping cinematic drone shot flying low over a rain-soaked neon megacity at night, ' +
      'reflections shimmering on the wet streets, volumetric fog, 8k, highly detailed'
    renderCard(artifact({ meta: { prompt: longPrompt } }))
    const toggle = screen.getByRole('button', { name: /show more/i })
    expect(toggle).toBeInTheDocument()
    await userEvent.click(toggle)
    expect(screen.getByRole('button', { name: /show less/i })).toBeInTheDocument()
  })

  it('krótki prompt nie ma przycisku „Show more"', () => {
    renderCard(artifact({ meta: { prompt: 'short prompt' } }))
    expect(screen.queryByRole('button', { name: /show more/i })).not.toBeInTheDocument()
  })
})
