// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
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

// TOP5: bloki ```html / ```svg renderują się jako artefakt w SANDBOXOWANYM iframe (Preview),
// z możliwością przełączenia na surowe źródło (Code). Inne języki zostają zwykłym blokiem kodu.
describe('Markdown — artefakty HTML/SVG (TOP5)', () => {
  it('blok ```html → sandboxowany iframe z kodem + CSP', () => {
    render(<Markdown text={'```html\n<h1>Hi artifact</h1>\n```'} />)
    const iframe = screen.getByTitle('html artifact preview')
    expect(iframe).toHaveAttribute('sandbox', 'allow-scripts')
    const doc = iframe.getAttribute('srcdoc') || ''
    expect(doc).toContain('<h1>Hi artifact</h1>')
    expect(doc).toContain('Content-Security-Policy')
  })

  it('blok ```svg → iframe artefaktu', () => {
    render(<Markdown text={'```svg\n<svg><circle r="4"/></svg>\n```'} />)
    expect(screen.getByTitle('svg artifact preview')).toBeInTheDocument()
  })

  it('inne języki (python) NIE są artefaktem (brak iframe)', () => {
    const { container } = render(<Markdown text={'```python\nprint(1)\n```'} />)
    expect(container.querySelector('iframe')).toBeNull()
  })

  it('toggle „Code" pokazuje surowe źródło zamiast iframe', () => {
    render(<Markdown text={'```html\n<h1>Toggle me</h1>\n```'} />)
    expect(screen.getByTitle('html artifact preview')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /code/i }))
    expect(screen.queryByTitle('html artifact preview')).toBeNull()
    expect(screen.getByText(/Toggle me/)).toBeInTheDocument()
  })
})
