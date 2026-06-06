// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Slider } from '../../src/renderer/src/components/ui/Slider'

describe('Slider', () => {
  it('renders a range input with the given value', () => {
    render(<Slider aria-label="vol" min={0} max={10} defaultValue={3} />)
    const el = screen.getByRole('slider', { name: 'vol' }) as HTMLInputElement
    expect(el).toHaveAttribute('type', 'range')
    expect(el.value).toBe('3')
  })

  it('honors min and max', () => {
    render(<Slider aria-label="t" min={1} max={5} defaultValue={2} />)
    const el = screen.getByRole('slider', { name: 't' })
    expect(el).toHaveAttribute('min', '1')
    expect(el).toHaveAttribute('max', '5')
  })
})
