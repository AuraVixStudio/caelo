// P3-9: testy czystych funkcji storage (tytułowanie + M22 grupowanie po projekcie).
import { describe, it, expect } from 'vitest'
import {
  conversationsForProject,
  newConversation,
  titleFromText,
  type Conversation
} from '../src/renderer/src/lib/storage'

describe('titleFromText', () => {
  it('falls back to "New chat" for empty/whitespace input', () => {
    expect(titleFromText('')).toBe('New chat')
    expect(titleFromText('   \n\t ')).toBe('New chat')
  })

  it('collapses internal whitespace runs to single spaces', () => {
    expect(titleFromText('hello   world\n\ttabs')).toBe('hello world tabs')
  })

  it('truncates long text to 34 chars + ellipsis', () => {
    const t = titleFromText('a'.repeat(50))
    expect(t.endsWith('…')).toBe(true)
    expect(t.length).toBe(35) // 34 znaki + 1 znak wielokropka
  })

  it('keeps short text as-is', () => {
    expect(titleFromText('short title')).toBe('short title')
  })
})

describe('newConversation', () => {
  it('stamps the given project id (null when omitted)', () => {
    expect(newConversation('p1').project_id).toBe('p1')
    expect(newConversation().project_id).toBe(null)
  })
})

describe('conversationsForProject (M22)', () => {
  const mk = (id: string, project_id?: string | null): Conversation => ({
    id,
    title: id,
    created: 0,
    project_id,
    messages: []
  })
  const list = [mk('a', 'p1'), mk('b', 'p2'), mk('c', null), mk('d', 'p1'), mk('e')]

  it('returns the whole list for "All projects" (null)', () => {
    expect(conversationsForProject(list, null)).toHaveLength(5)
  })

  it('keeps only conversations of the given project', () => {
    expect(conversationsForProject(list, 'p1').map((c) => c.id)).toEqual(['a', 'd'])
    expect(conversationsForProject(list, 'p2').map((c) => c.id)).toEqual(['b'])
  })

  it('excludes project-less and other-project conversations', () => {
    const ids = conversationsForProject(list, 'p1').map((c) => c.id)
    expect(ids).not.toContain('c') // project_id null
    expect(ids).not.toContain('e') // project_id undefined
    expect(ids).not.toContain('b') // other project
  })
})
