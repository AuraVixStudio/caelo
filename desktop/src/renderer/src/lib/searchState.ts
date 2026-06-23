// M10-F1/F2/F6: pure helpers for the live-search chat UI (search indicator,
// clickable sources, usage badge). Kept side-effect-free so they unit-test cleanly
// (Vitest) without a backend — the WS plumbing lives in api.ts/ChatView.

import type { Citation, ChatUsage, ToolEvent } from './api'

/** Human label for a live-search activity event (M10-F1). */
export function searchActivityLabel(ev: ToolEvent | null): string {
  if (!ev) return ''
  const where =
    ev.tool === 'x_search'
      ? 'X'
      : ev.tool === 'file_search'
        ? 'files'
        : ev.tool === 'web_search'
          ? 'the web'
          : 'sources'
  const verb = ev.status === 'completed' ? 'Searched' : 'Searching'
  const base = `${verb} ${where}`
  return ev.query ? `${base}: ${ev.query}` : `${base}…`
}

/** Dedupe citations by URL (first title wins) and drop anything not http(s). */
export function dedupeCitations(list: Citation[] | undefined): Citation[] {
  const out: Citation[] = []
  const seen = new Set<string>()
  for (const c of list ?? []) {
    const url = c?.url
    if (typeof url !== 'string' || !/^https?:\/\//i.test(url)) continue
    if (seen.has(url)) {
      // Backfill a title if the first occurrence had none.
      const prev = out.find((x) => x.url === url)
      if (prev && !prev.title && c.title) prev.title = c.title
      continue
    }
    seen.add(url)
    out.push({ url, title: c.title || '' })
  }
  return out
}

/** Short host label for a source chip, e.g. "https://x.com/a/b" -> "x.com". */
export function citationHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

/** Best display label for a source chip: a real page title when present, else the
 *  domain. The live Responses API often returns the inline reference number
 *  ("1", "2", …) as the citation title — useless as a label — so we fall back to the
 *  host in that case (the chip already shows its own ordinal). */
export function citationLabel(c: Citation): string {
  const title = (c.title || '').trim()
  if (title && !/^\d+$/.test(title)) return title
  return citationHost(c.url)
}

export function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1)}k`
  return String(n)
}

/** Format a USD cost, e.g. "$0.0234" (4dp under $1 — API costs are sub-dollar, 2dp above). */
export function formatCostUsd(usd: number): string {
  return `$${usd.toFixed(usd < 1 ? 4 : 2)}`
}

/** Compact usage summary, e.g. "2 searches · 1.2k tokens · $0.0234". Empty when nothing to show.
 *  cost_usd (4.1-g) is the REAL cost from xAI; shown only when present (no estimate in chat). */
export function formatUsage(usage: ChatUsage | undefined): string {
  if (!usage) return ''
  const parts: string[] = []
  const calls = usage.tool_calls ?? 0
  if (calls > 0) parts.push(`${calls} ${calls === 1 ? 'search' : 'searches'}`)
  const tokens = (usage.input_tokens ?? 0) + (usage.output_tokens ?? 0)
  if (tokens > 0) parts.push(`${formatTokens(tokens)} tokens`)
  const cost = usage.cost_usd
  if (typeof cost === 'number' && cost > 0) parts.push(formatCostUsd(cost))
  return parts.join(' · ')
}
