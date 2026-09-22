// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, listArtifacts, submitImageJob } from '../src/renderer/src/lib/api'

const coreRequest = vi.fn()

beforeEach(() => {
  coreRequest.mockReset()
  Object.defineProperty(window, 'caelo', {
    configurable: true,
    value: { coreRequest }
  })
})

describe('renderer API bridge', () => {
  it('ładuje galerię przez natywny most, a nie fetch renderera', async () => {
    coreRequest.mockResolvedValue({ ok: true, status: 200, data: {
      artifacts: [], count: 0, limit: 100, offset: 0
    } })
    const result = await listArtifacts({ baseUrl: 'http://unused', token: 'renderer-token' }, { limit: 100 })
    expect(result.artifacts).toEqual([])
    expect(coreRequest).toHaveBeenCalledWith(expect.objectContaining({
      path: '/artifacts?limit=100', method: 'GET'
    }))
  })

  it('wysyła generowanie dokładnie raz przez natywny most', async () => {
    coreRequest.mockResolvedValue({ ok: true, status: 200, data: { job: { id: 'j1' } } })
    await submitImageJob({ baseUrl: 'http://unused', token: 'renderer-token' }, {
      op: 'text2img', prompt: 'test', n: 1, aspect_ratio: '1:1', resolution: '1k'
    })
    expect(coreRequest).toHaveBeenCalledTimes(1)
    expect(coreRequest).toHaveBeenCalledWith(expect.objectContaining({
      path: '/genjobs/image', method: 'POST'
    }))
  })

  it('zachowuje komunikat błędu FastAPI', async () => {
    coreRequest.mockResolvedValue({ ok: false, status: 422, data: { detail: 'bad request' } })
    await expect(listArtifacts({ baseUrl: 'http://unused', token: 'x' }))
      .rejects.toEqual(expect.objectContaining<ApiError>({ status: 422, message: 'bad request' }))
  })
})
