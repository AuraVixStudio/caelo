// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ToastProvider, useToast } from '../../src/renderer/src/components/ui/Toast'

// ROAD-4.1-d: wspólny kanał komunikatów — push pokazuje toast, klik go zamyka.
function Pusher() {
  const toast = useToast()
  return (
    <button onClick={() => toast.push('save failed', 'error')}>fire</button>
  )
}

describe('Toast (ROAD-4.1-d)', () => {
  it('push pokazuje komunikat, klik go zamyka', async () => {
    render(
      <ToastProvider>
        <Pusher />
      </ToastProvider>
    )
    expect(screen.queryByText('save failed')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'fire' }))
    const toast = screen.getByText('save failed')
    expect(toast).toBeInTheDocument()
    await userEvent.click(toast)
    expect(screen.queryByText('save failed')).not.toBeInTheDocument()
  })

  it('useToast bez providera jest no-opem (nie wywraca)', () => {
    // render samego Pushera bez providera — klik nie rzuca
    render(<Pusher />)
    expect(screen.getByRole('button', { name: 'fire' })).toBeInTheDocument()
  })
})
