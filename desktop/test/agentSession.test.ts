// M21: tests for the saved-session → transcript reconstruction + list filter (pure utils).
import { describe, it, expect } from 'vitest'
import {
  filterSessions,
  historyToEntries,
  sessionsForWorkspace
} from '../src/renderer/src/lib/agentSession'
import type { AgentSessionMeta, RawLlmMessage } from '../src/renderer/src/lib/api'

function meta(p: Partial<AgentSessionMeta>): AgentSessionMeta {
  return {
    id: 'x',
    title: '',
    project_id: null,
    cwd: '',
    model: null,
    created_at: 0,
    updated_at: 0,
    message_count: 0,
    ...p
  }
}

describe('historyToEntries', () => {
  it('maps user and assistant text messages to entries', () => {
    const e = historyToEntries([
      { role: 'user', content: 'add a test' },
      { role: 'assistant', content: 'Done.' }
    ])
    expect(e).toHaveLength(2)
    expect(e[0]).toMatchObject({ kind: 'user', text: 'add a test' })
    expect(e[1]).toMatchObject({ kind: 'assistant', text: 'Done.' })
  })

  it('renders assistant tool_calls as collapsed done tool entries with parsed args', () => {
    const history: RawLlmMessage[] = [
      { role: 'user', content: 'read it' },
      {
        role: 'assistant',
        content: '',
        tool_calls: [
          { id: 'c1', function: { name: 'read_file', arguments: '{"path":"a.txt"}' } }
        ]
      },
      { role: 'tool', tool_call_id: 'c1', content: 'file contents here' }
    ]
    const e = historyToEntries(history)
    // user + tool (assistant had no text content → no assistant entry)
    expect(e).toHaveLength(2)
    const tool = e.find((x) => x.kind === 'tool')
    expect(tool).toBeDefined()
    if (tool && tool.kind === 'tool') {
      expect(tool.name).toBe('read_file')
      expect(tool.status).toBe('done')
      expect(tool.args).toEqual({ path: 'a.txt' })
      expect(tool.summary).toBe('file contents here')
    }
  })

  it('attaches the tool result to the matching tool entry by tool_call_id', () => {
    const e = historyToEntries([
      {
        role: 'assistant',
        content: 'working',
        tool_calls: [
          { id: 'a', function: { name: 'glob', arguments: '{}' } },
          { id: 'b', function: { name: 'grep', arguments: '{}' } }
        ]
      },
      { role: 'tool', tool_call_id: 'b', content: 'grep result' },
      { role: 'tool', tool_call_id: 'a', content: 'glob result' }
    ])
    const a = e.find((x) => x.kind === 'tool' && x.id === 'a')
    const b = e.find((x) => x.kind === 'tool' && x.id === 'b')
    expect(a && a.kind === 'tool' && a.summary).toBe('glob result')
    expect(b && b.kind === 'tool' && b.summary).toBe('grep result')
  })

  it('joins multimodal text parts and ignores images', () => {
    const e = historyToEntries([
      {
        role: 'user',
        content: [
          { type: 'text', text: 'look at' },
          { type: 'image_url', image_url: { url: 'data:...' } },
          { type: 'text', text: 'this' }
        ] as unknown as RawLlmMessage['content']
      }
    ])
    expect(e).toHaveLength(1)
    expect(e[0]).toMatchObject({ kind: 'user', text: 'look at this' })
  })

  it('tolerates empty/undefined history and bad arguments JSON', () => {
    expect(historyToEntries(undefined)).toEqual([])
    expect(historyToEntries([])).toEqual([])
    const e = historyToEntries([
      { role: 'assistant', content: '', tool_calls: [{ id: 'x', function: { name: 'run_command', arguments: 'not json' } }] }
    ])
    const tool = e.find((x) => x.kind === 'tool')
    expect(tool && tool.kind === 'tool' && tool.args).toEqual({})
  })
})

describe('filterSessions', () => {
  const list = [
    meta({ id: 'a', title: 'Fix auth bug', cwd: 'C:/proj/app', model: 'grok-build-0.1' }),
    meta({ id: 'b', title: 'Add tests', cwd: 'C:/proj/api', model: 'grok-4' }),
    meta({ id: 'c', title: 'Refactor parser', cwd: 'C:/other/lib', model: 'grok-build-0.1' })
  ]

  it('returns the list unchanged for an empty/whitespace query', () => {
    expect(filterSessions(list, '')).toHaveLength(3)
    expect(filterSessions(list, '   ')).toHaveLength(3)
  })

  it('matches by title (case-insensitive)', () => {
    expect(filterSessions(list, 'AUTH').map((s) => s.id)).toEqual(['a'])
  })

  it('matches by folder path and model', () => {
    expect(filterSessions(list, 'api').map((s) => s.id)).toEqual(['b'])
    expect(filterSessions(list, 'grok-build').map((s) => s.id)).toEqual(['a', 'c'])
  })

  it('treats spaces as AND tokens across fields', () => {
    expect(filterSessions(list, 'refactor lib').map((s) => s.id)).toEqual(['c'])
    expect(filterSessions(list, 'auth api')).toHaveLength(0)
  })
})

describe('sessionsForWorkspace', () => {
  const list = [
    meta({ id: 'a', cwd: 'C:/proj/app' }),
    meta({ id: 'b', cwd: 'C:/proj/app/' }), // trailing slash
    meta({ id: 'c', cwd: 'C:\\proj\\app' }), // backslashes
    meta({ id: 'd', cwd: 'C:/other/lib' }),
    meta({ id: 'e', cwd: '' }) // no folder
  ]

  it('keeps only sessions whose folder matches (normalizing slashes/case/trailing)', () => {
    expect(sessionsForWorkspace(list, 'c:/proj/app').map((s) => s.id)).toEqual(['a', 'b', 'c'])
  })

  it('returns the list unchanged when no workspace is open', () => {
    expect(sessionsForWorkspace(list, null)).toHaveLength(5)
    expect(sessionsForWorkspace(list, '')).toHaveLength(5)
  })

  it('returns nothing when no session belongs to the folder', () => {
    expect(sessionsForWorkspace(list, 'C:/nope')).toHaveLength(0)
  })
})
