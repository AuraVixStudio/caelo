// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Panele robią I/O na mount — zastępujemy je pustymi, test dotyczy tylko semantyki tabów.
vi.mock('../../src/renderer/src/components/extensions/McpServers', () => ({ McpServers: () => null }))
vi.mock('../../src/renderer/src/components/extensions/LspServers', () => ({ LspServers: () => null }))
vi.mock('../../src/renderer/src/components/extensions/HooksPanel', () => ({ HooksPanel: () => null }))
vi.mock('../../src/renderer/src/components/extensions/SkillsLibrary', () => ({ SkillsLibrary: () => null }))
vi.mock('../../src/renderer/src/components/extensions/CommandsPanel', () => ({ CommandsPanel: () => null }))
vi.mock('../../src/renderer/src/components/extensions/SubagentsPanel', () => ({ SubagentsPanel: () => null }))
vi.mock('../../src/renderer/src/components/extensions/Marketplace', () => ({ Marketplace: () => null }))
vi.mock('../../src/renderer/src/lib/api', async (orig) => ({
  ...(await orig<Record<string, unknown>>()),
  getSandboxStatus: vi.fn().mockResolvedValue({
    profile: 'off',
    availability: { platform: 'win32', available: false, mechanism: 'none', reason: '' }
  })
}))

import { Extensions } from '../../src/renderer/src/components/Extensions'

const conn = { baseUrl: '', token: '' } as never

describe('Extensions — ARIA tabs (S35-m)', () => {
  it('tablist + taby z dokładnie jednym aria-selected + tabpanel', () => {
    render(<Extensions conn={conn} />)
    expect(screen.getByRole('tablist', { name: 'Extensions' })).toBeInTheDocument()
    const tabs = screen.getAllByRole('tab')
    expect(tabs).toHaveLength(7)
    expect(tabs.filter((t) => t.getAttribute('aria-selected') === 'true')).toHaveLength(1)
    expect(screen.getByRole('tabpanel')).toBeInTheDocument()
  })

  it('strzałka → przełącza aktywną zakładkę (roving tabindex)', async () => {
    render(<Extensions conn={conn} />)
    const tabs = screen.getAllByRole('tab')
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true') // mcp
    tabs[0].focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(tabs[1]).toHaveAttribute('aria-selected', 'true') // lsp
  })
})
