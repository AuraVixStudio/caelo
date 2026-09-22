export interface CoreRequestInput {
  path: string
  method?: string
  body?: string
  headers?: Record<string, string>
  timeoutMs?: number
}

export interface CoreRequestResult {
  ok: boolean
  status: number
  data?: unknown
  error?: string
}

const ALLOWED_METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
const MIN_TIMEOUT_MS = 1_000
const MAX_TIMEOUT_MS = 310_000

function safePath(path: unknown): path is string {
  return typeof path === 'string' && path.startsWith('/') && !path.startsWith('//') &&
    !path.includes('://') && !path.includes('\\')
}

function errorMessage(reason: unknown): string {
  const name = (reason as Error | undefined)?.name
  if (name === 'TimeoutError') return 'Request timed out'
  if (name === 'AbortError') return 'Request cancelled'
  return `Network error: ${String((reason as Error | undefined)?.message || reason)}`
}

/**
 * Performs an authenticated JSON request from Electron's main process. Keeping
 * REST traffic out of the Chromium renderer avoids a second networking stack,
 * while the sidecar URL and bearer token remain authoritative in main.
 */
export async function performCoreRequest(
  baseUrl: string,
  token: string,
  input: CoreRequestInput
): Promise<CoreRequestResult> {
  if (!safePath(input?.path)) return { ok: false, status: 0, error: 'Invalid core request path' }

  const method = String(input.method || 'GET').toUpperCase()
  if (!ALLOWED_METHODS.has(method)) {
    return { ok: false, status: 0, error: `Unsupported core request method: ${method}` }
  }
  if (input.body !== undefined && typeof input.body !== 'string') {
    return { ok: false, status: 0, error: 'Invalid core request body' }
  }

  const requestedTimeout = Number(input.timeoutMs ?? 30_000)
  const timeoutMs = Number.isFinite(requestedTimeout)
    ? Math.min(MAX_TIMEOUT_MS, Math.max(MIN_TIMEOUT_MS, requestedTimeout))
    : 30_000
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  for (const [name, value] of Object.entries(input.headers ?? {})) {
    if (name.toLowerCase() !== 'authorization') headers[name] = String(value)
  }
  headers.Authorization = `Bearer ${token}`

  try {
    const response = await fetch(new URL(input.path, baseUrl), {
      method,
      body: method === 'GET' ? undefined : input.body,
      headers,
      signal: AbortSignal.timeout(timeoutMs)
    })
    const text = await response.text()
    let data: unknown = null
    if (text) {
      try {
        data = JSON.parse(text)
      } catch {
        data = text
      }
    }
    return { ok: response.ok, status: response.status, data }
  } catch (reason) {
    return { ok: false, status: 0, error: errorMessage(reason) }
  }
}
