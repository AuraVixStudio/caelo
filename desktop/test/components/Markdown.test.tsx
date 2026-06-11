// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Markdown } from '../../src/renderer/src/components/Markdown'

// P1-F: linki z markdownu modelu muszą dostać target=_blank (→ shell.openExternal),
// inaczej klik = nawigacja top-level blokowana przez will-navigate (link nic nie robi).
describe('Markdown — linki (P1-F)', () => {
  it('renderuje <a> z target=_blank i rel=noreferrer', () => {
    render(<Markdown text={'[example](https://example.com)'} />)
    const link = screen.getByRole('link', { name: 'example' })
    expect(link).toHaveAttribute('href', 'https://example.com')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link.getAttribute('rel') || '').toContain('noreferrer')
  })
})
