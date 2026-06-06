// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { IconButton } from '../../src/renderer/src/components/ui/IconButton'

const Icon = (): React.ReactElement => <svg data-testid="icon" />

describe('IconButton', () => {
  it('exposes its label as the accessible name', () => {
    render(<IconButton label="Settings" icon={<Icon />} tooltip={false} />)
    expect(screen.getByRole('button', { name: 'Settings' })).toBeInTheDocument()
  })

  it('reflects active state via aria-pressed', () => {
    render(<IconButton label="Mic" icon={<Icon />} active tooltip={false} />)
    expect(screen.getByRole('button', { name: 'Mic' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('fires onClick', async () => {
    const onClick = vi.fn()
    render(<IconButton label="Go" icon={<Icon />} tooltip={false} onClick={onClick} />)
    await userEvent.click(screen.getByRole('button', { name: 'Go' }))
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('renders a tooltip with the label when enabled', () => {
    render(<IconButton label="Help" icon={<Icon />} />)
    expect(screen.getByRole('tooltip')).toHaveTextContent('Help')
  })
})
