// M9-F5: test czystego filtrowania/rankingu komend palety.
import { describe, it, expect } from 'vitest'
import { filterCommands, type Command } from '../src/renderer/src/lib/commands'

const noop = (): void => undefined
const cmd = (id: string, title: string, extra: Partial<Command> = {}): Command => ({
  id,
  title,
  run: noop,
  ...extra
})

const CMDS: Command[] = [
  cmd('chat', 'Chat', { hint: 'Go to', keywords: 'chat' }),
  cmd('code', 'Code', { hint: 'Go to' }),
  cmd('image', 'Image', { hint: 'Go to' }),
  cmd('history', 'History', { hint: 'Go to', keywords: 'search' })
]

describe('filterCommands', () => {
  it('returns all commands for an empty query, unchanged order', () => {
    expect(filterCommands(CMDS, '').map((c) => c.id)).toEqual(['chat', 'code', 'image', 'history'])
    expect(filterCommands(CMDS, '   ').map((c) => c.id)).toEqual([
      'chat',
      'code',
      'image',
      'history'
    ])
  })

  it('matches by title (case-insensitive) and drops non-matches', () => {
    expect(filterCommands(CMDS, 'cod').map((c) => c.id)).toEqual(['code'])
    expect(filterCommands(CMDS, 'IMAGE').map((c) => c.id)).toEqual(['image'])
    expect(filterCommands(CMDS, 'zzz')).toEqual([])
  })

  it('ranks prefix matches above substring matches', () => {
    const cmds = [cmd('a', 'Search history'), cmd('b', 'Chat')]
    // query 'ch' is a prefix of "Chat" (score 60) and a substring of "Search" (40)
    expect(filterCommands(cmds, 'ch').map((c) => c.id)).toEqual(['b', 'a'])
  })

  it('matches helper fields (hint/keywords) when the title does not', () => {
    expect(filterCommands(CMDS, 'search').map((c) => c.id)).toEqual(['history'])
  })
})
