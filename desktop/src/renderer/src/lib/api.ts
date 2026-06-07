// Klient backendu caelo-core: REST + WebSocket czatu.
// baseUrl i token pochodzą z handshake'u (window.caelo.getCore()).

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
  artifacts?: ChatArtifact[] // M20: media generated in this turn (shown inline)
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

// M19-B9: poziom reasoning_effort dla modeli rozumujących ('' = Auto/dziedzicz).
export type ReasoningEffort = '' | 'low' | 'medium' | 'high'

export interface SettingsResp {
  chat_model: string
  code_model: string
  system_prompt: string
  chat_temperature: number
  chat_effort: ReasoningEffort // M19-B9: domyślny effort czatu
  code_effort: ReasoningEffort // M19-B9: domyślny effort agenta
  chat_search_mode: SearchMode
  chat_search_sources: string[]
  voice: string
  voice_language: string
  has_api_key: boolean
}

/** Preferowane źródło uwierzytelniania ("przełącznik trybów"). */
export type AuthSource = 'auto' | 'oauth' | 'api_key'
/** Faktycznie aktywne źródło klucza dla wywołań xAI. */
export type ActiveSource = 'oauth' | 'api_key' | 'env' | 'none'

export interface AuthResp {
  authenticated: boolean
  oauth: boolean
  account: Record<string, unknown>
  has_api_key: boolean
  // Pola dodane wraz z przełącznikiem źródła (opcjonalne — zgodność ze starszym backendem/mockami).
  has_stored_key?: boolean // klucz w ustawieniach (usuwalny z UI)
  has_env_key?: boolean // klucz z XAI_API_KEY (.env), nieusuwalny z UI
  auth_source?: AuthSource // preferencja
  active_source?: ActiveSource // faktyczne aktywne źródło
}

