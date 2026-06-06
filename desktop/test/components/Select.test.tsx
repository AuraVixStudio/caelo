// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Select } from '../../src/renderer/src/components/ui/Select'

describe('Select', () => {
  it('renders its options', () => {
    render(
      <Select aria-label="pick">
        <option value="a">Alpha</option>
        <option value="b">Beta</option>
      </Select>
    )
    expect(screen.getByRole('option', { name: 'Alpha' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Beta' })).toBeInTheDocument()
  })

  it('fires onChange with the selected value', async () => {
    const onChange = vi.fn()
    render(
      <Select aria-label="pick" defaultValue="a" onChange={onChange}>
        <option value="a">Alpha</option>
        <option value="b">Beta</option>
      </Select>
    )
    const el = screen.getByRole('combobox', { name: 'pick' }) as HTMLSelectElement
    await userEvent.selectOptions(el, 'b')
    expect(onChange).toHaveBeenCalled()
    expect(el.value).toBe('b')
  })
})
