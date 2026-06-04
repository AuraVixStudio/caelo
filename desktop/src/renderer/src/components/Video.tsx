import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from 'react'
import { Film, ImagePlus, Wand2, X } from 'lucide-react'
import {
  createVideoJob,
  editVideoJob,
  extendVideoJob,
  pollVideoJob,
  type Conn,
  type VideoStatus
} from '../lib/api'
import { useModels } from '../lib/serverState'
import {
  EXTEND_DURATION_DEFAULT,
  EXTEND_DURATION_MAX,
  EXTEND_DURATION_MIN,
  VIDEO_DURATION_DEFAULT,
  VIDEO_DURATION_MAX,
  VIDEO_DURATION_MIN,
  VIDEO_RATIOS,
  VIDEO_RESOLUTIONS
} from '../lib/constants'
import { cn } from '../lib/cn'
import { fileToDataUri } from '../lib/files'
import { Button } from './ui/Button'
import { Card } from './ui/Card'
import { Page, Field } from './ui/Page'
import { Select } from './ui/Select'
import { Slider } from './ui/Slider'
import { Textarea } from './ui/Textarea'

type Mode = 'generate' | 'edit' | 'extend'

const MODES: { id: Mode; label: string }[] = [
  { id: 'generate', label: 'Generate' },
  { id: 'edit', label: 'Edit' },
  { id: 'extend', label: 'Extend' }
]

interface MediaRef {
  name: string
  value: string // data-URI (upload) lub https URL (ponowne użycie wyniku)
}

