// @vitest-environment jsdom
// Publiczny link (xAI Files API): nic nie wychodzi z maszyny przed kliknięciem w karcie
// zgody, a istniejący link da się skopiować i odwołać.
import '@testing-library/jest-dom/vitest'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { fireEvent } from '@testing-library/dom'

const create = vi.fn()
const revoke = vi.fn()
vi.mock('../../src/renderer/src/lib/api', async (orig) => ({
  ...(await orig<Record<string, unknown>>()),
  createArtifactPublicUrl: (...args: unknown[]) => create(...args),
  revokeArtifactPublicUrl: (...args: unknown[]) => revoke(...args)
}))

import { ShareLinkButton, canSharePublicly } from '../../src/renderer/src/components/ShareLinkButton'
import type { HubArtifact } from '../../src/renderer/src/lib/api'

const conn = { baseUrl: '', token: '' }
function art(meta: Record<string, unknown> = {}, mime = 'image/png'): HubArtifact {
  return { id: 'a1', type: 'image', mode: 'generate', mime, path: 'C:/media/a.png', thumb_path: '',
    meta, project_id: null, created_at: 0, favorite: false } as HubArtifact
}

describe('ShareLinkButton', () => {
  beforeEach(() => {
    create.mockReset().mockResolvedValue({ public_url: 'https://files-cdn.x.ai/t/a.png', expires_at: null, file_id: 'f' })
    revoke.mockReset().mockResolvedValue({ public_url: null, expires_at: null, file_id: 'f', revoked: true })
  })

  it('tylko typy obsługiwane przez Files API', () => {
    expect(canSharePublicly(art())).toBe(true)
    expect(canSharePublicly(art({}, 'audio/mpeg'))).toBe(false)
  })

  it('otwarcie pokazuje kartę zgody i niczego nie wysyła', async () => {
    render(<ShareLinkButton conn={conn} art={art()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Share link' }))
    expect(await screen.findByText('Create a public link?')).toBeInTheDocument()
    expect(create).not.toHaveBeenCalled()
  })

  it('zgoda tworzy link z wybranym wygaśnięciem', async () => {
    render(<ShareLinkButton conn={conn} art={art()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Share link' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Create public link' }))
    await waitFor(() => expect(create).toHaveBeenCalledWith(conn, 'a1', 86_400))
    expect(await screen.findByDisplayValue('https://files-cdn.x.ai/t/a.png')).toBeInTheDocument()
  })

  it('istniejący link można odwołać', async () => {
    render(<ShareLinkButton conn={conn} art={art({ public_url: 'https://files-cdn.x.ai/t/a.png' })} />)
    fireEvent.click(screen.getByRole('button', { name: 'Public link' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Revoke link' }))
    await waitFor(() => expect(revoke).toHaveBeenCalledWith(conn, 'a1'))
    expect(await screen.findByText('Create a public link?')).toBeInTheDocument()
  })
})
