import { useEffect, useState, type ChangeEvent, type DragEvent } from 'react'
import { ImagePlus, Sparkles, Wand2, X } from 'lucide-react'
import { editImage, generateImage, type Conn, type MediaResult } from '../lib/api'
import { useModels } from '../lib/serverState'
import {
  ASPECT_RATIOS,
  EDIT_MAX_IMAGES,
  IMAGE_MODELS,
  IMAGE_VARIANTS,
  RESOLUTIONS
} from '../lib/constants'
import { fileToDataUri } from '../lib/files'
import { MediaGallery } from './MediaGallery'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'
import { Card } from './ui/Card'
import { Page, Field } from './ui/Page'
import { Select } from './ui/Select'
import { Textarea } from './ui/Textarea'

interface RefImage {
  name: string
  uri: string
}

/**
 * Połączona zakładka obrazu: generowanie i edycja w jednym widoku.
 * Bez obrazów referencyjnych → generowanie (/images/generate); po dodaniu
 * obrazów (do 3) panel przełącza się na edycję (/images/edit).
 */
export function Image({ conn }: { conn: Conn }) {
  const [prompt, setPrompt] = useState('')
  const [images, setImages] = useState<RefImage[]>([])
  const [models, setModels] = useState<string[]>(IMAGE_MODELS)
  const [model, setModel] = useState('')
  const [n, setN] = useState(1)
  const [ratio, setRatio] = useState('auto')
  const [resolution, setResolution] = useState('1k')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<MediaResult[]>([])
  const { models: modelsResp, error: modelsError } = useModels(conn) // P2-2

  const editing = images.length > 0

  useEffect(() => {
    if (modelsResp) {
      if (modelsResp.image?.length) setModels(modelsResp.image)
      setModel((prev) => prev || modelsResp.default_image || modelsResp.image?.[0] || IMAGE_MODELS[0])
    } else if (modelsError) {
      setModel((prev) => prev || IMAGE_MODELS[0])
    }
  }, [modelsResp, modelsError])

  async function addFiles(files: FileList | null): Promise<void> {
    if (!files) return
    const imgs = Array.from(files).filter((f) => f.type.startsWith('image/'))
    const loaded = await Promise.all(
      imgs.map(async (f) => ({ name: f.name, uri: await fileToDataUri(f) }))
    )
    setImages((prev) => [...prev, ...loaded].slice(0, EDIT_MAX_IMAGES))
  }

  function onPick(e: ChangeEvent<HTMLInputElement>): void {
    void addFiles(e.target.files)
    e.target.value = ''
  }

  function onDrop(e: DragEvent<HTMLDivElement>): void {
    e.preventDefault()
    void addFiles(e.dataTransfer.files)
  }

  function removeImage(idx: number): void {
    setImages((prev) => prev.filter((_, i) => i !== idx))
  }

  async function run(): Promise<void> {
    if (!prompt.trim() || busy) return
    setBusy(true)
    setError(null)
    try {
      const r = editing
        ? await editImage(conn, {
            prompt: prompt.trim(),
            images: images.map((i) => i.uri),
            n,
            aspect_ratio: ratio,
            resolution,
            model: model || undefined
          })
        : await generateImage(conn, {
            prompt: prompt.trim(),
            n,
            aspect_ratio: ratio,
            resolution,
            model: model || undefined
          })
      setResults(r.results)
    } catch (e) {
      setError(String((e as Error).message || e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Page
      title="Image"
      subtitle="Generate an image from a prompt, or attach reference images to edit, combine, or restyle."
      actions={
        <Badge tone={editing ? 'accent' : 'neutral'}>
          {editing ? `Edit · ${images.length}/${EDIT_MAX_IMAGES}` : 'Generate'}
        </Badge>
      }
    >
      <div
        onDrop={onDrop}
        onDragOver={(e) => e.preventDefault()}
        className="mb-4 flex min-h-28 items-center justify-center rounded-xl border border-dashed border-border-strong bg-surface/40 p-4"
      >
        {images.length === 0 ? (
          <span className="text-sm text-muted">
            Optional: drop up to {EDIT_MAX_IMAGES} reference images here to switch to edit mode.
          </span>
        ) : (
          <div className="flex flex-wrap gap-3">
            {images.map((img, i) => (
              <div className="relative h-28 w-28" key={i}>
                <img
                  src={img.uri}
                  alt={img.name}
                  className="h-full w-full rounded-lg border border-border object-cover"
                />
                <button
                  onClick={() => removeImage(i)}
                  className="absolute -right-2 -top-2 flex h-6 w-6 items-center justify-center rounded-full bg-error text-white shadow-sm"
                >
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <Card>
        <Textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder={
            editing
              ? 'Change the background to a snowy night…'
              : 'A photorealistic mountain lake at golden hour…'
          }
          rows={3}
          className="mb-4"
        />
        <div className="flex flex-wrap items-end gap-3">
          <label className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg border border-border bg-surface-2 px-3 text-xs font-medium transition-colors hover:border-border-strong">
            <ImagePlus size={14} /> Add images
            <input type="file" accept="image/*" multiple onChange={onPick} hidden />
          </label>
          <Field label="Model" className="w-52">
            <Select size="sm" value={model} onChange={(e) => setModel(e.target.value)}>
              {(models.length ? models : model ? [model] : []).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Variants" className="w-24">
            <Select size="sm" value={String(n)} onChange={(e) => setN(parseInt(e.target.value, 10))}>
              {IMAGE_VARIANTS.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Aspect" className="w-32">
            <Select size="sm" value={ratio} onChange={(e) => setRatio(e.target.value)}>
              {ASPECT_RATIOS.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Resolution" className="w-32">
            <Select size="sm" value={resolution} onChange={(e) => setResolution(e.target.value)}>
              {RESOLUTIONS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </Select>
          </Field>
          <Button
            className="ml-auto"
            icon={editing ? <Wand2 size={16} /> : <Sparkles size={16} />}
            onClick={run}
            disabled={busy || !prompt.trim()}
          >
            {busy ? (editing ? 'Editing…' : 'Generating…') : editing ? 'Edit' : 'Generate'}
          </Button>
        </div>
      </Card>

      {error ? <p className="mt-4 text-sm text-error">{error}</p> : null}
      <div className="mt-6">
        <MediaGallery results={results} />
      </div>
    </Page>
  )
}
