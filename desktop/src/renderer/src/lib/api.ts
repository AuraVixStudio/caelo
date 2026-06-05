// Klient backendu grok-core: REST + WebSocket czatu.
// baseUrl i token pochodzą z handshake'u (window.grok.getCore()).

import { blobToDataUri } from './files'

export interface Conn {
  baseUrl: string
  token: string
}

export interface ChatAttachment {
  id: string
  name: string
  kind: 'image' | 'text' | 'document'
  uri?: string // data-URI (kind === 'image' or 'document')
  text?: string // file text (kind === 'text')
  mime?: string // document mime (kind === 'document')
}

/** A source returned by live search (M10-F2). Deduped by url. */
export interface Citation {
  url: string
  title?: string
}

/** Tool/token usage for a turn (M10-F6, BYO-key cost transparency). */
export interface ChatUsage {
  tool_calls?: number
  input_tokens?: number
  output_tokens?: number
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  attachments?: ChatAttachment[]
  citations?: Citation[] // live-search sources (assistant messages)
  usage?: ChatUsage // tool calls + tokens for this turn (assistant messages)
}

/** Live-search mode (M10-F3): Auto = model decides, On = forced, Off = no tools. */
export type SearchMode = 'auto' | 'on' | 'off'

/** Część treści multimodalnej (tekst / obraz / dokument). Obraz → vision (B3),
 *  dokument → Q&A nad dokumentem (B4); backend mapuje je na format Responses API. */
export type ContentPart =
  | { type: 'text'; text: string }
  | { type: 'image_url'; image_url: { url: string } }
  | { type: 'document'; document: { data: string; mime: string; name: string } }

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
  chat_search_mode: SearchMode
  chat_search_sources: string[]
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
  chat_search_mode: SearchMode
  chat_search_sources: string[]
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

// --- Generation jobs (M11): one async queue for image + video ---
export type GenJobKind = 'image' | 'video'
export type GenJobOp = 'text2img' | 'edit' | 'variation' | 'text2video' | 'img2video'
export type GenJobStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'

export interface GenJob {
  id: string
  kind: GenJobKind
  op: GenJobOp
  params: Record<string, unknown>
  status: GenJobStatus
  artifact_ids: string[]
  error: string
  cost: number
  project_id: string | null
  created_at: number
  updated_at: number
}

export interface ImageJobBody {
  op: 'text2img' | 'edit' | 'variation'
  prompt: string
  n: number
  aspect_ratio: string
  resolution: string
  model?: string
  images?: string[] // data-URI (edit/variation, up to 3)
}

export interface VideoGenJobBody {
  op: 'text2video' | 'img2video' | 'edit' | 'extend'
  prompt: string
  duration: number
  resolution: string
  aspect_ratio: string
  model?: string
  image?: string // data-URI: first frame for img2video
  video?: string // https URL or data:video — source for edit/extend
}

// Submit returns immediately with the queued job; the worker runs it server-side.
export const submitImageJob = (c: Conn, body: ImageJobBody): Promise<{ job: GenJob }> =>
  api(c, '/genjobs/image', { method: 'POST', body: JSON.stringify(body) })

export const submitVideoGenJob = (c: Conn, body: VideoGenJobBody): Promise<{ job: GenJob }> =>
  api(c, '/genjobs/video', { method: 'POST', body: JSON.stringify(body) })

export interface GenJobsQuery {
  active?: boolean
  project_id?: string
  limit?: number
  offset?: number
}

export const listGenJobs = (
  c: Conn,
  query: GenJobsQuery = {}
): Promise<{ jobs: GenJob[]; total_cost: number; count: number }> => {
  // active is a boolean → serialize explicitly (queryString takes string|number).
  const params: Record<string, string | number | undefined> = {
    project_id: query.project_id,
    limit: query.limit,
    offset: query.offset
  }
  if (query.active !== undefined) params.active = query.active ? 'true' : 'false'
  return api(c, '/genjobs' + queryString(params))
}

export const getGenJob = (c: Conn, id: string): Promise<{ job: GenJob }> =>
  api(c, `/genjobs/${encodeURIComponent(id)}`)

export const cancelGenJob = (c: Conn, id: string): Promise<{ job: GenJob }> =>
  api(c, `/genjobs/${encodeURIComponent(id)}/cancel`, { method: 'POST' })

export const retryGenJob = (c: Conn, id: string): Promise<{ job: GenJob }> =>
  api(c, `/genjobs/${encodeURIComponent(id)}/retry`, { method: 'POST' })

/** Clear finished jobs (done/failed/cancelled) from the list. Media artifacts are
 *  kept — only the job log rows are removed. Optionally scoped by kind. */
export const clearGenJobs = (c: Conn, kind?: GenJobKind): Promise<{ cleared: number }> =>
  api(c, '/genjobs' + queryString({ kind }), { method: 'DELETE' })

