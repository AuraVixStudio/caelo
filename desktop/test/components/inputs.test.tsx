// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Input } from '../../src/renderer/src/components/ui/Input'
import { Textarea } from '../../src/renderer/src/components/ui/Textarea'

describe('Input', () => {
  it('fires onChange on typing', async () => {
    const onChange = vi.fn()
    render(<Input value="" placeholder="name" onChange={onChange} />)
    await userEvent.type(screen.getByPlaceholderText('name'), 'a')
    expect(onChange).toHaveBeenCalled()
  })

  it('renders the controlled value', () => {
    render(<Input value="hello" readOnly />)
    expect(screen.getByDisplayValue('hello')).toBeInTheDocument()
  })

  it('respects the disabled attribute', () => {
    render(<Input placeholder="p" disabled />)
    expect(screen.getByPlaceholderText('p')).toBeDisabled()
  })
})

describe('Textarea', () => {
  it('fires onChange on typing', async () => {
    const onChange = vi.fn()
    render(<Textarea value="" placeholder="msg" onChange={onChange} />)
    await userEvent.type(screen.getByPlaceholderText('msg'), 'x')
    expect(onChange).toHaveBeenCalled()
  })

  it('respects the disabled attribute', () => {
    render(<Textarea placeholder="m" disabled />)
    expect(screen.getByPlaceholderText('m')).toBeDisabled()
  })
})
