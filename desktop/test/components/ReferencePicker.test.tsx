// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { NativeReferenceItem } from '../../src/renderer/src/types'
import { ReferencePicker } from '../../src/renderer/src/components/ReferencePicker'

const stored: NativeReferenceItem = {
  id: '0123456789abcdef0123456789abcdef',
  name: 'Hero.png',
  mime: 'image/png',
  bytes: 2,
  updatedAt: 1,
  uri: 'caelo-reference://image/0123456789abcdef0123456789abcdef'
}

const listReferenceLibrary = vi.fn()
const importReferenceLibrary = vi.fn()
const getReferenceDataUri = vi.fn()
const deleteReferenceImage = vi.fn()

beforeEach(() => {
  listReferenceLibrary.mockReset().mockResolvedValue([stored])
  importReferenceLibrary.mockReset().mockResolvedValue([])
  getReferenceDataUri.mockReset().mockResolvedValue('data:image/png;base64,AA')
  deleteReferenceImage.mockReset().mockResolvedValue(true)
  Object.defineProperty(window, 'caelo', {
    configurable: true,
    value: {
      getCore: vi.fn(), coreRequest: vi.fn(), onCoreStatus: vi.fn(), selectFolder: vi.fn(), openPath: vi.fn(),
      listReferenceLibrary, importReferenceLibrary, getReferenceDataUri, deleteReferenceImage
    }
  })
})

function renderPicker(onAdd = vi.fn()): void {
  render(<ReferencePicker
    conn={{ baseUrl: 'http://127.0.0.1:1', token: 'test' }}
    max={3}
    current={[]}
    defaultRole="character"
    onAdd={onAdd}
    onClose={vi.fn()}
  />)
}

describe('ReferencePicker', () => {
  it('wybiera zapisany obraz bez wywołań HTTP i zwraca go jako referencję', async () => {
    const onAdd = vi.fn()
    renderPicker(onAdd)

    await userEvent.click(await screen.findByRole('button', { name: 'Select Hero.png' }))
    await userEvent.click(screen.getByRole('button', { name: 'Add selected (1)' }))

    await waitFor(() => expect(onAdd).toHaveBeenCalledWith([{
      name: 'Hero.png',
      uri: 'data:image/png;base64,AA',
      libraryId: stored.id,
      role: 'character'
    }]))
    expect(getReferenceDataUri).toHaveBeenCalledWith(stored.id)
  })

  it('usuwa obraz z biblioteki dopiero po potwierdzeniu', async () => {
    renderPicker()

    await userEvent.click(await screen.findByRole('button', { name: 'Delete Hero.png' }))
    // Sam klik w kosz niczego nie kasuje — plik znika z dysku nieodwracalnie.
    expect(deleteReferenceImage).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole('button', { name: 'Confirm deleting Hero.png' }))
    await waitFor(() => expect(deleteReferenceImage).toHaveBeenCalledWith(stored.id))
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Select Hero.png' })).not.toBeInTheDocument()
    )
    expect(screen.getByText('The reference library is empty')).toBeInTheDocument()
  })

  it('anulowanie potwierdzenia zostawia obraz w bibliotece', async () => {
    renderPicker()

    await userEvent.click(await screen.findByRole('button', { name: 'Delete Hero.png' }))
    await userEvent.click(screen.getByRole('button', { name: 'Cancel deleting Hero.png' }))

    expect(deleteReferenceImage).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Select Hero.png' })).toBeInTheDocument()
  })

  it('importuje przez natywne kopiowanie pliku i automatycznie zaznacza wynik', async () => {
    listReferenceLibrary.mockResolvedValue([])
    importReferenceLibrary.mockResolvedValue([stored])
    renderPicker()

    await userEvent.click(await screen.findByRole('button', { name: /Import images/i }))

    expect(await screen.findByRole('button', { name: 'Deselect Hero.png' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add selected (1)' })).toBeEnabled()
  })
})
