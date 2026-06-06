// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Badge } from '../../src/renderer/src/components/ui/Badge'

describe('Badge', () => {
  it('renders its children', () => {
    render(<Badge>NEW</Badge>)
    expect(screen.getByText('NEW')).toBeInTheDocument()
  })

  it('applies the tone class', () => {
    render(<Badge tone="error">ERR</Badge>)
    expect(screen.getByText('ERR').className).toContain('text-error')
  })
})
