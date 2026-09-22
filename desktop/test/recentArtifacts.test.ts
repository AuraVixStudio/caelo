// Regresja: świeżo wygenerowany obraz/wideo musi trafić do „Recent" NATYCHMIAST.
// Wymuszone odświeżenie (`force`) nie może dołączać do żądania, które wystartowało
// zanim zadanie się skończyło — tak lista zostawała bez nowego artefaktu i była
// stemplowana jako świeża, więc miniatura pojawiała się dopiero po restarcie.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { Conn, HubArtifact } from '../src/renderer/src/lib/api'

const listArtifacts = vi.fn()
vi.mock('../src/renderer/src/lib/api', () => ({
  listArtifacts: (...args: unknown[]) => listArtifacts(...args)
}))

const { listRecentArtifacts } = await import('../src/renderer/src/lib/recentArtifacts')

const conn = { baseUrl: 'http://127.0.0.1:1', token: 't' } as unknown as Conn
const art = (id: string): HubArtifact => ({ id, type: 'image' }) as unknown as HubArtifact

function deferred(): { promise: Promise<unknown>; resolve: (v: unknown) => void } {
  let resolve!: (v: unknown) => void
  const promise = new Promise((r) => {
    resolve = r
  })
  return { promise, resolve }
}

beforeEach(() => {
  listArtifacts.mockReset()
})

describe('listRecentArtifacts', () => {
  it('force wysyła NOWE żądanie zamiast dołączać do trwającego', async () => {
    const first = deferred()
    const second = deferred()
    listArtifacts.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)

    const stale = listRecentArtifacts(conn, 'image')
    const fresh = listRecentArtifacts(conn, 'image', undefined, true)

    expect(listArtifacts).toHaveBeenCalledTimes(2)

    first.resolve({ artifacts: [art('old')] })
    second.resolve({ artifacts: [art('old'), art('new')] })
    expect((await stale).map((a) => a.id)).toEqual(['old'])
    expect((await fresh).map((a) => a.id)).toEqual(['old', 'new'])

    // Późniejszy wynik wygrywa — cache trzyma listę z nowym artefaktem.
    listArtifacts.mockReturnValueOnce(Promise.resolve({ artifacts: [] }))
    expect((await listRecentArtifacts(conn, 'image')).map((a) => a.id)).toEqual(['old', 'new'])
    expect(listArtifacts).toHaveBeenCalledTimes(2) // odpowiedź z cache, bez żądania
  })

  it('spóźniona odpowiedź nie nadpisuje nowszej', async () => {
    const slow = deferred()
    const quick = deferred()
    listArtifacts.mockReturnValueOnce(slow.promise).mockReturnValueOnce(quick.promise)

    const stale = listRecentArtifacts(conn, 'video')
    const fresh = listRecentArtifacts(conn, 'video', undefined, true)

    quick.resolve({ artifacts: [art('new')] })
    await fresh
    slow.resolve({ artifacts: [] })
    await stale

    listArtifacts.mockReturnValueOnce(Promise.resolve({ artifacts: [] }))
    expect((await listRecentArtifacts(conn, 'video')).map((a) => a.id)).toEqual(['new'])
  })

  it('bez force współdzieli trwające żądanie', async () => {
    const one = deferred()
    listArtifacts.mockReturnValueOnce(one.promise)
    const a = listRecentArtifacts(conn, 'image', 'p1')
    const b = listRecentArtifacts(conn, 'image', 'p1')
    expect(listArtifacts).toHaveBeenCalledTimes(1)
    one.resolve({ artifacts: [art('x')] })
    expect(await a).toEqual(await b)
  })
})
