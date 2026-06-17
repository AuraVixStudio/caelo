// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { EffortSelect } from '../../src/renderer/src/components/ui/EffortSelect'

// Faza-G: gdy wybrany model nie wspiera reasoning_effort, EffortSelect ostrzega — trigger
// (aria-label + kolor warn) gdy wybrany jest realny effort, a dropdown zawsze informuje.
describe('EffortSelect — wskaźnik braku wsparcia reasoning_effort', () => {
  it('model bez wsparcia + wybrany effort → trigger ostrzega + nota w dropdownie', () => {
    render(<EffortSelect effort="high" model="grok-build-0.1" onSelect={() => undefined} />)
    const trigger = screen.getByRole('button', { name: /reasoning effort/i })
    expect(trigger.getAttribute('aria-label')).toMatch(/not supported by the selected model/i)
    fireEvent.click(trigger) // otwórz dropdown (portal)
    expect(screen.getByText(/ignores reasoning effort/i)).toBeInTheDocument()
  })

  it('model wspierający (grok-4.3) → brak ostrzeżenia', () => {
    render(<EffortSelect effort="high" model="grok-4.3" onSelect={() => undefined} />)
    const trigger = screen.getByRole('button', { name: /reasoning effort/i })
    expect(trigger.getAttribute('aria-label')).not.toMatch(/not supported/i)
    fireEvent.click(trigger)
    expect(screen.queryByText(/ignores reasoning effort/i)).toBeNull()
  })

  it('Auto na modelu bez wsparcia → trigger nie ostrzega, ale dropdown nadal informuje', () => {
    render(<EffortSelect effort="" model="grok-build-0.1" onSelect={() => undefined} />)
    const trigger = screen.getByRole('button', { name: /reasoning effort/i })
    expect(trigger.getAttribute('aria-label')).not.toMatch(/not supported/i)
    fireEvent.click(trigger)
    expect(screen.getByText(/ignores reasoning effort/i)).toBeInTheDocument()
  })
})