/** Remove one finished job from the list (artifact kept). Active jobs → 409. */
export const deleteGenJob = (c: Conn, id: string): Promise<{ ok: boolean }> =>
  api(c, `/genjobs/${encodeURIComponent(id)}`, { method: 'DELETE' })

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

// --- Hub backbone (M9): one searchable history, artifacts, projects ---
export interface HubEvent {
  id: string
  mode: string
  text: string
  artifact_id: string | null
  project_id: string | null
  created_at: number // epoch seconds
}

export interface HubArtifact {
  id: string
  type: string // image | video | audio | file | text | code
  mode: string
  mime: string
  path: string
  thumb_path: string
  meta: Record<string, unknown>
  project_id: string | null
  created_at: number
}

export interface HubProject {
  id: string
  name: string
  root: string
  created_at: number
}

/** Ready-to-use LLM input block produced by the send-to bus (M9-B4). */
export interface InputBlock {
  artifact_id: string
  type: string
  mode: string
  mime: string
  name: string
  block:
    | { type: 'image_url'; image_url: { url: string } }
    | { type: 'document'; document: { data: string; mime: string; name: string } }
    | { type: 'text'; text: string }
  data_uri?: string
  text?: string
}

export interface HistoryQuery {
  q?: string
  mode?: string
  project_id?: string
  from?: number
  to?: number
  limit?: number
  offset?: number
}

function queryString(params: Record<string, string | number | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
  return parts.length ? '?' + parts.join('&') : ''
}

export const listHistory = (
  c: Conn,
  query: HistoryQuery = {}
): Promise<{ events: HubEvent[]; count: number; limit: number; offset: number }> =>
  api(c, '/history' + queryString(query as Record<string, string | number | undefined>))

export const listArtifacts = (
  c: Conn,
  query: HistoryQuery = {}
): Promise<{ artifacts: HubArtifact[]; count: number; limit: number; offset: number }> =>
  api(c, '/artifacts' + queryString(query as Record<string, string | number | undefined>))

export const getArtifact = (c: Conn, id: string): Promise<HubArtifact> =>
  api(c, `/artifacts/${encodeURIComponent(id)}`)

/** Delete an artifact: its record + the file on disk (if under an allowed media dir).
 *  Used to clear accumulated media from Recent / Gallery. Irreversible. */
export const deleteArtifact = (c: Conn, id: string): Promise<{ ok: boolean; deleted_file: boolean }> =>
  api(c, `/artifacts/${encodeURIComponent(id)}`, { method: 'DELETE' })

export const getArtifactInputBlock = (c: Conn, id: string): Promise<InputBlock> =>
  api(c, `/artifacts/${encodeURIComponent(id)}/input-block`)

/** Fetch artifact bytes as an object URL. The /content endpoint needs a Bearer
 *  header, which an <img src> can't send — so we fetch the blob and wrap it.
 *  Caller must URL.revokeObjectURL(url) when the element unmounts. */
export async function getArtifactContentUrl(c: Conn, id: string): Promise<string> {
  const res = await fetch(c.baseUrl + `/artifacts/${encodeURIComponent(id)}/content`, {
    headers: { Authorization: `Bearer ${c.token}` },
    signal: AbortSignal.timeout(60_000)
  })
  if (!res.ok) throw new ApiError(`HTTP ${res.status}`, res.status)
  return URL.createObjectURL(await res.blob())
}

/** Fetch an artifact's bytes as a data-URI — e.g. to reuse a generated video as the
 *  source for edit/extend (which take a data:video/* or https URL, not a local path). */
export async function getArtifactDataUri(c: Conn, id: string): Promise<string> {
  const res = await fetch(c.baseUrl + `/artifacts/${encodeURIComponent(id)}/content`, {
    headers: { Authorization: `Bearer ${c.token}` },
    signal: AbortSignal.timeout(120_000)
  })
  if (!res.ok) throw new ApiError(`HTTP ${res.status}`, res.status)
  return blobToDataUri(await res.blob())
}

export interface ProjectsResp {
  projects: HubProject[]
  recent_workspaces: string[]
  current_project_id: string | null
}

export const listProjects = (c: Conn): Promise<ProjectsResp> => api<ProjectsResp>(c, '/projects')

export const createProject = (
  c: Conn,
  name: string,
  root?: string
): Promise<{ project: HubProject; current_project_id: string | null }> =>
  api(c, '/projects', { method: 'POST', body: JSON.stringify({ name, root }) })

export const selectProject = (
  c: Conn,
  projectId: string | null
): Promise<{ current_project_id: string | null; project: HubProject | null }> =>
  api(c, '/projects/current', { method: 'POST', body: JSON.stringify({ project_id: projectId }) })

