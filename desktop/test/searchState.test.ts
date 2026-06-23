// M10-F1/F2/F6: tests for the pure live-search UI helpers (indicator label,
// citation dedup, usage formatting).
import { describe, it, expect } from 'vitest'
import {
  searchActivityLabel,
  dedupeCitations,
  citationHost,
  citationLabel,
  formatUsage,
  formatCostUsd
} from '../src/renderer/src/lib/searchState'

describe('searchActivityLabel', () => {
  it('maps tools to human labels (F1)', () => {
    expect(searchActivityLabel({ tool: 'web_search', status: 'searching' })).toBe(
      'Searching the web…'
    )
    expect(searchActivityLabel({ tool: 'x_search', status: 'in_progress' })).toBe('Searching X…')
    expect(searchActivityLabel({ tool: 'file_search', status: 'searching' })).toBe(
      'Searching files…'
    )
  })

  it('uses past tense when completed and includes the query', () => {
    expect(searchActivityLabel({ tool: 'web_search', status: 'completed', query: 'grok news' })).toBe(
      'Searched the web: grok news'
    )
  })

  it('returns empty string for null', () => {
    expect(searchActivityLabel(null)).toBe('')
  })

  it('falls back to a generic label for unknown tools', () => {
    expect(searchActivityLabel({ tool: 'mystery', status: 'searching' })).toBe('Searching sources…')
  })
})

describe('dedupeCitations', () => {
  it('dedupes by url and keeps the first non-empty title (F2)', () => {
    const out = dedupeCitations([
      { url: 'https://a.com/1', title: '' },
      { url: 'https://a.com/1', title: 'First A' },
      { url: 'https://b.com/2', title: 'B' }
    ])
    expect(out).toEqual([
      { url: 'https://a.com/1', title: 'First A' },
      { url: 'https://b.com/2', title: 'B' }
    ])
  })

  it('drops non-http(s) and malformed entries', () => {
    const out = dedupeCitations([
      { url: 'javascript:alert(1)' },
      { url: 'ftp://x/y' },
      // @ts-expect-error intentional bad input
      { url: 123 },
      { url: 'https://ok.com' }
    ])
    expect(out).toEqual([{ url: 'https://ok.com', title: '' }])
  })

  it('handles undefined', () => {
    expect(dedupeCitations(undefined)).toEqual([])
  })
})

describe('citationHost', () => {
  it('strips scheme/path and www.', () => {
    expect(citationHost('https://www.example.com/a/b?c=1')).toBe('example.com')
    expect(citationHost('https://x.com/post/1')).toBe('x.com')
  })
  it('returns the input on parse failure', () => {
    expect(citationHost('not a url')).toBe('not a url')
  })
})

describe('citationLabel', () => {
  it('uses a real title when present', () => {
    expect(citationLabel({ url: 'https://x.ai/news', title: 'Grok 4 announcement' })).toBe(
      'Grok 4 announcement'
    )
  })
  it('falls back to the host when title is a bare reference number', () => {
    // The live Responses API returns titles like "1", "2" — show the domain instead.
    expect(citationLabel({ url: 'https://openrouter.ai/grok', title: '3' })).toBe('openrouter.ai')
  })
  it('falls back to the host when title is empty', () => {
    expect(citationLabel({ url: 'https://www.theverge.com/a/b' })).toBe('theverge.com')
  })
})

describe('formatUsage', () => {
  it('summarizes searches and tokens (F6)', () => {
    expect(formatUsage({ tool_calls: 2, input_tokens: 800, output_tokens: 400 })).toBe(
      '2 searches · 1.2k tokens'
    )
    expect(formatUsage({ tool_calls: 1, output_tokens: 50 })).toBe('1 search · 50 tokens')
  })
  it('omits zero parts and handles undefined', () => {
    expect(formatUsage({ tool_calls: 0, input_tokens: 0, output_tokens: 0 })).toBe('')
    expect(formatUsage(undefined)).toBe('')
  })
  it('appends real cost_usd when present (4.1-g)', () => {
    expect(formatUsage({ output_tokens: 50, cost_usd: 0.025 })).toBe('50 tokens · $0.0250')
    expect(formatUsage({ tool_calls: 1, output_tokens: 50, cost_usd: 1.5 })).toBe(
      '1 search · 50 tokens · $1.50'
    )
    // absent/zero cost → no cost segment (no estimate in chat)
    expect(formatUsage({ output_tokens: 50 })).toBe('50 tokens')
    expect(formatUsage({ output_tokens: 50, cost_usd: 0 })).toBe('50 tokens')
  })
})

describe('formatCostUsd', () => {
  it('uses 4dp under a cent, 2dp above (4.1-g)', () => {
    expect(formatCostUsd(0.0234)).toBe('$0.0234')
    expect(formatCostUsd(1.5)).toBe('$1.50')
  })
})