export type SettingsPatch = Partial<{
  api_key: string
  auth_source: AuthSource // preferowane źródło uwierzytelniania
  chat_model: string
  code_model: string
  system_prompt: string
  chat_temperature: number
  chat_effort: ReasoningEffort // M19-B9
  code_effort: ReasoningEffort // M19-B9
  chat_search_mode: SearchMode
  chat_search_sources: string[]
  voice: string
  voice_language: string
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
/** Usuwa zapisany klucz API (nie dotyka XAI_API_KEY z .env ani OAuth). */
export const clearApiKey = (c: Conn): Promise<{ ok: boolean }> =>
  api<{ ok: boolean }>(c, '/settings/api-key', { method: 'DELETE' })

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
  chars?: number // M12-B5: characters synthesized (exact)
  cost?: number // M12-B5: estimated TTS cost (BYO-key)
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
  cost?: number // M12-B5: estimated STT cost from duration (BYO-key)
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

/** WebSocket URL for the streaming STT bridge (M12-B1; token + optional language). */
export function voiceSttStreamUrl(c: Conn, language?: string): string {
  const base =
    c.baseUrl.replace(/^http/, 'ws') + '/voice/stt/stream?token=' + encodeURIComponent(c.token)
  return language ? base + '&language=' + encodeURIComponent(language) : base
}

/** WebSocket URL for the voice-conversation pipeline (M12-B3; token in query). */
export function voiceConverseUrl(c: Conn): string {
  return c.baseUrl.replace(/^http/, 'ws') + '/voice/converse?token=' + encodeURIComponent(c.token)
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
  kind?: string // M22: 'chat' (projekt czatu) | 'code' (workspace Code)
  instructions?: string // M22: system prompt per projekt czatu
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

/** M19-B10: fetch hub history as Markdown (the /history/export route returns
 *  text/markdown, not JSON — so this is a raw fetch with the bearer header). */
export async function exportHistoryMarkdown(c: Conn, query: HistoryQuery = {}): Promise<string> {
  const res = await fetch(
    c.baseUrl + '/history/export' +
      queryString(query as Record<string, string | number | undefined>),
    { headers: { Authorization: `Bearer ${c.token}` } }
  )
  if (!res.ok) throw new ApiError(`History export failed (${res.status})`, res.status)
  return res.text()
}

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

// M22: zarządzanie projektem czatu — rename / instrukcje (PATCH) + usunięcie (DELETE).
export const updateProject = (
  c: Conn,
  id: string,
  patch: { name?: string; instructions?: string }
): Promise<{ project: HubProject }> =>
  api(c, `/projects/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(patch) })

export const deleteProject = (
  c: Conn,
  id: string
): Promise<{ ok: boolean; current_project_id: string | null }> =>
  api(c, `/projects/${encodeURIComponent(id)}`, { method: 'DELETE' })

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

// Flat, recursive file list of the workspace (for @-file references in the agent
// composer). Skips ignored dirs/symlinks; capped server-side (truncated=true if cut).
export const fsFiles = (c: Conn): Promise<{ files: string[]; truncated: boolean }> =>
  api(c, '/fs/files')

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

// M19-B4: glob permission rules (ToolPrefix(glob), deny > allow). Global rules persist
// in caelo_settings.json; project rules live in <ws>/.caelo/permissions.json (read-only here).
export interface GlobRules {
  allow: string[]
  deny: string[]
}
export const getPermissionRules = (c: Conn): Promise<GlobRules> => api(c, '/permissions/rules')
export const setPermissionRules = (c: Conn, rules: GlobRules): Promise<GlobRules> =>
  api(c, '/permissions/rules', { method: 'PUT', body: JSON.stringify(rules) })

// M19-B3: LSP servers (language intelligence for the coding agent). Global config in
// caelo_settings DATA_DIR/lsp.json; project config in <ws>/.caelo/lsp.json (read-only here).
export interface LspServerInfo {
  name: string
  command: string
  args: string[]
  languages: string[]
  running: boolean
}
export interface LspServerBody {
  name: string
  command: string
  args?: string[]
  extensionToLanguage: Record<string, string>
  env?: Record<string, string>
}
export const listLspServers = (
  c: Conn
): Promise<{ servers: LspServerInfo[]; has_workspace: boolean }> => api(c, '/lsp')
export const addLspServer = (c: Conn, body: LspServerBody): Promise<{ ok: boolean }> =>
  api(c, '/lsp', { method: 'POST', body: JSON.stringify(body) })
export const removeLspServer = (c: Conn, name: string): Promise<{ ok: boolean }> =>
  api(c, `/lsp/${encodeURIComponent(name)}`, { method: 'DELETE' })
export const restartLspServer = (c: Conn, name: string): Promise<{ ok: boolean }> =>
  api(c, `/lsp/${encodeURIComponent(name)}/restart`, { method: 'POST' })

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

// --- Agent sessions (M21): persisted, resumable coding sessions, filtered per project ---
export interface AgentSessionMeta {
  id: string
  title: string
  project_id: string | null
  cwd: string
  model: string | null
  created_at: number // epoch seconds
  updated_at: number // epoch seconds
  message_count: number // user + assistant messages
}

/** A raw LLM message as stored in a saved session's history (role user/assistant/tool). */
export interface RawLlmMessage {
  role: string
  content?: unknown // string | content parts | null
  tool_calls?: Array<{ id?: string; function?: { name?: string; arguments?: string } }>
  tool_call_id?: string
}

export interface AgentSessionFull extends AgentSessionMeta {
  v?: number
  history: RawLlmMessage[]
}

/** List saved sessions, newest first. Pass a project id to filter to that project. */
export const listAgentSessions = (
  c: Conn,
  projectId?: string | null
): Promise<{ sessions: AgentSessionMeta[] }> =>
  api(c, '/agent/sessions' + (projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''))

export const getAgentSession = (c: Conn, id: string): Promise<AgentSessionFull> =>
  api(c, `/agent/sessions/${encodeURIComponent(id)}`)

export const deleteAgentSession = (c: Conn, id: string): Promise<{ ok: boolean }> =>
  api(c, `/agent/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' })

// --- Agent project rules (CAELO.md, M13-B4/F4) ---
export interface CaeloMdResp {
  content: string
  exists: boolean
  global_exists: boolean
  max_bytes: number
  name: string
}

export const getCaeloMd = (c: Conn): Promise<CaeloMdResp> => api(c, '/agent/caelo-md')

export const putCaeloMd = (c: Conn, content: string): Promise<{ ok: boolean; path: string }> =>
  api(c, '/agent/caelo-md', { method: 'PUT', body: JSON.stringify({ content }) })

// --- M14: Extensibility (MCP servers / hooks / skills / slash commands) ---------

export interface McpTool {
  name: string
  description: string
  readonly: boolean
}

export interface McpServerInfo {
  id: string
  name: string
  transport: 'stdio' | 'remote'
  enabled: boolean
  status?: string // stopped | starting | ready | error | remote
  error?: string
  command?: string[]
  cwd?: string | null
  env_keys?: string[]
  url?: string
  server_label?: string
  has_authorization?: boolean
  tools?: McpTool[]
  tool_count?: number
  resource_count?: number
  prompt_count?: number
  server_info?: Record<string, unknown>
}

export interface McpServerInput {
  id?: string
  name?: string
  transport: 'stdio' | 'remote'
  command?: string[]
  cwd?: string | null
  env?: Record<string, string>
  url?: string
  authorization?: string
  server_label?: string
  enabled?: boolean
}

export const listMcpServers = (c: Conn): Promise<{ servers: McpServerInfo[] }> => api(c, '/mcp')
export const addMcpServer = (c: Conn, body: McpServerInput): Promise<{ server: McpServerInfo }> =>
  api(c, '/mcp', { method: 'POST', body: JSON.stringify(body) })
export const removeMcpServer = (c: Conn, id: string): Promise<{ ok: boolean }> =>
  api(c, `/mcp/${encodeURIComponent(id)}`, { method: 'DELETE' })
export const setMcpEnabled = (c: Conn, id: string, enabled: boolean): Promise<{ server: McpServerInfo }> =>
  api(c, `/mcp/${encodeURIComponent(id)}/enabled`, { method: 'PUT', body: JSON.stringify({ enabled }) })
// Starting a stdio server runs an arbitrary command — gated by an explicit user click.
export const startMcpServer = (c: Conn, id: string): Promise<{ server: McpServerInfo }> =>
  api(c, `/mcp/${encodeURIComponent(id)}/start`, { method: 'POST', timeoutMs: 60_000 })
export const stopMcpServer = (c: Conn, id: string): Promise<{ server: McpServerInfo }> =>
  api(c, `/mcp/${encodeURIComponent(id)}/stop`, { method: 'POST' })

export interface HookInfo {
  id: string
  event: 'pre_tool' | 'post_tool' | 'pre_session'
  type: 'block_command' | 'block_path' | 'audit' | 'run_script'
  enabled: boolean
  description?: string
  pattern?: string
  command?: string[]
  match_tools?: string[]
}

export interface AuditEntry {
  ts: string
  action: string // tool | blocked | hook_script | session
  tool?: string
  ok?: boolean
  hook?: string
  detail?: string
  cmd?: string
  args?: Record<string, unknown>
  [k: string]: unknown
}

export const listHooks = (c: Conn): Promise<{ hooks: HookInfo[] }> => api(c, '/hooks')
export const addHook = (c: Conn, body: Partial<HookInfo>): Promise<{ hook: HookInfo }> =>
  api(c, '/hooks', { method: 'POST', body: JSON.stringify(body) })
export const setHookEnabled = (c: Conn, id: string, enabled: boolean): Promise<{ hook: HookInfo }> =>
  api(c, `/hooks/${encodeURIComponent(id)}/enabled`, { method: 'PUT', body: JSON.stringify({ enabled }) })
export const removeHook = (c: Conn, id: string): Promise<{ ok: boolean }> =>
  api(c, `/hooks/${encodeURIComponent(id)}`, { method: 'DELETE' })
export const getAuditLog = (c: Conn, limit = 200): Promise<{ entries: AuditEntry[] }> =>
  api(c, `/hooks/audit?limit=${limit}`)
export const clearAuditLog = (c: Conn): Promise<{ ok: boolean }> =>
  api(c, '/hooks/audit', { method: 'DELETE' })

export interface SkillInfo {
  id: string
  name: string
  description: string
  triggers: string[]
  builtin: boolean
  enabled: boolean
  has_resources: boolean
  bytes: number
  body?: string
  /** M19-B5 §1.3: discovery source — 'builtin' | 'user' | 'claude-global' | 'claude-project' | 'grok-project'. Only 'user' skills are editable/deletable. */
  source?: string
}

export const listSkills = (c: Conn): Promise<{ skills: SkillInfo[] }> => api(c, '/skills')
export const getSkill = (c: Conn, id: string): Promise<{ skill: SkillInfo }> =>
  api(c, `/skills/${encodeURIComponent(id)}`)
export const createSkill = (
  c: Conn,
  body: { id: string; template?: string; name?: string; description?: string }
): Promise<{ skill: SkillInfo }> => api(c, '/skills', { method: 'POST', body: JSON.stringify(body) })
export const setSkillEnabled = (c: Conn, id: string, enabled: boolean): Promise<{ skill: SkillInfo }> =>
  api(c, `/skills/${encodeURIComponent(id)}/enabled`, { method: 'PUT', body: JSON.stringify({ enabled }) })
export const deleteSkill = (c: Conn, id: string): Promise<{ ok: boolean }> =>
  api(c, `/skills/${encodeURIComponent(id)}`, { method: 'DELETE' })

export interface SlashCommand {
  name: string
  description: string
  template: string
  target: 'chat' | 'agent' | 'both'
  mode?: string
  action?: string
  builtin: boolean
}

export const listCommands = (c: Conn): Promise<{ commands: SlashCommand[] }> => api(c, '/commands')
export const addCommand = (
  c: Conn,
  body: { name: string; template: string; description?: string; target?: string; mode?: string; action?: string }
): Promise<{ command: SlashCommand }> => api(c, '/commands', { method: 'POST', body: JSON.stringify(body) })
export const removeCommand = (c: Conn, name: string): Promise<{ ok: boolean }> =>
  api(c, `/commands/${encodeURIComponent(name)}`, { method: 'DELETE' })

// --- M16: Community packages / marketplace ----------------------------------------

export type PackageType = 'skill' | 'command' | 'mcp' | 'template'

export interface PackagePermissions {
  tools: string[]
  starts_process: boolean
  writes_files: boolean
  network: boolean
}

export interface PackageManifest {
  schema: number
  id: string
  name: string
  version: string
  type: PackageType
  author: string
  description: string
  requires: { app: string; model?: string }
  permissions: PackagePermissions
  source: string
  integrity: string
}

/** Report from /packages/inspect — the consent card (M16-2). No install happens. */
export interface PackageReport {
  manifest: PackageManifest
  integrity_ok: boolean
  compatible: boolean
  risk: 'low' | 'medium' | 'high'
  warnings: string[]
  payload_names: string[]
  already_installed: boolean
  source_url?: string
}

export interface InstalledPackage {
  id: string
  type: PackageType
  name: string
  version: string
  author: string
  source: string
  requires: { app: string; model?: string }
  permissions: PackagePermissions
  integrity: string
  installed_at: string
}

export interface RegistryEntry {
  id: string
  type: PackageType
  name: string
  version: string
  author: string
  description: string
  url: string
  source: string
  requires: Record<string, unknown>
  installed: boolean
  installed_version: string | null
  has_update: boolean
  compatible: boolean
}

export interface PackageUpdate {
  id: string
  type: PackageType
  name: string
  installed_version: string
  latest_version: string | null
  has_update: boolean
  compatible: boolean
  url: string | null
}

export interface TemplateInfo {
  id: string
  name: string
  description: string
  version: string
  builtin: boolean
  file_count: number
}

export const listPackages = (c: Conn): Promise<{ packages: InstalledPackage[] }> =>
  api(c, '/packages')
export const inspectPackage = (
  c: Conn,
  body: { data_b64?: string; url?: string }
): Promise<{ report: PackageReport }> =>
  api(c, '/packages/inspect', { method: 'POST', body: JSON.stringify(body) })
export const installPackage = (
  c: Conn,
  body: { data_b64?: string; url?: string; consent: boolean }
): Promise<{ installed: InstalledPackage }> =>
  api(c, '/packages/install', { method: 'POST', body: JSON.stringify(body), timeoutMs: 60_000 })
export const uninstallPackage = (c: Conn, id: string, type?: PackageType): Promise<{ ok: boolean }> =>
  api(c, `/packages/${encodeURIComponent(id)}${type ? `?type=${type}` : ''}`, { method: 'DELETE' })
export const exportPackage = (
  c: Conn,
  body: { type: PackageType; ref: string }
): Promise<{ filename: string; data_b64: string; bytes: number }> =>
  api(c, '/packages/export', { method: 'POST', body: JSON.stringify(body) })
export const getRegistry = (c: Conn, url?: string): Promise<{ packages: RegistryEntry[] }> =>
  api(c, `/packages/registry${url ? `?url=${encodeURIComponent(url)}` : ''}`, { timeoutMs: 60_000 })
export const getPackageUpdates = (c: Conn, url?: string): Promise<{ updates: PackageUpdate[] }> =>
  api(c, `/packages/updates${url ? `?url=${encodeURIComponent(url)}` : ''}`, { timeoutMs: 60_000 })
export const listTemplates = (c: Conn): Promise<{ templates: TemplateInfo[] }> =>
  api(c, '/packages/templates')
export const newProjectFromTemplate = (
  c: Conn,
  tid: string,
  body: { dest: string; name?: string }
): Promise<{ template: { id: string; name: string; dest: string; created: string[]; skipped: string[] }; project: { id: string; name: string } | null }> =>
  api(c, `/packages/templates/${encodeURIComponent(tid)}/new-project`, {
    method: 'POST',
    body: JSON.stringify(body)
  })

// --- M17: Subagent teams (roles / limits / worktree merges / runs) ---------------
/** M19-B11: one declared input/output field of a subagent role (persona I/O contract). */
export interface TeamRoleIO {
  name: string
  io_type: 'text' | 'file'
  required: boolean
  description: string
}

export interface TeamRole {
  id: string
  label: string
  description: string
  tools: string[] // file tools allowed for this role
  mcp: 'none' | 'readonly' | 'all'
  worktree: boolean // mutating role → works in an isolated copy, reviewed at merge
  model: string // '' = inherit orchestrator model
  reasoning_effort: ReasoningEffort // M19-B9: '' = inherit run effort
  instructions: string // M19-B11: persona (falls back to prompt when empty)
  inputs: TeamRoleIO[] // M19-B11: what the orchestrator may pass in
  outputs: TeamRoleIO[] // M19-B11: what the subagent should return
  prompt: string
  builtin: boolean
}

export interface TeamLimits {
  max_parallel: number
  max_depth: number
  timeout_s: number
  max_subagents: number
  max_total_turns: number
  max_iters: number
}

export interface MergeFile {
  path: string
  kind: 'created' | 'modified' | 'deleted'
}

export interface TeamMerge {
  id: string
  agent_id: string
  role: string
  task: string
  files: MergeFile[]
  conflicts: string[] // paths also changed by another pending merge
  created_at: number
  file_count: number
}

export interface SubagentReport {
  agent_id: string
  role: string
  task: string
  status: string // queued | running | done | failed | cancelled | timeout
  summary: string
  error: string
  turns: number
  tool_calls: number
  input_tokens: number
  output_tokens: number
  est_usd: number
  duration: number
  merge_id: string | null
  files_changed: number
}

export interface TeamTotals {
  subagents: number
  turns: number
  tool_calls: number
  input_tokens: number
  output_tokens: number
  merges: number
  est_usd: number
}

export interface TeamReport {
  run: number
  subagents: SubagentReport[]
  totals: TeamTotals
  errors: string[]
  created_at: number
}

export const listTeamRoles = (c: Conn): Promise<{ roles: TeamRole[]; limits: TeamLimits }> =>
  api(c, '/agent/team/roles')
export const upsertTeamRole = (c: Conn, body: Partial<TeamRole> & { id: string }): Promise<{ role: TeamRole }> =>
  api(c, '/agent/team/roles', { method: 'POST', body: JSON.stringify(body) })
export const removeTeamRole = (c: Conn, id: string): Promise<{ ok: boolean; roles: TeamRole[] }> =>
  api(c, `/agent/team/roles/${encodeURIComponent(id)}`, { method: 'DELETE' })
export const setTeamLimits = (c: Conn, body: Partial<TeamLimits>): Promise<{ limits: TeamLimits }> =>
  api(c, '/agent/team/limits', { method: 'PUT', body: JSON.stringify(body) })

export const listTeamMerges = (c: Conn): Promise<{ merges: TeamMerge[]; has_workspace: boolean }> =>
  api(c, '/agent/team/merges')
export const teamMergeDiff = (c: Conn, id: string): Promise<{ diff: string }> =>
  api(c, `/agent/team/merges/${encodeURIComponent(id)}/diff`)
export const applyTeamMerge = (
  c: Conn,
  id: string
): Promise<{ ok: boolean; applied: string[]; deleted: string[]; skipped: string[] }> =>
  api(c, `/agent/team/merges/${encodeURIComponent(id)}/apply`, { method: 'POST' })
export const rejectTeamMerge = (c: Conn, id: string): Promise<{ ok: boolean }> =>
  api(c, `/agent/team/merges/${encodeURIComponent(id)}/reject`, { method: 'POST' })
export const clearTeamMerges = (c: Conn): Promise<{ ok: boolean; cleared: number }> =>
  api(c, '/agent/team/merges', { method: 'DELETE' })
export const listTeamRuns = (c: Conn): Promise<{ runs: TeamReport[] }> => api(c, '/agent/team/runs')

export interface ChatStreamHandle {
  stop: () => void
}

export interface ChatStreamPayload {
  messages: ApiChatMessage[]
  model: string
  temperature: number
  system_prompt?: string
  reasoning_effort?: ReasoningEffort // M19-B9: low|medium|high (omit/'' = inherit chat_effort)
  search_mode?: SearchMode // M10-B2: live-search mode (default off, server-side)
  sources?: string[] // M10-B2: web/x/news (only meaningful when searching)
}

/** A live-search activity event from the server tool loop (M10-F1). */
export interface ToolEvent {
  tool: string // 'web_search' | 'x_search' | 'file_search'
  status: string // 'in_progress' | 'searching' | 'completed' | ...
  query?: string | null
}

/** An artifact generated during the chat (M20) — e.g. an image to render inline. */
export interface ChatArtifact {
  id: string
  kind: string // 'image' | 'video'
  mime?: string
}

export interface ChatStreamHandlers {
  onDelta: (full: string) => void
  onDone: (full: string) => void
  onError: (err: string) => void
  onTool?: (ev: ToolEvent) => void // M10-F1: search activity indicator
  onCitations?: (citations: Citation[]) => void // M10-F2: clickable sources
  onUsage?: (usage: ChatUsage) => void // M10-F6: cost/usage badge
  onArtifact?: (a: ChatArtifact) => void // M20: media generated in chat (render inline)
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
      artifact?: ChatArtifact
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
    } else if (m.type === 'artifact') {
      if (m.artifact) handlers.onArtifact?.(m.artifact)
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
