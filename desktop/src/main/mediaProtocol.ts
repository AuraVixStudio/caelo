import { net, protocol } from 'electron'

export interface MediaConnection {
  status: string
  baseUrl?: string
  token?: string
}

protocol.registerSchemesAsPrivileged([
  { scheme: 'caelo-media', privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true } },
  { scheme: 'caelo-reference', privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true } }
])

/** Chroniony most strumieniowy do artefaktów. Przekazuje Range bez buforowania body. */
export function registerMediaProtocol(getConnection: () => MediaConnection): void {
  protocol.handle('caelo-media', async (request) => {
    try {
      const url = new URL(request.url)
      const artifactId = url.pathname.replace(/^\//, '')
      if (!['artifact', 'thumbnail'].includes(url.hostname) || !/^[A-Za-z0-9_-]{1,128}$/.test(artifactId))
        return new Response('Invalid media URL', { status: 400 })
      const connection = getConnection()
      if (connection.status !== 'ready' || !connection.baseUrl || !connection.token)
        return new Response('Caelo Core is not ready', { status: 503 })
      const headers = new Headers({ Authorization: `Bearer ${connection.token}` })
      const range = request.headers.get('range')
      if (range) headers.set('Range', range)
      const resource = url.hostname === 'thumbnail' ? 'thumbnail' : 'content'
      return net.fetch(`${connection.baseUrl}/artifacts/${encodeURIComponent(artifactId)}/${resource}`, {
        method: 'GET', headers
      })
    } catch {
      return new Response('Media unavailable', { status: 502 })
    }
  })
}
