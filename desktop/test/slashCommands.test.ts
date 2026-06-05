// M14-F3: testy czystych utili komend slash — filtrowanie/ranking, detekcja „/",
// parsowanie „/name rest" i rozwijanie szablonu ({input}/{args}).
import { describe, it, expect } from 'vitest'
import {
  expandTemplate,
  filterSlashCommands,
  matchSlash,
  slashQuery
} from '../src/renderer/src/lib/slashCommands'

const CMDS = [
  { name: 'plan', description: 'Make a plan', template: 'Plan: {input}' },
  { name: 'review', description: 'Review changes', template: 'Review: {input}' },
  { name: 'commit', description: 'Propose a commit', template: 'Commit. {input}' },
  { name: 'mcp', description: 'Open MCP manager', template: 'List MCP {input}', action: 'open_mcp' }
]

describe('filterSlashCommands (F3: command filter)', () => {
  it('returns all for an empty query', () => {
    expect(filterSlashCommands(CMDS, '').length).toBe(4)
  })

  it('matches by name prefix and ranks exact first', () => {
    const r = filterSlashCommands(CMDS, 'c')
    expect(r.map((c) => c.name)).toContain('commit')
  })

  it('tolerates a leading slash in the query', () => {
    expect(filterSlashCommands(CMDS, '/plan')[0].name).toBe('plan')
  })

  it('matches by description', () => {
    expect(filterSlashCommands(CMDS, 'changes').map((c) => c.name)).toEqual(['review'])
  })

  it('drops non-matches', () => {
    expect(filterSlashCommands(CMDS, 'zzz')).toEqual([])
  })
})

describe('slashQuery (F3: dropdown toggle)', () => {
  it('returns the partial name while typing a command', () => {
    expect(slashQuery('/pl')).toBe('pl')
  })

  it('returns "" for a lone slash', () => {
    expect(slashQuery('/')).toBe('')
  })

  it('returns null once a space (args) is typed', () => {
    expect(slashQuery('/plan do x')).toBeNull()
  })

  it('returns null for plain text', () => {
    expect(slashQuery('hello')).toBeNull()
  })
})

describe('matchSlash (F3: invocation parse)', () => {
  it('parses name + rest', () => {
    expect(matchSlash('/plan refactor auth')).toEqual({ name: 'plan', rest: 'refactor auth' })
  })

  it('parses a bare command with empty rest', () => {
    expect(matchSlash('/mcp')).toEqual({ name: 'mcp', rest: '' })
  })

  it('returns null for non-slash text', () => {
    expect(matchSlash('hello /plan')).toBeNull()
  })
})

describe('expandTemplate (F3: template expansion)', () => {
  it('substitutes {input} and {args}', () => {
    expect(expandTemplate('Plan: {input} ({args})', 'do x')).toBe('Plan: do x (do x)')
  })

  it('collapses to a clean string when input is empty', () => {
    expect(expandTemplate('Review: {input}', '')).toBe('Review:')
  })
})