export function Video({ conn }: { conn: Conn }) {
  const [mode, setMode] = useState<Mode>('generate')
  const [prompt, setPrompt] = useState('')
  const [image, setImage] = useState<MediaRef | null>(null) // kadr startowy (generate)
  const [source, setSource] = useState<MediaRef | null>(null) // źródłowe wideo (edit/extend)
  const [duration, setDuration] = useState(VIDEO_DURATION_DEFAULT) // generate 1-15
  const [extDuration, setExtDuration] = useState(EXTEND_DURATION_DEFAULT) // extend 1-10
  const [resolution, setResolution] = useState('480p')
  const [ratio, setRatio] = useState('Original')
  const [models, setModels] = useState<string[]>([])
  const [model, setModel] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [video, setVideo] = useState<VideoStatus | null>(null)
  const aliveRef = useRef(true)
  const { models: modelsResp } = useModels(conn) // P2-2: współdzielony cache /models

  useEffect(() => {
    aliveRef.current = true
    return () => {
      aliveRef.current = false
    }
  }, [])

  useEffect(() => {
    if (!modelsResp) return
    setModels(modelsResp.video)
    setModel((prev) => prev || modelsResp.default_video)
  }, [modelsResp])

  const needsSource = mode === 'edit' || mode === 'extend'

  // Edit/Extend nie działają na modelu "preview" (np. grok-imagine-video-1.5-preview
  // zwraca 400 na /videos/extensions). Po wejściu w te tryby wybieramy pierwszy
  // model bez "preview" (zwykle grok-imagine-video). Ręczny wybór użytkownika
  // (zmiana modelu w tym samym trybie) nie jest nadpisywany.
  useEffect(() => {
    if (needsSource && model.includes('preview')) {
      const base = models.find((m) => !m.includes('preview'))
      if (base) setModel(base)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, models])

  async function addFile(files: FileList | null): Promise<void> {
    const list = files ? Array.from(files) : []
    if (needsSource) {
      const f = list.find((x) => x.type.startsWith('video/'))
      if (f) setSource({ name: f.name, value: await fileToDataUri(f) })
    } else {
      const f = list.find((x) => x.type.startsWith('image/'))
      if (f) setImage({ name: f.name, value: await fileToDataUri(f) })
    }
  }

  function onPick(e: ChangeEvent<HTMLInputElement>): void {
    void addFile(e.target.files)
    e.target.value = ''
  }

  function onDrop(e: DragEvent<HTMLDivElement>): void {
    e.preventDefault()
    void addFile(e.dataTransfer.files)
  }

  function poll(id: string): void {
    const tick = async (): Promise<void> => {
      if (!aliveRef.current) return
      try {
        const st = await pollVideoJob(conn, id)
        if (st.status === 'done') {
          setVideo(st)
          setStatus('Done')
          setBusy(false)
          return
        }
        if (st.status === 'failed' || st.status === 'expired') {
          setError('Video job failed or expired.')
          setBusy(false)
          return
        }
        setTimeout(tick, 5000)
      } catch (e) {
        setError(String((e as Error).message || e))
        setBusy(false)
      }
    }
    setTimeout(tick, 4000)
  }

  async function run(): Promise<void> {
    if (!prompt.trim() || busy) return
    if (needsSource && !source) return
    setBusy(true)
    setError(null)
    setVideo(null)
    setStatus('Submitting job…')
    try {
      let requestId: string
      if (mode === 'edit') {
        requestId = (
          await editVideoJob(conn, {
            prompt: prompt.trim(),
            video: source!.value,
            model: model || undefined
          })
        ).request_id
      } else if (mode === 'extend') {
        requestId = (
          await extendVideoJob(conn, {
            prompt: prompt.trim(),
            video: source!.value,
            duration: extDuration,
            model: model || undefined
          })
        ).request_id
      } else {
        requestId = (
          await createVideoJob(conn, {
            prompt: prompt.trim(),
            duration,
            resolution,
            aspect_ratio: ratio,
            model: model || undefined,
            image: image?.value
          })
        ).request_id
      }
      setStatus('Rendering… (can take up to ~2 min)')
      poll(requestId)
    } catch (e) {
      setError(String((e as Error).message || e))
      setBusy(false)
    }
  }

  const videoUrl = video?.video?.url
  const localPath = video?.local_path

  // Wczytaj gotowy wynik jako źródło do edycji/przedłużenia (zdalny URL xAI).
  function reuse(nextMode: Mode): void {
    if (!videoUrl) return
    setSource({ name: 'Generated video', value: videoUrl })
    setMode(nextMode)
    setVideo(null)
    setStatus('')
    setError(null)
  }

  const submitLabel =
    mode === 'edit' ? 'Edit video' : mode === 'extend' ? 'Extend video' : 'Generate'
  const placeholder =
    mode === 'edit'
      ? 'Give the woman a silver necklace…'
      : mode === 'extend'
        ? 'The shot pans to an over-the-shoulder perspective…'
        : image
          ? 'Describe the motion — e.g. slow zoom-in, camera pans left…'
          : 'A drone shot flying over a neon city at night…'

  return (
    <Page title="Video" subtitle="Generate, edit, or extend short videos with Grok.">
      {/* Mode toggle */}
      <div className="mb-4 inline-flex rounded-lg border border-border bg-surface-2 p-0.5">
        {MODES.map((m) => (
          <button
            key={m.id}
            onClick={() => setMode(m.id)}
            className={cn(
              'rounded-md px-3.5 py-1.5 text-sm font-medium transition-colors',
              mode === m.id ? 'bg-surface text-fg shadow-sm' : 'text-muted hover:text-fg'
            )}
          >
            {m.label}
          </button>
        ))}
      </div>

      {/* Source: still image (generate) or source video (edit/extend) */}
      <div
        onDrop={onDrop}
        onDragOver={(e) => e.preventDefault()}
        className="mb-4 flex min-h-28 items-center justify-center rounded-xl border border-dashed border-border-strong bg-surface/40 p-4"
      >
        {needsSource ? (
          source ? (
            <div className="relative w-full max-w-md">
              <video
                src={source.value}
                controls
                className="w-full rounded-lg border border-border bg-black"
              />
              <button
                onClick={() => setSource(null)}
                className="absolute -right-2 -top-2 flex h-6 w-6 items-center justify-center rounded-full bg-error text-white shadow-sm"
              >
                <X size={12} />
              </button>
              <p className="mt-1 truncate text-xs text-muted">{source.name}</p>
            </div>
          ) : (
            <span className="text-sm text-muted">
              Drop a source video here, upload one, or generate a video first and reuse it.
            </span>
          )
        ) : image ? (
          <div className="relative h-28 w-28">
            <img
              src={image.value}
              alt={image.name}
              className="h-full w-full rounded-lg border border-border object-cover"
            />
            <button
              onClick={() => setImage(null)}
              className="absolute -right-2 -top-2 flex h-6 w-6 items-center justify-center rounded-full bg-error text-white shadow-sm"
            >
              <X size={12} />
            </button>
          </div>
        ) : (
          <span className="text-sm text-muted">
            Optional: drop a still image here to animate it (image-to-video).
          </span>
        )}
      </div>

      <Card>
        <Textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder={placeholder}
          rows={3}
          className="mb-4"
        />
        <div className="flex flex-wrap items-end gap-3">
          <label className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg border border-border bg-surface-2 px-3 text-xs font-medium transition-colors hover:border-border-strong">
            {needsSource ? <Film size={14} /> : <ImagePlus size={14} />}
            {needsSource
              ? source
                ? 'Replace video'
                : 'Upload video'
              : image
                ? 'Replace frame'
                : 'First frame'}
            <input
              type="file"
              accept={needsSource ? 'video/*' : 'image/*'}
              onChange={onPick}
              hidden
            />
          </label>
          <Field label="Model" className="w-44">
            <Select size="sm" value={model} onChange={(e) => setModel(e.target.value)}>
              {(models.length ? models : model ? [model] : []).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </Select>
          </Field>

          {mode === 'generate' ? (
            <>
              <Field label={`Duration · ${duration}s`} className="w-44">
                <Slider
                  min={VIDEO_DURATION_MIN}
                  max={VIDEO_DURATION_MAX}
                  step={1}
                  value={duration}
                  onChange={(e) => setDuration(parseInt(e.target.value, 10))}
                />
              </Field>
              <Field label="Resolution" className="w-28">
                <Select size="sm" value={resolution} onChange={(e) => setResolution(e.target.value)}>
                  {VIDEO_RESOLUTIONS.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Aspect" className="w-32">
                <Select size="sm" value={ratio} onChange={(e) => setRatio(e.target.value)}>
                  {VIDEO_RATIOS.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </Select>
              </Field>
            </>
          ) : null}

          {mode === 'extend' ? (
            <Field label={`Add · ${extDuration}s`} className="w-44">
              <Slider
                min={EXTEND_DURATION_MIN}
                max={EXTEND_DURATION_MAX}
                step={1}
                value={extDuration}
                onChange={(e) => setExtDuration(parseInt(e.target.value, 10))}
              />
            </Field>
          ) : null}

          <Button
            className="ml-auto"
            icon={<Film size={16} />}
            onClick={run}
            disabled={busy || !prompt.trim() || (needsSource && !source)}
          >
            {busy ? 'Working…' : submitLabel}
          </Button>
        </div>
        {needsSource ? (
          <p className="mt-3 text-xs text-muted">
            {mode === 'edit'
              ? 'Editing keeps the original length and framing — only the prompt-described changes are applied. '
              : ''}
            Needs a model that supports {mode === 'edit' ? 'edits' : 'extensions'} (e.g.
            grok-imagine-video) — the 1.5 preview model may not yet.
          </p>
        ) : null}
      </Card>

      {busy ? <p className="mt-4 text-sm text-muted">{status}</p> : null}
      {error ? <p className="mt-4 text-sm text-error">{error}</p> : null}

      {videoUrl ? (
        <div className="mt-6 max-w-2xl">
          <video
            src={videoUrl}
            controls
            className="w-full rounded-xl border border-border bg-black"
          />
          <div className="mt-3 flex flex-wrap gap-2">
            {localPath ? (
              <Button variant="outline" size="sm" onClick={() => window.grok.openPath(localPath)}>
                Open file
              </Button>
            ) : null}
            <Button
              variant="outline"
              size="sm"
              icon={<Wand2 size={14} />}
              onClick={() => reuse('edit')}
            >
              Edit this video
            </Button>
            <Button
              variant="outline"
              size="sm"
              icon={<Film size={14} />}
              onClick={() => reuse('extend')}
            >
              Extend this video
            </Button>
          </div>
        </div>
      ) : null}
    </Page>
  )
}
