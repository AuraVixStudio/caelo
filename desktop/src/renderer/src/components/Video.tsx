import { useCallback, useEffect, useState, type ChangeEvent, type DragEvent } from 'react'
import { Film, ImagePlus, X } from 'lucide-react'
import { listArtifacts, type Conn, type HubArtifact } from '../lib/api'
import { useGenJobs } from '../lib/useGenJobs'
import { useHub } from '../lib/hub'
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
import { ArtifactCard } from './ArtifactCard'
import { GenQueue } from './GenQueue'
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

/**
 * Zakładka wideo (M11-F3). Wszystkie operacje (text→video, image→video, edit, extend)
 * to asynchroniczne zadania `GenJob` — jedna kolejka z postępem/anulowaniem/kosztem,
 * a wyniki lądują jako artefakty M9 w „Recent videos" i galerii. Kadr startowy i
 * źródłowe wideo trzymane w Hub (przeżywają zmianę zakładki + „Send video to…").
 */
export function Video({ conn }: { conn: Conn }) {
  const [mode, setMode] = useState<Mode>('generate')
  const [prompt, setPrompt] = useState('')
  const [duration, setDuration] = useState(VIDEO_DURATION_DEFAULT)
  const [extDuration, setExtDuration] = useState(EXTEND_DURATION_DEFAULT)
  const [resolution, setResolution] = useState('480p')
  const [ratio, setRatio] = useState('Original')
  const [models, setModels] = useState<string[]>([])
  const [model, setModel] = useState('')
  const [results, setResults] = useState<HubArtifact[]>([])
  const { models: modelsResp } = useModels(conn) // P2-2
  const { jobs, submitVideo, cancel, retry, clearFinished, dismiss, error: jobsError } =
    useGenJobs(conn)
  // Kadr startowy i źródłowe wideo trzymane w Hub (przeżywają zmianę zakładki —
  // panel jest leniwy; „Send video to…" z galerii też ładuje je tędy).
  const {
    currentProjectId,
    pendingSend,
    setPendingSend,
    videoFrame: image,
    setVideoFrame: setImage,
    videoSource: source,
    setVideoSource: setSource,
    videoCommandMode,
    setVideoCommandMode
  } = useHub()

  const videoJobs = jobs.filter((j) => j.kind === 'video')
  const doneCount = videoJobs.filter((j) => j.status === 'done').length

  useEffect(() => {
    if (!modelsResp) return
    setModels(modelsResp.video)
    setModel((prev) => prev || modelsResp.default_video)
  }, [modelsResp])

  const needsSource = mode === 'edit' || mode === 'extend'

  // Edit/Extend nie działają na modelach 1.5 (grok-imagine-video-1.5 obsługuje tylko
  // image→video → 400 na /videos/extensions); tylko bazowy grok-imagine-video.
  // Po wejściu w te tryby wybieramy pierwszy model bez "1.5". Ręczny wybór nie jest nadpisywany.
  useEffect(() => {
    if (needsSource && model.includes('1.5')) {
      const base = models.find((m) => !m.includes('1.5'))
      if (base) setModel(base)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, models])

  const refreshResults = useCallback(() => {
    listArtifacts(conn, { mode: 'video', project_id: currentProjectId ?? undefined, limit: 24 })
      .then((r) => setResults(r.artifacts))
      .catch(() => undefined)
  }, [conn, currentProjectId])

  // Odśwież galerię wideo, gdy przybędzie ukończonych zadań (job → artefakt M9).
  useEffect(() => {
    refreshResults()
  }, [refreshResults, doneCount])

  // M11: „Send to → Animate (Video)" — podnieś obraz jako kadr startowy (image→video).
  useEffect(() => {
    if (!pendingSend || pendingSend.target !== 'Video') return
    const block = pendingSend.block.block
    if (block.type === 'image_url') {
      setImage({ name: pendingSend.label || 'frame', uri: block.image_url.url })
      setMode('generate')
    }
    setPendingSend(null)
  }, [pendingSend, setPendingSend])

  // M11: „Send video to → Edit/Extend" z galerii — Hub załadował źródło (videoSource)
  // i komendę trybu; tu ją konsumujemy i czyścimy.
  useEffect(() => {
    if (!videoCommandMode) return
    setMode(videoCommandMode)
    setVideoCommandMode(null)
  }, [videoCommandMode, setVideoCommandMode])

  async function addFile(files: FileList | null): Promise<void> {
    const list = files ? Array.from(files) : []
    if (needsSource) {
      const f = list.find((x) => x.type.startsWith('video/'))
      if (f) setSource({ name: f.name, uri: await fileToDataUri(f) })
    } else {
      const f = list.find((x) => x.type.startsWith('image/'))
      if (f) setImage({ name: f.name, uri: await fileToDataUri(f) })
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

  async function run(): Promise<void> {
    if (!prompt.trim()) return
    if (needsSource && !source) return
    if (mode === 'edit') {
      await submitVideo({
        op: 'edit',
        prompt: prompt.trim(),
        duration,
        resolution,
        aspect_ratio: ratio,
        model: model || undefined,
        video: source!.uri
      })
    } else if (mode === 'extend') {
      await submitVideo({
        op: 'extend',
        prompt: prompt.trim(),
        duration: extDuration,
        resolution,
        aspect_ratio: ratio,
        model: model || undefined,
        video: source!.uri
      })
    } else {
      await submitVideo({
        op: image ? 'img2video' : 'text2video',
        prompt: prompt.trim(),
        duration,
        resolution,
        aspect_ratio: ratio,
        model: model || undefined,
        image: image?.uri
      })
    }
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
    <Page
      title="Video"
      subtitle="Generate, edit, or extend short videos with Caelo. Every job queues and lands in your gallery."
    >
      {/* Mode toggle */}
      <div className="mb-4 inline-flex rounded-lg border border-border bg-surface-2 p-0.5">
        {MODES.map((m) => (
          <button
            key={m.id}
            onClick={() => setMode(m.id)}
            aria-pressed={mode === m.id}
            className={cn(
              'rounded-md px-3.5 py-1.5 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent',
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
                src={source.uri}
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
              Drop a source video here, upload one, or send one here from a generated result.
            </span>
          )
        ) : image ? (
          <div className="relative h-28 w-28">
            <img
              src={image.uri}
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
                  aria-label="Duration in seconds"
                  aria-valuetext={`${duration} seconds`}
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
                aria-label="Seconds to add"
                aria-valuetext={`${extDuration} seconds`}
                onChange={(e) => setExtDuration(parseInt(e.target.value, 10))}
              />
            </Field>
          ) : null}

          <Button
            className="ml-auto"
            icon={<Film size={16} />}
            onClick={run}
            disabled={!prompt.trim() || (needsSource && !source)}
          >
            {submitLabel}
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

      {jobsError ? <p className="mt-4 text-sm text-error">{jobsError}</p> : null}

      <div className="mt-6">
        <GenQueue
          jobs={videoJobs.slice(0, 8)}
          onCancel={cancel}
          onRetry={retry}
          onClear={() => clearFinished('video')}
          onDismiss={dismiss}
          title="Jobs"
        />
      </div>

      {results.length ? (
        <div className="mt-6">
          <h2 className="mb-2 text-sm font-semibold text-muted">Recent videos</h2>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-4">
            {results.map((art) => (
              <ArtifactCard
                key={art.id}
                conn={conn}
                art={art}
                mediaClassName="h-40 w-full rounded-lg"
                onDeleted={(id) => setResults((prev) => prev.filter((a) => a.id !== id))}
              />
            ))}
          </div>
        </div>
      ) : null}
    </Page>
  )
}
