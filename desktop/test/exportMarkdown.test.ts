// M19-B10: tests for the chat→Markdown serializer (pure utils).
import { describe, it, expect } from 'vitest'
import { conversationToMarkdown, safeFilename } from '../src/renderer/src/lib/exportMarkdown'
import type { Conversation } from '../src/renderer/src/lib/storage'

function conv(messages: Conversation['messages'], title = 'My chat'): Conversation {
  return { id: 'c1', title, created: 0, messages }
}

describe('conversationToMarkdown', () => {
  it('includes the title and user/assistant turns', () => {
    const md = conversationToMarkdown(
      conv([
        { role: 'user', content: 'What is Grok?' },
        { role: 'assistant', content: 'A model by xAI.' }
      ])
    )
    expect(md).toContain('# My chat')
    expect(md).toContain('## You')
    expect(md).toContain('What is Grok?')
    expect(md).toContain('## Assistant')
    expect(md).toContain('A model by xAI.')
  })

  it('renders assistant citations as Markdown links', () => {
    const md = conversationToMarkdown(
      conv([
        { role: 'user', content: 'news?' },
        {
          role: 'assistant',
          content: 'Here.',
          citations: [{ url: 'https://x.ai', title: 'xAI' }, { url: 'https://example.com' }]
        }
      ])
    )
    expect(md).toContain('**Sources:**')
    expect(md).toContain('[xAI](https://x.ai)')
    // citation without a title falls back to the URL as link text
    expect(md).toContain('[https://example.com](https://example.com)')
  })

  it('handles empty content gracefully', () => {
    const md = conversationToMarkdown(conv([{ role: 'assistant', content: '' }]))
    expect(md).toContain('(no response)')
  })

  it('falls back to a default title and ends with a single newline', () => {
    const md = conversationToMarkdown(conv([{ role: 'user', content: 'hi' }], ''))
    expect(md.startsWith('# Chat')).toBe(true)
    expect(md.endsWith('\n')).toBe(true)
    expect(md.endsWith('\n\n')).toBe(false)
  })
})

describe('safeFilename', () => {
  it('slugs unsafe characters and trims', () => {
    expect(safeFilename('Hello, World! / test')).toBe('Hello-World-test')
  })

  it('falls back when the title is empty or all-unsafe', () => {
    expect(safeFilename('')).toBe('chat')
    expect(safeFilename('///')).toBe('chat')
    expect(safeFilename('', 'session')).toBe('session')
  })

  it('caps length at 60 characters', () => {
    expect(safeFilename('a'.repeat(200)).length).toBeLessThanOrEqual(60)
  })
})
