// Klient backendu grok-core: REST + WebSocket czatu.
// baseUrl i token pochodzą z handshake'u (window.grok.getCore()).

export interface Conn {
  baseUrl: string
  token: string
}

export interface ChatAttachment {
  id: string
  name: string
  kind: 'image' | 'text'
  uri?: string // image data-URI (kind === 'image')
  text?: string // file text (kind === 'text')
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  attachments?: ChatAttachment[]
}

/** Część treści multimodalnej dla /chat/completions (tekst lub obraz). */
export type ContentPart =
  | { type: 'text'; text: string }
  | { type: 'image_url'; image_url: { url: string } }

/** Wiadomość w formacie API (content może być stringiem lub listą part-ów). */
export interface ApiChatMessage {
  role: string
  content: string | ContentPart[]
}

export interface ModelsResp {
  chat: string[]
  image: string[]
  video: string[]
  voices: string[]
  default_chat: string
  default_image: string
  default_video: string
  default_voice: string
  realtime_model: string
  default_code: string
}

export interface SettingsResp {
  chat_model: string
  code_model: string
  system_prompt: string
  chat_temperature: number
  has_api_key: boolean
}

export interface AuthResp {
  authenticated: boolean
  oauth: boolean
  account: Record<string, unknown>
  has_api_key: boolean
}

export type SettingsPatch = Partial<{
  api_key: string
  chat_model: string
  code_model: string
  system_prompt: string
  chat_temperature: number
}>

/** Błąd HTTP z kodem statusu — pozwala wywołującym rozróżnić auth (401/403),
 *  timeout/anulowanie (status 0) od reszty (P2-11). */
export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export type ApiInit = RequestInit & { timeoutMs?: number }

const DEFAULT_TIMEOUT_MS = 30_000

/** Łączy sygnały (timeout + opcjonalny sygnał wywołującego) — pierwszy abort wygrywa. */
function combineSignals(signals: AbortSignal[]): AbortSignal {
  if (typeof AbortSignal.any === 'function') return AbortSignal.any(signals)
  const ctrl = new AbortController()
  for (const s of signals) {
    if (s.aborted) {
      ctrl.abort(s.reason)
      break
    }
    s.addEventListener('abort', () => ctrl.abort(s.reason), { once: true })
  }
  return ctrl.signal
}

