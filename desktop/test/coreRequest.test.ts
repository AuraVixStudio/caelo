import { afterEach, describe, expect, it } from 'vitest'
import { createServer, type Server } from 'node:http'
import { once } from 'node:events'
import { performCoreRequest } from '../src/main/coreRequest'

let server: Server | null = null

afterEach(async () => {
  if (!server) return
  server.close()
  await once(server, 'close')
  server = null
})

async function listen(handler: Parameters<typeof createServer>[0]): Promise<string> {
  server = createServer(handler)
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  const address = server.address()
  if (!address || typeof address === 'string') throw new Error('test server did not bind')
  return `http://127.0.0.1:${address.port}`
}

describe('performCoreRequest', () => {
  it('wykonuje uwierzytelnione żądanie JSON w procesie głównym', async () => {
    const baseUrl = await listen((request, response) => {
      expect(request.url).toBe('/artifacts?limit=1')
      expect(request.headers.authorization).toBe('Bearer authoritative-token')
      response.writeHead(200, { 'Content-Type': 'application/json' })
      response.end(JSON.stringify({ artifacts: [{ id: 'a1' }] }))
    })
    const result = await performCoreRequest(baseUrl, 'authoritative-token', {
      path: '/artifacts?limit=1', headers: { Authorization: 'Bearer renderer-token' }
    })
    expect(result).toEqual({ ok: true, status: 200, data: { artifacts: [{ id: 'a1' }] } })
  })

  it('przekazuje treść POST bez automatycznego ponawiania', async () => {
    let calls = 0
    const baseUrl = await listen((request, response) => {
      calls += 1
      let body = ''
      request.setEncoding('utf8')
      request.on('data', (chunk) => { body += chunk })
      request.on('end', () => {
        expect(body).toBe('{"prompt":"test"}')
        response.writeHead(200, { 'Content-Type': 'application/json' })
        response.end('{"job":{"id":"j1"}}')
      })
    })
    const result = await performCoreRequest(baseUrl, 'token', {
      path: '/genjobs/image', method: 'POST', body: '{"prompt":"test"}'
    })
    expect(result.ok).toBe(true)
    expect(calls).toBe(1)
  })

  it('blokuje URL spoza lokalnego silnika', async () => {
    const result = await performCoreRequest('http://127.0.0.1:1', 'token', {
      path: '//example.com/steal'
    })
    expect(result).toEqual({ ok: false, status: 0, error: 'Invalid core request path' })
  })
})
