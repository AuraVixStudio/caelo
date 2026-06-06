// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CommandPalette } from '../../src/renderer/src/components/CommandPalette'
import type { Command } from '../../src/renderer/src/lib/commands'

function makeCommands(run = vi.fn()): Command[] {
  return [
    { id: 'goto-chat', title: 'Chat', hint: 'Go to', keywords: 'chat', run },
    { id: 'goto-voice', title: 'Voice', hint: 'Go to', keywords: 'voice', run },
    { id: 'goto-settings', title: 'Settings', hint: 'Go to', keywords: 'settings', run }
  ]
}

const input = (): HTMLElement => screen.getByRole('textbox', { name: 'Command palette search' })

describe('CommandPalette', () => {
  it('renders nothing when closed', () => {
    render(<CommandPalette open={false} onClose={() => {}} commands={makeCommands()} />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows the dialog and all commands when open', () => {
    render(<CommandPalette open onClose={() => {}} commands={makeCommands()} />)
    expect(screen.getByRole('dialog', { name: 'Command palette' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Chat/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Voice/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Settings/ })).toBeInTheDocument()
  })

  it('filters commands by the search query', async () => {
    render(<CommandPalette open onClose={() => {}} commands={makeCommands()} />)
    await userEvent.type(input(), 'voice')
    expect(screen.getByRole('button', { name: /Voice/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Chat/ })).not.toBeInTheDocument()
  })

  it('runs a command and closes on click', async () => {
    const run = vi.fn()
    const onClose = vi.fn()
    render(<CommandPalette open onClose={onClose} commands={makeCommands(run)} />)
    await userEvent.click(screen.getByRole('button', { name: /Settings/ }))
    expect(run).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('runs the active command on Enter', async () => {
    const run = vi.fn()
    const onClose = vi.fn()
    render(<CommandPalette open onClose={onClose} commands={makeCommands(run)} />)
    await userEvent.type(input(), '{Enter}')
    expect(run).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('closes on Escape without running a command', async () => {
    const run = vi.fn()
    const onClose = vi.fn()
    render(<CommandPalette open onClose={onClose} commands={makeCommands(run)} />)
    await userEvent.type(input(), '{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(run).not.toHaveBeenCalled()
  })

  it('shows an empty state when nothing matches', async () => {
    render(<CommandPalette open onClose={() => {}} commands={makeCommands()} />)
    await userEvent.type(input(), 'zzzzz')
    expect(screen.getByText('No matching commands')).toBeInTheDocument()
  })
})
