import { afterEach, describe, expect, it, vi } from 'vitest'
import { uploadReferenceImage } from '../src/renderer/src/lib/api'

afterEach(() => vi.unstubAllGlobals())

describe('reference library upload', () => {
  it('wysyła surowe bajty obrazu zamiast dużego JSON/base64', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ artifact: { id: 'ref-1' } }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    }))
    vi.stubGlobal('fetch', fetchMock)

    await uploadReferenceImage(
      { baseUrl: 'http://127.0.0.1:1234', token: 'token' },
      'Zażółć hero.png',
      'data:image/png;base64,AQID'
    )

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/reference-library/file?name=')
    expect(decodeURIComponent(url)).toContain('Zażółć hero.png')
    expect(init.headers).toMatchObject({ 'Content-Type': 'image/png' })
    expect(Array.from(new Uint8Array(await (init.body as Blob).arrayBuffer()))).toEqual([1, 2, 3])
  })
})
