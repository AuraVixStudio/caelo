// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ReferenceLibrary } from '../../src/renderer/src/components/ReferenceLibrary'
import type { ReferenceRoleOption } from '../../src/renderer/src/lib/referenceRoles'

const flashOptions: ReferenceRoleOption[] = [
  { value: 'character', label: 'Character', max: 4 },
  { value: 'general', label: 'General', max: 14 },
  { value: 'object', label: 'Object', max: 10 },
  { value: 'starting_image', label: 'Starting Image', max: 1 }
]

describe('ReferenceLibrary', () => {
  it('pokazuje role aktywnego modelu i zapisuje wybór Starting Image', async () => {
    const onChange = vi.fn()
    render(<ReferenceLibrary
      items={[{ name: 'portrait.png', uri: 'data:image/png;base64,AA', role: 'general' }]}
      max={14}
      onChange={onChange}
      options={flashOptions}
    />)

    const select = screen.getByRole('combobox')
    expect(Array.from(select.querySelectorAll('option')).map((option) => option.textContent)).toEqual([
      'Character', 'General', 'Object', 'Starting Image'
    ])
    expect(screen.queryByRole('option', { name: 'Style' })).not.toBeInTheDocument()

    await userEvent.selectOptions(select, 'starting_image')
    expect(onChange).toHaveBeenCalledWith([
      { name: 'portrait.png', uri: 'data:image/png;base64,AA', role: 'starting_image' }
    ])
  })

  it('otwiera duży podgląd miniatury i zamyka go klawiszem Escape', async () => {
    render(<ReferenceLibrary
      items={[{ name: 'portrait.png', uri: 'data:image/png;base64,AA', role: 'general' }]}
      max={3}
      onChange={vi.fn()}
      options={flashOptions}
    />)

    await userEvent.click(screen.getByRole('button', { name: 'Preview portrait.png' }))
    const preview = screen.getByRole('dialog', { name: 'Preview portrait.png' })
    expect(preview).toBeInTheDocument()
    expect(within(preview).getByRole('img', { name: 'portrait.png' })).toBeInTheDocument()

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: 'Preview portrait.png' })).not.toBeInTheDocument()
  })
})