// --- Project knowledge (M10-B5): documents stored locally per project, attached
// to a message on demand ("Attach all"). xAI has no server-side vector stores. ---
export interface CollectionFile {
  id: string
  project_id: string
  name: string
  path: string
  mime: string
  bytes: number
  created_at: number
}

export const listCollection = (
  c: Conn
): Promise<{ files: CollectionFile[]; project_id: string | null; has_collection: boolean }> =>
  api(c, '/collections')

/** Save a document (data-URI) to the active project's knowledge (stored locally). */
export const uploadCollectionFile = (
  c: Conn,
  name: string,
  data: string
): Promise<{ file: CollectionFile }> =>
  api(c, '/collections/files', {
    method: 'POST',
    body: JSON.stringify({ name, data }),
    timeoutMs: 180_000
  })

export const deleteCollectionFile = (c: Conn, id: string): Promise<{ ok: boolean }> =>
  api(c, `/collections/files/${encodeURIComponent(id)}`, { method: 'DELETE' })

/** Fetch a project document's bytes as a data-URI, to attach it to a message. */
export async function collectionFileDataUri(c: Conn, id: string): Promise<string> {
  const res = await fetch(c.baseUrl + `/collections/files/${encodeURIComponent(id)}/content`, {
    headers: { Authorization: `Bearer ${c.token}` },
    signal: AbortSignal.timeout(60_000)
  })
  if (!res.ok) throw new ApiError(`HTTP ${res.status}`, res.status)
  return blobToDataUri(await res.blob())
}

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

// --- Agent checkpoints / undo (M13-B5) ---
export interface CheckpointInfo {
  id: string
  label: string
  created_at: number // epoch seconds
  files: number // files snapshotted in this checkpoint
  has_command: boolean // ran a command → undo is partial
}

export interface CheckpointsResp {
  checkpoints: CheckpointInfo[]
  session_id: string | null
  partial: boolean
  has_workspace: boolean
}

export interface UndoResp {
  ok: boolean
  restored: string[]
  deleted: string[]
  missing: string[]
  partial: boolean
  checkpoints_undone: number
}

export const listCheckpoints = (c: Conn): Promise<CheckpointsResp> => api(c, '/agent/checkpoints')

/** Undo to a checkpoint (id), or the whole session when id is omitted. */
export const agentUndo = (c: Conn, checkpointId?: string | null): Promise<UndoResp> =>
  api(c, '/agent/undo', {
    method: 'POST',
    body: JSON.stringify({ checkpoint_id: checkpointId ?? null })
  })

// --- Agent project rules (GROK.md, M13-B4/F4) ---
export interface GrokMdResp {
  content: string
  exists: boolean
  global_exists: boolean
  max_bytes: number
  name: string
}

export const getGrokMd = (c: Conn): Promise<GrokMdResp> => api(c, '/agent/grok-md')

export const putGrokMd = (c: Conn, content: string): Promise<{ ok: boolean; path: string }> =>
  api(c, '/agent/grok-md', { method: 'PUT', body: JSON.stringify({ content }) })

export interface ChatStreamHandle {
  stop: () => void
}

export interface ChatStreamPayload {
  messages: ApiChatMessage[]
  model: string
  temperature: number
  system_prompt?: string
  search_mode?: SearchMode // M10-B2: live-search mode (default off, server-side)
  sources?: string[] // M10-B2: web/x/news (only meaningful when searching)
}

/** A live-search activity event from the server tool loop (M10-F1). */
export interface ToolEvent {
  tool: string // 'web_search' | 'x_search' | 'file_search'
  status: string // 'in_progress' | 'searching' | 'completed' | ...
  query?: string | null
}

export interface ChatStreamHandlers {
  onDelta: (full: string) => void
  onDone: (full: string) => void
  onError: (err: string) => void
  onTool?: (ev: ToolEvent) => void // M10-F1: search activity indicator
  onCitations?: (citations: Citation[]) => void // M10-F2: clickable sources
  onUsage?: (usage: ChatUsage) => void // M10-F6: cost/usage badge
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
    let m: {
      type?: string
      delta?: string
      full?: string
      error?: string
      tool?: string
      status?: string
      query?: string | null
      citations?: Citation[]
      usage?: ChatUsage
      tool_calls?: number
    }
    try {
      m = JSON.parse(ev.data as string)
    } catch {
      return
    }
    if (m.type === 'delta') {
      acc += m.delta ?? ''
      handlers.onDelta(acc)
    } else if (m.type === 'tool_call') {
      // M10-F1: server-side live-search activity (web_search/x_search).
      handlers.onTool?.({ tool: m.tool ?? '', status: m.status ?? '', query: m.query })
    } else if (m.type === 'citations') {
      handlers.onCitations?.(m.citations ?? [])
    } else if (m.type === 'usage') {
      handlers.onUsage?.({ ...(m.usage ?? {}), tool_calls: m.tool_calls ?? m.usage?.tool_calls })
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
