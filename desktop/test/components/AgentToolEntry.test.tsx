// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { EntryView, type Entry } from '../../src/renderer/src/components/code/AgentPanel'

// Kompaktowy wpis narzędzia: domyślnie zwinięty (jeden wiersz), output/summary chowane,
// żeby seria odczytów plików nie zalewała transkryptu. Awaiting/error wymuszają rozwinięcie.
const toolEntry = (over: Partial<Extract<Entry, { kind: 'tool' }>> = {}): Entry => ({
  kind: 'tool',
  id: 't1',
  name: 'read_file',
  args: { path: 'src/app.py' },
  status: 'done',
  output: 'SECRET_OUTPUT_LINE',
  summary: 'Read 3 lines',
  ...over
})

describe('EntryView (tool) — kompaktowanie', () => {
  it('done: zwinięty domyślnie, output/summary ukryte; klik rozwija', async () => {
    render(<EntryView entry={toolEntry()} onApprove={() => undefined} />)

    // Nagłówek zawsze widoczny (nazwa + ścieżka), output/summary schowane.
    const header = screen.getByRole('button', { name: /read_file/ })
    expect(header).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('SECRET_OUTPUT_LINE')).not.toBeInTheDocument()
    expect(screen.queryByText('Read 3 lines')).not.toBeInTheDocument()

    await userEvent.click(header)

    expect(header).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('SECRET_OUTPUT_LINE')).toBeInTheDocument()
    expect(screen.getByText('Read 3 lines')).toBeInTheDocument()
  })

  it('awaiting: rozwinięty z kartą zatwierdzenia bez klikania; Accept woła onApprove', async () => {
    const onApprove = vi.fn()
    render(
      <EntryView
        entry={toolEntry({
          name: 'run_command',
          args: { command: 'npm test' },
          status: 'awaiting',
          output: '',
          summary: '',
          detail: { kind: 'command', command: 'npm test' }
        })}
        onApprove={onApprove}
      />
    )

    expect(screen.getByText(/\$ npm test/)).toBeInTheDocument() // karta komendy ($ prefix)
    await userEvent.click(screen.getByRole('button', { name: 'Accept' }))
    expect(onApprove).toHaveBeenCalledWith('t1', 'accept')
  })

  it('error: szczegóły widoczne od razu i niezwijalne (brak aria-expanded)', () => {
    render(
      <EntryView
        entry={toolEntry({ status: 'error', output: 'BOOM', summary: 'Tool failed' })}
        onApprove={() => undefined}
      />
    )

    expect(screen.getByText('BOOM')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /read_file/ })).not.toHaveAttribute('aria-expanded')
  })
})
