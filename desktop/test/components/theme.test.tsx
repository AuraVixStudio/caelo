// @vitest-environment jsdom
import './_matchMedia' // side-effect: stub matchMedia BEFORE importing lib/theme (reads it at load)
import '@testing-library/jest-dom/vitest'
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ThemeProvider, useTheme } from '../../src/renderer/src/lib/theme'

function Probe(): React.ReactElement {
  const { theme, setTheme } = useTheme()
  return (
    <div>
      <span data-testid="mode">{theme}</span>
      <button onClick={() => setTheme('dark')}>dark</button>
      <button onClick={() => setTheme('light')}>light</button>
    </div>
  )
}

describe('ThemeProvider / useTheme', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.classList.remove('dark')
  })

  it('defaults to system mode', () => {
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>
    )
    expect(screen.getByTestId('mode')).toHaveTextContent('system')
  })

  it('setTheme("dark") adds the .dark class and persists', async () => {
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>
    )
    await userEvent.click(screen.getByRole('button', { name: 'dark' }))
    expect(screen.getByTestId('mode')).toHaveTextContent('dark')
    expect(document.documentElement).toHaveClass('dark')
    expect(localStorage.getItem('caelo.theme')).toBe('dark')
  })

  it('setTheme("light") removes the .dark class', async () => {
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>
    )
    await userEvent.click(screen.getByRole('button', { name: 'dark' }))
    await userEvent.click(screen.getByRole('button', { name: 'light' }))
    expect(document.documentElement).not.toHaveClass('dark')
    expect(localStorage.getItem('caelo.theme')).toBe('light')
  })
})
