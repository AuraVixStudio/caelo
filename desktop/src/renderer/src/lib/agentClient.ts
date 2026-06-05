// Klient WebSocket agenta kodowania (/agent/stream).
// Utrzymuje jedno połączenie na sesję modułu Code; emituje zdarzenia do handlerów.

import type { Conn } from './api'

/** Szczegóły żądania zatwierdzenia narzędzia (diff zapisu / komenda / plik binarny). */
export interface ApprovalDetail {
  kind?: string // 'diff' | 'command' | 'binary' | 'error'
  diff?: string
  command?: string
  cwd?: string
  created?: boolean // M13-B1: diff dla NOWEGO pliku (same dodania)
  bytes?: number // M13-B1: rozmiar dla kind === 'binary'
  detail?: string // komunikat dla 'binary'/'error'
}

/**
 * Ramki serwer→klient agenta (P2-7) — **discriminated union** po `type`, zgodny z
 * protokołem w `grok_core/routes/agent.py`. Zastępuje luźne `{type:string; [k]:unknown}`.
 */
export type AgentEvent =
  | { type: 'workspace'; path: string }
  | { type: 'text'; full: string }
  | { type: 'tool_call'; id: string; name: string; args: Record<string, unknown> }
  | { type: 'approval_request'; id: string; name: string; detail?: ApprovalDetail }
  | { type: 'checkpoint'; id: string; label: string; created_at: number }
  | { type: 'output'; id: string; chunk: string }
  | { type: 'tool_result'; id: string; ok: boolean; summary: string }
  | { type: 'assistant_done'; content: string }
  | { type: 'stopped' }
  | { type: 'done' }
  | { type: 'error'; error: string }

function asString(v: unknown, fallback = ''): string {
  return typeof v === 'string' ? v : fallback
}

function asRecord(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === 'object' && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {}
}

function parseDetail(v: unknown): ApprovalDetail | undefined {
  if (v === null || typeof v !== 'object') return undefined
  const d = v as Record<string, unknown>
  const out: ApprovalDetail = {}
  if (typeof d.kind === 'string') out.kind = d.kind
  if (typeof d.diff === 'string') out.diff = d.diff
  if (typeof d.command === 'string') out.command = d.command
  if (typeof d.cwd === 'string') out.cwd = d.cwd
  if (typeof d.created === 'boolean') out.created = d.created
  if (typeof d.bytes === 'number') out.bytes = d.bytes
  if (typeof d.detail === 'string') out.detail = d.detail
  return out
}

/**
 * Waliduje i zawęża surową ramkę na granicy WS (P2-7). Normalizuje typy pól, więc
 * konsument może im ufać; nieznany `type` lub niepoprawny kształt → `null` (ramka pomijana).
 */
export function parseAgentEvent(raw: unknown): AgentEvent | null {
  if (raw === null || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  switch (o.type) {
    case 'workspace':
      return { type: 'workspace', path: asString(o.path) }
    case 'text':
      return { type: 'text', full: asString(o.full) }
    case 'tool_call':
      return { type: 'tool_call', id: asString(o.id), name: asString(o.name), args: asRecord(o.args) }
    case 'approval_request':
      return {
        type: 'approval_request',
        id: asString(o.id),
        name: asString(o.name),
        detail: parseDetail(o.detail)
      }
    case 'checkpoint':
      return {
        type: 'checkpoint',
        id: asString(o.id),
        label: asString(o.label),
        created_at: typeof o.created_at === 'number' ? o.created_at : 0
      }
    case 'output':
      return { type: 'output', id: asString(o.id), chunk: asString(o.chunk) }
    case 'tool_result':
      return { type: 'tool_result', id: asString(o.id), ok: o.ok === true, summary: asString(o.summary) }
    case 'assistant_done':
      return { type: 'assistant_done', content: asString(o.content) }
    case 'stopped':
      return { type: 'stopped' }
    case 'done':
      return { type: 'done' }
    case 'error':
      return { type: 'error', error: asString(o.error, 'error') }
    default:
      return null
  }
}

export class AgentConnection {
  private ws: WebSocket | null = null
  private handlers: Array<(e: AgentEvent) => void> = []
  private closed = false // true po close() — wstrzymuje auto-reconnect
  private attempts = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  ready = false

  constructor(
    private conn: Conn,
    private onOpen?: () => void,
    private onClose?: () => void
  ) {
    this.connect()
  }

  // P1-5: pojedyncze połączenie z auto-reconnectem (backoff) po nieoczekiwanym
  // zamknięciu — po restarcie sidecara WS nie umiera już cicho.
  private connect(): void {
    const url =
      this.conn.baseUrl.replace(/^http/, 'ws') +
      '/agent/stream?token=' +
      encodeURIComponent(this.conn.token)
    const ws = new WebSocket(url)
    this.ws = ws
    ws.onopen = () => {
      this.ready = true
      this.attempts = 0
      this.onOpen?.()
    }
    ws.onmessage = (ev) => {
      let raw: unknown
      try {
        raw = JSON.parse(ev.data as string)
      } catch {
        return
      }
      const e = parseAgentEvent(raw) // P2-7: walidacja/zawężenie na granicy; nieznane → pomiń
      if (!e) return
      this.handlers.forEach((h) => h(e))
    }
    ws.onerror = () => {
      try {
        ws.close() // wymuś onclose (i sprzątanie) zamiast wisieć w błędzie
      } catch {
        /* ignore */
      }
    }
    ws.onclose = () => {
      this.ready = false
      this.onClose?.()
      if (!this.closed) this.scheduleReconnect()
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer || this.closed) return
    this.attempts += 1
    const delay = Math.min(this.attempts * 1000, 8000) // backoff z górnym limitem
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      if (!this.closed) this.connect()
    }, delay)
  }

  on(handler: (e: AgentEvent) => void): () => void {
    this.handlers.push(handler)
    return () => {
      this.handlers = this.handlers.filter((h) => h !== handler)
    }
  }

  private send(obj: Record<string, unknown>): void {
    try {
      this.ws?.send(JSON.stringify(obj))
    } catch {
      /* ignore */
    }
  }

  setWorkspace(path: string): void {
    this.send({ type: 'workspace', path })
  }

  sendMessage(text: string, model: string, images: string[] = [], mode = 'ask'): void {
    // M13: mode = ask | accept-edits | plan | bypass (jak „Mode" w Claude Code).
    this.send({ type: 'message', text, model, images, mode })
  }

  approve(id: string, decision: 'accept' | 'reject' | 'always'): void {
    this.send({ type: 'approval', id, decision })
  }

  stop(): void {
    this.send({ type: 'stop' })
  }

  close(): void {
    this.closed = true // zatrzymaj auto-reconnect
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    try {
      this.ws?.close()
    } catch {
      /* ignore */
    }
  }
}
