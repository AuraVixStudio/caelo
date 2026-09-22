import { useEffect, useMemo, useState } from 'react'
import { Check, ImagePlus, Maximize2, Trash2, Upload, X } from 'lucide-react'
import type { Conn } from '../lib/api'
import { compressImageIfNeeded, MAX_IMAGE_URI_CHARS } from '../lib/imageCompress'
import type { StagedImage } from '../lib/hub'
import type { ReferenceRole } from '../lib/referenceRoles'
import type { NativeReferenceItem } from '../types'
import { cn } from '../lib/cn'
import { ImagePreview } from './ImagePreview'
import { Button } from './ui/Button'
import { IconButton } from './ui/IconButton'

async function usableDataUri(item: NativeReferenceItem): Promise<string> {
  const uri = await window.caelo.getReferenceDataUri(item.id)
  if (uri.length <= MAX_IMAGE_URI_CHARS) return uri

  // Biblioteka przechowuje oryginał. Dopiero przy użyciu bardzo dużego zdjęcia
  // przygotowujemy mniejszą kopię wejściową dla dostawcy AI.
  const blob = await (await fetch(uri)).blob()
  const compressed = await compressImageIfNeeded(new File([blob], item.name, { type: item.mime }))
  if (!compressed.fitsBudget) throw new Error(`${item.name} is too large to use as a reference.`)
  return compressed.uri
}

