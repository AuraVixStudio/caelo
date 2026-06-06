// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Card } from '../../src/renderer/src/components/ui/Card'

describe('Card', () => {
  it('renders title, subtitle and children', () => {
    render(
      <Card title="Account" subtitle="Manage keys">
        <p>Body</p>
      </Card>
    )
    expect(screen.getByRole('heading', { name: 'Account' })).toBeInTheDocument()
    expect(screen.getByText('Manage keys')).toBeInTheDocument()
    expect(screen.getByText('Body')).toBeInTheDocument()
  })

  it('renders children without an optional title', () => {
    render(
      <Card>
        <span>Only body</span>
      </Card>
    )
    expect(screen.getByText('Only body')).toBeInTheDocument()
    expect(screen.queryByRole('heading')).not.toBeInTheDocument()
  })
})
