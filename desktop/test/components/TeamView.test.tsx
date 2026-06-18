// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock warstwy API: TeamView pobiera diff scalenia leniwie po otwarciu review.
vi.mock('../../src/renderer/src/lib/api', async (orig) => {
  const actual = await orig<typeof import('../../src/renderer/src/lib/api')>()
  return { ...actual, teamMergeDiff: vi.fn(async () => ({ diff: '--- a/util.py\n+++ b/util.py\n@@\n+x' })) }
})

import { TeamView } from '../../src/renderer/src/components/code/TeamView'
import { teamMergeDiff, type Conn, type TeamMerge } from '../../src/renderer/src/lib/api'
import { applyStatus, type SubAgentMap } from '../../src/renderer/src/lib/teamView'

const conn = { port: 1, token: 't' } as unknown as Conn

function mergeFor(agent_id: string, conflicts: string[] = []): TeamMerge {
  return {
    id: `m_${agent_id}`,
    agent_id,
    role: 'implementer',
    task: 'add version()',
    files: [{ path: 'util.py' } as never],
    conflicts,
    created_at: 0,
    file_count: 1
  }
}

function nodes(): SubAgentMap {
  return applyStatus({}, {
    agent_id: 'sa1',
    role: 'implementer',
    task: 'add version()',
    status: 'done',
    summary: 'done',
    merge_id: 'm_sa1',
    files_changed: 1,
    turns: 1,
    tool_calls: 1
  })
}

const noop = () => {}

describe('TeamView merge review (F2)', () => {
  it('opens the merge diff in a modal dialog with reachable Accept/Discard buttons', async () => {
    const user = userEvent.setup()
    render(
      <TeamView
        nodes={nodes()}
        merges={[mergeFor('sa1')]}
        report={null}
        conn={conn}
        onApprove={noop}
        onApplyMerge={noop}
        onRejectMerge={noop}
        busy={false}
      />
    )
    // Brak modala, dopóki nie klikniemy „Review merge".
    expect(screen.queryByRole('dialog')).toBeNull()

    await user.click(screen.getByText(/Review merge/i))

    const dialog = await screen.findByRole('dialog', { name: /review merge/i })
    expect(dialog).toBeInTheDocument()
    // Przyciski w stopce modala są dostępne (regresja: wcześniej inline, poza zasięgiem w max-h-64).
    expect(screen.getByRole('button', { name: /accept & merge/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^discard$/i })).toBeInTheDocument()
    expect(teamMergeDiff).toHaveBeenCalled()
  })

  it('surfaces a conflict badge when another worktree changed the same file', async () => {
    const user = userEvent.setup()
    render(
      <TeamView
        nodes={nodes()}
        merges={[mergeFor('sa1', ['src/calculator.py'])]}
        report={null}
        conn={conn}
        onApprove={noop}
        onApplyMerge={noop}
        onRejectMerge={noop}
        busy={false}
      />
    )
    await user.click(screen.getByText(/Review merge/i))
    const dialog = await screen.findByRole('dialog', { name: /review merge/i })
    expect(dialog).toHaveTextContent(/conflict/i)
    expect(dialog).toHaveTextContent('src/calculator.py')
  })
})