export function ReferencePicker({ max, current, defaultRole, onAdd, onClose }: {
  conn: Conn // zachowane w API komponentu; biblioteka celowo nie korzysta z połączenia HTTP
  max: number
  current: StagedImage[]
  defaultRole: ReferenceRole
  onAdd: (items: StagedImage[]) => void
  onClose: () => void
}) {
  const [items, setItems] = useState<NativeReferenceItem[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [preview, setPreview] = useState<NativeReferenceItem | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loadAttempt, setLoadAttempt] = useState(0)
  // Kasowanie jest nieodwracalne (plik znika z dysku), więc kafelek pyta o
  // potwierdzenie zamiast usuwać od razu po kliknięciu w kosz.
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const currentIds = useMemo(() => new Set(current.map((item) => item.libraryId).filter(Boolean)), [current])
  const remaining = Math.max(0, max - current.length)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    window.caelo.listReferenceLibrary()
      .then((loaded) => { if (alive) setItems(loaded) })
      .catch((reason) => { if (alive) setError(String((reason as Error).message || reason)) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [loadAttempt])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key !== 'Escape' || preview) return
      // Escape zamyka najpierw potwierdzenie kasowania, dopiero potem całe okno.
      if (confirmDelete) setConfirmDelete(null)
      else onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [confirmDelete, onClose, preview])

  function toggle(id: string): void {
    if (currentIds.has(id)) return
    setSelected((previous) => {
      const next = new Set(previous)
      if (next.has(id)) next.delete(id)
      else if (next.size < remaining) next.add(id)
      return next
    })
  }

  async function importFiles(): Promise<void> {
    setBusy(true)
    setError(null)
    try {
      const imported = await window.caelo.importReferenceLibrary()
      if (!imported.length) return
      setItems((previous) => {
        const importedIds = new Set(imported.map((item) => item.id))
        return [...imported, ...previous.filter((item) => !importedIds.has(item.id))]
      })
      setSelected((previous) => {
        const next = new Set(previous)
        for (const item of imported) {
          if (next.size >= remaining) break
          next.add(item.id)
        }
        return next
      })
    } catch (reason) {
      setError(String((reason as Error).message || reason))
    } finally {
      setBusy(false)
    }
  }

  async function removeItem(id: string): Promise<void> {
    setBusy(true)
    setError(null)
    try {
      await window.caelo.deleteReferenceImage(id)
      setItems((previous) => previous.filter((item) => item.id !== id))
      setSelected((previous) => {
        const next = new Set(previous)
        next.delete(id)
        return next
      })
      setPreview((current) => (current && current.id === id ? null : current))
      setConfirmDelete(null)
    } catch (reason) {
      setError(String((reason as Error).message || reason))
    } finally {
      setBusy(false)
    }
  }

  async function addSelected(): Promise<void> {
    const chosen = items.filter((item) => selected.has(item.id)).slice(0, remaining)
    if (!chosen.length) return
    setBusy(true)
    setError(null)
    try {
      const staged = await Promise.all(chosen.map(async (item): Promise<StagedImage> => ({
        name: item.name,
        uri: await usableDataUri(item),
        libraryId: item.id,
        role: defaultRole
      })))
      onAdd(staged)
      onClose()
    } catch (reason) {
      setError(String((reason as Error).message || reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/65 p-5"
      role="dialog" aria-modal="true" aria-label="Reference image library" onMouseDown={onClose}>
      <section className="flex max-h-[88vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-border bg-bg shadow-2xl"
        onMouseDown={(event) => event.stopPropagation()}>
        <header className="flex items-center gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold">Reference image library</h2>
            <p className="text-xs text-muted">Import once, then reuse images without choosing them from disk again.</p>
          </div>
          <Button variant="outline" onClick={() => void importFiles()} disabled={busy}>
            <Upload size={16} /> Import images
          </Button>
          <IconButton label="Close library" icon={<X size={19} />} onClick={onClose} />
        </header>

        <div className="min-h-64 flex-1 overflow-y-auto p-5">
          {loading ? <p className="py-16 text-center text-sm text-muted">Loading library…</p> : null}
          {!loading && !items.length ? (
            <div className="flex flex-col items-center py-16 text-center text-muted">
              <ImagePlus size={34} className="mb-3" />
              <p className="text-sm font-medium text-fg">The reference library is empty</p>
              <p className="mt-1 text-xs">Use “Import images” to add the first reusable references.</p>
            </div>
          ) : null}
          {items.length ? (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-4">
              {items.map((item) => {
                const isCurrent = currentIds.has(item.id)
                const isSelected = selected.has(item.id)
                return (
                  <div key={item.id} className={cn('group relative overflow-hidden rounded-xl border bg-surface p-2',
                    isSelected ? 'border-accent ring-2 ring-accent/30' : 'border-border')}>
                    <button type="button" disabled={isCurrent} onClick={() => toggle(item.id)}
                      aria-label={`${isSelected ? 'Deselect' : 'Select'} ${item.name}`}
                      className="relative block h-32 w-full overflow-hidden rounded-lg bg-black/30 disabled:cursor-default">
                      <img src={item.uri} alt={item.name} loading="lazy"
                        className={cn('h-full w-full object-cover transition-opacity', isCurrent && 'opacity-45')} />
                      {isSelected || isCurrent ? <span className="absolute left-2 top-2 flex h-6 w-6 items-center justify-center rounded-full bg-accent text-accent-fg">
                        <Check size={14} /></span> : null}
                      {isCurrent ? <span className="absolute inset-x-2 bottom-2 rounded bg-black/70 px-2 py-1 text-[10px] text-white">Already added</span> : null}
                    </button>
                    <div className="absolute right-3 top-3 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                      <button type="button" aria-label={`Preview ${item.name}`} onClick={() => setPreview(item)}
                        className="flex h-7 w-7 items-center justify-center rounded-md bg-black/70 text-white hover:bg-black focus:opacity-100">
                        <Maximize2 size={14} />
                      </button>
                      <button type="button" aria-label={`Delete ${item.name}`} disabled={busy}
                        onClick={() => setConfirmDelete(item.id)}
                        className="flex h-7 w-7 items-center justify-center rounded-md bg-black/70 text-white hover:bg-error focus:opacity-100 disabled:opacity-50">
                        <Trash2 size={14} />
                      </button>
                    </div>
                    {confirmDelete === item.id ? (
                      <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 rounded-xl bg-bg/95 p-3 text-center">
                        <p className="text-xs text-fg">Delete this image from the library?</p>
                        <div className="flex gap-2">
                          <Button variant="ghost" size="sm" disabled={busy}
                            aria-label={`Cancel deleting ${item.name}`}
                            onClick={() => setConfirmDelete(null)}>Cancel</Button>
                          <Button variant="danger" size="sm" disabled={busy}
                            aria-label={`Confirm deleting ${item.name}`}
                            onClick={() => void removeItem(item.id)}>Delete</Button>
                        </div>
                      </div>
                    ) : null}
                    <p className="mt-2 truncate px-1 text-xs" title={item.name}>{item.name}</p>
                  </div>
                )
              })}
            </div>
          ) : null}
          {error ? <div className="mt-4 flex items-center gap-3 text-sm text-error">
            <span>{error}</span>
            {!busy ? <Button variant="outline" size="sm" onClick={() => setLoadAttempt((value) => value + 1)}>Retry</Button> : null}
          </div> : null}
        </div>

        <footer className="flex items-center gap-3 border-t border-border px-5 py-4">
          <p className="mr-auto text-xs text-muted">Selected {selected.size} of {remaining} available slots</p>
          <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={() => void addSelected()} disabled={busy || selected.size === 0}>
            {busy ? 'Working…' : `Add selected (${selected.size})`}
          </Button>
        </footer>
      </section>
      {preview ? <ImagePreview src={preview.uri} name={preview.name} onClose={() => setPreview(null)} /> : null}
    </div>
  )
}