async function api<T>(conn: Conn, path: string, init?: ApiInit): Promise<T> {
  // P2-9: każde żądanie ma timeout (nie wisi w nieskończoność), a wywołujący może
  // dołożyć własny AbortSignal (przycisk Cancel) — pierwszy abort wygrywa.
  const { timeoutMs, signal: userSignal, headers, ...rest } = init ?? {}
  const timeout = AbortSignal.timeout(timeoutMs ?? DEFAULT_TIMEOUT_MS)
  const signal = userSignal ? combineSignals([userSignal, timeout]) : timeout

  let res: Response
  try {
    res = await fetch(conn.baseUrl + path, {
      ...rest,
      signal,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${conn.token}`,
        ...(headers as Record<string, string> | undefined)
      }
    })
  } catch (e) {
    const name = (e as Error)?.name
    if (name === 'TimeoutError') throw new ApiError('Request timed out', 0)
    if (name === 'AbortError') throw new ApiError('Request cancelled', 0)
    throw new ApiError(`Network error: ${String((e as Error)?.message || e)}`, 0)
  }

  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body?.detail) detail = String(body.detail)
    } catch {
      /* ignore */
    }
    // P2-11: 401/403 to problem tokenu SESJI backendu (nie OAuth xAI) — podpowiedz restart.
    if (res.status === 401 || res.status === 403) {
      detail = `Authentication failed (${res.status}) — the backend session may need a restart.`
    }
    throw new ApiError(detail, res.status)
  }
  return (await res.json()) as T
}

export const getModels = (c: Conn): Promise<ModelsResp> => api<ModelsResp>(c, '/models')
export const getSettings = (c: Conn): Promise<SettingsResp> => api<SettingsResp>(c, '/settings')
export const getAuthStatus = (c: Conn): Promise<AuthResp> => api<AuthResp>(c, '/auth/status')
export const putSettings = (c: Conn, patch: SettingsPatch): Promise<{ ok: boolean }> =>
  api<{ ok: boolean }>(c, '/settings', { method: 'PUT', body: JSON.stringify(patch) })

// --- Auth (OAuth) ---
export const login = (c: Conn): Promise<{ ok: boolean; account: Record<string, unknown> }> =>
  // Backend czeka do 300 s na ukończenie logowania w przeglądarce — daj zapas.
  api(c, '/auth/login', { method: 'POST', timeoutMs: 310_000 })
export const logout = (c: Conn): Promise<{ ok: boolean }> =>
  api(c, '/auth/logout', { method: 'POST' })

// --- Media ---
export interface MediaResult {
  url: string
  path: string | null
}

export interface GenerateImageBody {
  prompt: string
  n: number
  aspect_ratio: string
  resolution: string
  model?: string
}

export interface EditImageBody {
  prompt: string
  images: string[] // data-URI
  n: number
  aspect_ratio: string
  resolution: string
  model?: string
}

export interface VideoJobBody {
  prompt: string
  duration: number
  resolution: string
  aspect_ratio: string
  model?: string
  image?: string // data-URI: first frame for image-to-video
}

export interface VideoEditBody {
  prompt: string
  video: string // https URL or data-URI of the source video
  model?: string
}

export interface VideoExtendBody {
  prompt: string
  video: string // https URL or data-URI of the source video
  duration?: number // added seconds (1-10)
  model?: string
}

export interface VideoStatus {
  status?: string
  video?: { url?: string }
  local_path?: string
  [k: string]: unknown
}

// Generowanie obrazu bywa wolne (zwłaszcza model „quality") — hojny limit.
export const generateImage = (c: Conn, body: GenerateImageBody): Promise<{ results: MediaResult[] }> =>
  api(c, '/images/generate', { method: 'POST', body: JSON.stringify(body), timeoutMs: 180_000 })

export const editImage = (c: Conn, body: EditImageBody): Promise<{ results: MediaResult[] }> =>
  api(c, '/images/edit', { method: 'POST', body: JSON.stringify(body), timeoutMs: 180_000 })

// Zadania wideo zwracają request_id (potem polling) — zwykle szybko, ale z zapasem.
export const createVideoJob = (c: Conn, body: VideoJobBody): Promise<{ request_id: string }> =>
  api(c, '/video/jobs', { method: 'POST', body: JSON.stringify(body), timeoutMs: 60_000 })

export const editVideoJob = (c: Conn, body: VideoEditBody): Promise<{ request_id: string }> =>
  api(c, '/video/edits', { method: 'POST', body: JSON.stringify(body), timeoutMs: 60_000 })

export const extendVideoJob = (c: Conn, body: VideoExtendBody): Promise<{ request_id: string }> =>
  api(c, '/video/extensions', { method: 'POST', body: JSON.stringify(body), timeoutMs: 60_000 })

export const pollVideoJob = (c: Conn, id: string): Promise<VideoStatus> =>
  api<VideoStatus>(c, `/video/jobs/${encodeURIComponent(id)}`)

// --- Voice (TTS / STT / realtime) ---
export interface TTSBody {
  text: string
  voice_id: string
  language?: string
}

export interface TTSResp {
  audio_b64: string
  mime: string
  path: string | null
}

export interface STTBody {
  audio_b64: string // base64 of the recording (no data: prefix)
  filename?: string
  language?: string
}

export interface STTResp {
  text?: string
  language?: string
  duration?: number
  words?: { text: string; start: number; end: number }[]
  [k: string]: unknown
}

export const textToSpeech = (c: Conn, body: TTSBody): Promise<TTSResp> =>
  api<TTSResp>(c, '/voice/tts', { method: 'POST', body: JSON.stringify(body), timeoutMs: 120_000 })

export const speechToText = (c: Conn, body: STTBody): Promise<STTResp> =>
  api<STTResp>(c, '/voice/stt', { method: 'POST', body: JSON.stringify(body), timeoutMs: 120_000 })

/** WebSocket URL for the realtime voice proxy (token + optional model in query). */
export function voiceRealtimeUrl(c: Conn, model?: string): string {
  const base =
    c.baseUrl.replace(/^http/, 'ws') + '/voice/realtime?token=' + encodeURIComponent(c.token)
  return model ? base + '&model=' + encodeURIComponent(model) : base
}

// --- History / config ---
export interface HistoryEntry {
  timestamp: string
  mode: string
  prompt: string
  url: string
}

// Legacy media-generations history. M9-B3 moved it from '/history' to
// '/history/generations' (the hub history backbone now owns '/history'). The
// History tab keeps this until it is rebuilt to consume hub events (M9-F3).
export const getHistory = (c: Conn): Promise<{ entries: HistoryEntry[] }> =>
  api(c, '/history/generations')

export const getOutputDir = (c: Conn): Promise<{ path: string }> =>
  api(c, '/config/output-dir')

export const setOutputDir = (c: Conn, path: string): Promise<{ ok: boolean; path: string }> =>
  api(c, '/config/output-dir', { method: 'PUT', body: JSON.stringify({ path }) })

// --- Workspace / files / git (mini-IDE) ---
export interface TreeEntry {
  name: string
  type: 'dir' | 'file'
  path: string
}

export interface GitStatus {
  is_repo: boolean
  branch?: string
  files?: { status: string; path: string }[]
  detail?: string
}

export const fsGetWorkspace = (c: Conn): Promise<{ path: string | null }> =>
  api(c, '/fs/workspace')

export const fsRecent = (c: Conn): Promise<{ recent: string[] }> => api(c, '/fs/recent')

export const fsSetWorkspace = (c: Conn, path: string): Promise<{ path: string }> =>
  api(c, '/fs/workspace', { method: 'POST', body: JSON.stringify({ path }) })

export const fsTree = (c: Conn, path = '.'): Promise<{ path: string; entries: TreeEntry[] }> =>
  api(c, `/fs/tree?path=${encodeURIComponent(path)}`)

export const fsRead = (c: Conn, path: string): Promise<{ path: string; content: string }> =>
  api(c, `/fs/read?path=${encodeURIComponent(path)}`)

export const fsWrite = (c: Conn, path: string, content: string): Promise<{ ok: boolean; path: string }> =>
  api(c, '/fs/write', { method: 'POST', body: JSON.stringify({ path, content }) })

export const gitStatus = (c: Conn): Promise<GitStatus> => api(c, '/git/status')

export const gitDiff = (c: Conn, path = ''): Promise<{ diff?: string; is_repo?: boolean; detail?: string }> =>
  api(c, `/git/diff?path=${encodeURIComponent(path)}`)

export const gitStage = (c: Conn, paths?: string[]): Promise<{ ok: boolean }> =>
  api(c, '/git/add', { method: 'POST', body: JSON.stringify({ paths: paths ?? null }) })

export const gitCommit = (
  c: Conn,
  message: string,
  stageAll = false
): Promise<{ ok: boolean; output: string }> =>
  api(c, '/git/commit', { method: 'POST', body: JSON.stringify({ message, stage_all: stageAll }) })

// --- Agent permissions (session allowlist) ---
export const getPermissions = (c: Conn): Promise<{ rules: string[] }> => api(c, '/permissions')

export const clearPermissions = (c: Conn): Promise<{ ok: boolean; rules: string[] }> =>
  api(c, '/permissions', { method: 'DELETE' })

export interface ChatStreamHandle {
  stop: () => void
}

export interface ChatStreamPayload {
  messages: ApiChatMessage[]
  model: string
  temperature: number
  system_prompt?: string
}

export interface ChatStreamHandlers {
  onDelta: (full: string) => void
  onDone: (full: string) => void
  onError: (err: string) => void
}

/** Otwiera WS /chat/stream, wysyła jedną turę i strumieniuje odpowiedź. */
export function streamChat(
  conn: Conn,
  payload: ChatStreamPayload,
  handlers: ChatStreamHandlers
): ChatStreamHandle {
  const wsUrl =
    conn.baseUrl.replace(/^http/, 'ws') + '/chat/stream?token=' + encodeURIComponent(conn.token)
  let finished = false
  let acc = '' // backend streamuje przyrostowo (P1-3); sklejamy, by onDelta dostawał pełny tekst
  const ws = new WebSocket(wsUrl)

  ws.onopen = () => ws.send(JSON.stringify({ type: 'chat', ...payload }))
  ws.onmessage = (ev) => {
    let m: { type?: string; delta?: string; full?: string; error?: string }
    try {
      m = JSON.parse(ev.data as string)
    } catch {
      return
    }
    if (m.type === 'delta') {
      acc += m.delta ?? ''
      handlers.onDelta(acc)
    } else if (m.type === 'done') {
      finished = true
      handlers.onDone(m.full ?? acc)
      ws.close()
    } else if (m.type === 'error') {
      finished = true
      handlers.onError(m.error ?? 'Unknown error')
      ws.close()
    }
  }
  ws.onerror = () => {
    if (!finished) {
      finished = true
      handlers.onError('WebSocket connection error')
    }
    try {
      ws.close() // P1-5: nie zostawiaj socketu w stanie błędu (leak)
    } catch {
      /* ignore */
    }
  }
  // P1-5: zamknięcie przed 'done' (np. restart sidecara w trakcie) — zgłoś błąd, nie wisij cicho.
  ws.onclose = () => {
    if (!finished) {
      finished = true
      handlers.onError('Connection closed before completion')
    }
  }

  return {
    stop: () => {
      try {
        ws.send(JSON.stringify({ type: 'stop' }))
      } catch {
        /* ignore */
      }
    }
  }
}
