import { useCallback, useEffect, useRef, useState, type ChangeEvent, type DragEvent } from 'react'
import { Film, ImagePlus, Images, Maximize2 } from 'lucide-react'
import { type Conn, type HubArtifact } from '../lib/api'
import { cn } from '../lib/cn'
import { fileToDataUri } from '../lib/files'
import { compressImageIfNeeded } from '../lib/imageCompress'
import { useGenJobs } from '../lib/useGenJobs'
import { useHub, type StagedImage } from '../lib/hub'
import { useMediaCapabilities } from '../lib/useMediaCapabilities'
import { usePersistentState } from '../lib/usePersistentState'
import { forgetRecentArtifact, listRecentArtifacts } from '../lib/recentArtifacts'
import { ArtifactCard } from './ArtifactCard'
import { GenQueue } from './GenQueue'
import { ProviderModelPicker } from './ProviderModelPicker'
import { ReferenceLibrary } from './ReferenceLibrary'
import { ReferencePicker } from './ReferencePicker'
import { ImagePreview } from './ImagePreview'
import { Button } from './ui/Button'
import { Card } from './ui/Card'
import { Input } from './ui/Input'
import { Field, Page } from './ui/Page'
import { Select } from './ui/Select'
import { Slider } from './ui/Slider'
import { Textarea } from './ui/Textarea'

/** Strefa „upuść pliki tutaj" z podświetleniem. `dragleave` wpada też przy przejściu na
 *  dziecko strefy, więc gasimy podświetlenie dopiero, gdy kursor naprawdę opuścił
 *  kontener (relatedTarget poza nim) — inaczej ramka miga przy każdym elemencie w środku. */
function useDropZone(onFiles: (files: FileList | null) => void): {
  dragging: boolean
  zoneProps: {
    onDrop: (event: DragEvent<HTMLElement>) => void
    onDragOver: (event: DragEvent<HTMLElement>) => void
    onDragLeave: (event: DragEvent<HTMLElement>) => void
  }
} {
  const [dragging, setDragging] = useState(false)
  return {
    dragging,
    zoneProps: {
      onDragOver: (event) => {
        event.preventDefault()
        setDragging(true)
      },
      onDragLeave: (event) => {
        const next = event.relatedTarget
        if (next instanceof Node && event.currentTarget.contains(next)) return
        setDragging(false)
      },
      onDrop: (event) => {
        event.preventDefault()
        setDragging(false)
        onFiles(event.dataTransfer.files)
      }
    }
  }
}

type Mode = 'generate' | 'edit' | 'extend'
const MODES: { id: Mode; label: string }[] = [
  { id: 'generate', label: 'Generate' }, { id: 'edit', label: 'Edit' }, { id: 'extend', label: 'Extend' }
]

export function Video({ conn }: { conn: Conn }) {
  const [mode, setMode] = usePersistentState<Mode>('caelo.media.video.mode.v1', 'generate',
    (value): value is Mode => value === 'generate' || value === 'edit' || value === 'extend')
  const [prompt, setPrompt] = useState('')
  const [duration, setDuration] = usePersistentState('caelo.media.video.duration.v1', 6,
    (value): value is number => typeof value === 'number' && Number.isFinite(value) && value > 0)
  const [resolution, setResolution] = usePersistentState('caelo.media.video.resolution.v1', '720p',
    (value): value is string => typeof value === 'string')
  const [ratio, setRatio] = usePersistentState('caelo.media.video.aspect.v1', '16:9',
    (value): value is string => typeof value === 'string')
  const [lastImage, setLastImage] = useState<StagedImage | null>(null)
  const [audio, setAudio] = usePersistentState('caelo.media.video.audio.v1', true,
    (value): value is boolean => typeof value === 'boolean')
  const [seed, setSeed] = usePersistentState('caelo.media.video.seed.v1', '',
    (value): value is string => typeof value === 'string')
  const [negativePrompt, setNegativePrompt] = usePersistentState('caelo.media.video.negative-prompt.v1', '',
    (value): value is string => typeof value === 'string')
  const [results, setResults] = useState<HubArtifact[]>([])
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [framePreview, setFramePreview] = useState<StagedImage | null>(null)
  const { jobs, submitVideo, cancel, retry, clearFinished, dismiss, error: jobsError } = useGenJobs(conn)
  const { currentProjectId, pendingSend, setPendingSend, videoFrame: image, setVideoFrame: setImage,
    videoRefs: refs, setVideoRefs: setRefs, videoSource: source, setVideoSource: setSource,
    videoCommandMode, setVideoCommandMode, promptReuse, setPromptReuse } = useHub()
  const operation = mode === 'edit' ? 'edit' : mode === 'extend' ? 'extend' :
    refs.length ? 'reference_to_video' : image && lastImage ? 'first_last_frame' : image ? 'img2video' : 'text2video'
  const caps = useMediaCapabilities(conn, 'video', operation)
  const capability = caps.descriptor?.capabilities
  const maxRefs = capability?.max_reference_images ?? 3
  const needsSource = mode !== 'generate'
  const videoJobs = jobs.filter((job) => job.kind === 'video')
  const doneCount = videoJobs.filter((job) => job.status === 'done').length

  useEffect(() => {
    const resolutions = mode === 'extend' && capability?.extension_resolutions.length
      ? capability.extension_resolutions : capability?.resolutions ?? []
    if (resolutions.length && !resolutions.includes(resolution)) setResolution(resolutions[0])
    if (capability?.aspect_ratios.length && !capability.aspect_ratios.includes(ratio)) setRatio(capability.aspect_ratios[0])
    if (capability?.durations.length && !capability.durations.includes(duration)) setDuration(capability.durations[0])
    if (!capability?.durations.length && capability?.duration_min != null && duration < capability.duration_min) {
      setDuration(capability.duration_min)
    }
    if (!capability?.durations.length && capability?.duration_max != null && duration > capability.duration_max) {
      setDuration(capability.duration_max)
    }
    if (mode === 'extend' && capability?.extension_seconds) setDuration(capability.extension_seconds)
    if (refs.length > maxRefs) setRefs((items) => items.slice(0, maxRefs))
  }, [capability, duration, maxRefs, mode, ratio, refs.length, resolution, setDuration, setRatio, setRefs,
    setResolution])

  const refreshResults = useCallback((force = false) => {
    listRecentArtifacts(conn, 'video', currentProjectId ?? undefined, force)
      .then(setResults).catch(() => undefined)
  }, [conn, currentProjectId])
  const previousDoneCount = useRef(doneCount)
  useEffect(() => {
    const force = doneCount > previousDoneCount.current
    previousDoneCount.current = doneCount
    refreshResults(force)
  }, [refreshResults, doneCount])
  useEffect(() => {
    if (promptReuse?.target !== 'Video') return
    setPrompt(promptReuse.text); setPromptReuse(null)
  }, [promptReuse, setPromptReuse])
  useEffect(() => {
    if (!pendingSend || pendingSend.target !== 'Video') return
    if (pendingSend.block.block.type === 'image_url') {
      setImage({ name: pendingSend.label || 'frame', uri: pendingSend.block.block.image_url.url,
        artifactId: pendingSend.block.artifact_id })
      setMode('generate')
    }
    setPendingSend(null)
  }, [pendingSend, setImage, setMode, setPendingSend])
  useEffect(() => {
    if (!videoCommandMode) return
    setMode(videoCommandMode); setVideoCommandMode(null)
  }, [setMode, videoCommandMode, setVideoCommandMode])

  async function addMain(files: FileList | null): Promise<void> {
    const list = Array.from(files ?? [])
    if (needsSource) {
      const file = list.find((item) => item.type.startsWith('video/'))
      if (file) setSource({ name: file.name, uri: await fileToDataUri(file) })
    } else {
      const file = list.find((item) => item.type.startsWith('image/'))
      if (file) setImage({ name: file.name, uri: (await compressImageIfNeeded(file)).uri })
    }
  }
  async function addRefs(files: FileList | null): Promise<void> {
    const loaded = await Promise.all(Array.from(files ?? []).filter((file) => file.type.startsWith('image/'))
      .map(async (file) => ({ name: file.name, uri: (await compressImageIfNeeded(file)).uri, role: 'character' as const })))
    setRefs((items) => [...items, ...loaded].slice(0, maxRefs))
  }
  async function addLast(files: FileList | null): Promise<void> {
    const file = Array.from(files ?? []).find((item) => item.type.startsWith('image/'))
    if (file) setLastImage({ name: file.name, uri: (await compressImageIfNeeded(file)).uri })
  }
  function pick(handler: (files: FileList | null) => Promise<void>) {
    return (event: ChangeEvent<HTMLInputElement>) => { void handler(event.target.files); event.target.value = '' }
  }
  const mainZone = useDropZone((files) => void addMain(files))
  const refsZone = useDropZone((files) => void addRefs(files))

  async function run(): Promise<void> {
    if (!prompt.trim() || !caps.model || (needsSource && !source)) return
    const sources = [
      { id: source?.artifactId, role: 'source_video' }, { id: image?.artifactId, role: 'first_frame' },
      { id: lastImage?.artifactId, role: 'last_frame' },
      ...refs.map((item) => ({ id: item.artifactId, role: item.role ?? 'character' }))
    ].filter((item): item is { id: string; role: string } => !!item.id)
    await submitVideo({ provider: caps.provider, model: caps.model, op: operation,
      prompt: prompt.trim(), duration, resolution, aspect_ratio: ratio,
      image: mode === 'generate' ? image?.uri : undefined,
      last_image: operation === 'first_last_frame' ? lastImage?.uri : undefined,
      video: needsSource ? source?.uri : undefined,
      reference_images: operation === 'reference_to_video' ? refs.map((item) => item.uri) : undefined,
      reference_roles: operation === 'reference_to_video' ? refs.map((item) => item.role ?? 'character') : undefined,
      generate_audio: capability?.native_audio ? audio : undefined,
      seed: capability?.supports_seed && seed ? Number(seed) : undefined,
      negative_prompt: capability?.supports_negative_prompt && negativePrompt.trim() ? negativePrompt.trim() : undefined,
      source_artifact_ids: sources.map((item) => item.id),
      source_artifact_roles: sources.map((item) => item.role) })
  }

  const staged = needsSource ? source : image
  const durations = capability?.durations ?? []
  const resolutions = mode === 'extend' && capability?.extension_resolutions.length
    ? capability.extension_resolutions : capability?.resolutions ?? []
  return (
    <Page title="Video" subtitle="One adaptive workspace for xAI and Google video models.">
      <div className="mb-4 inline-flex rounded-lg border border-border bg-surface-2 p-0.5">
        {MODES.map((item) => <button key={item.id} onClick={() => setMode(item.id)} aria-pressed={mode === item.id}
          className={cn('rounded-md px-3.5 py-1.5 text-sm font-medium', mode === item.id ? 'bg-surface text-fg shadow-sm' : 'text-muted')}>
          {item.label}</button>)}
      </div>
      <div {...mainZone.zoneProps}
        className={cn('mb-4 rounded-xl border border-dashed bg-surface/40 p-4 transition-colors',
          mainZone.dragging ? 'border-accent bg-accent/5' : 'border-border-strong')}>
        <p className="mb-2 text-xs text-muted">{needsSource ? 'Source video' : 'Optional first frame'}</p>
        {staged ? <div className="flex items-center gap-3">
          {needsSource
            ? <video src={staged.uri} muted preload="metadata"
                className="h-20 w-28 shrink-0 rounded-md border border-border object-cover" />
            : <button type="button" aria-label={`Preview ${staged.name}`} onClick={() => setFramePreview(staged)}
                className="group relative h-20 w-28 shrink-0 overflow-hidden rounded-md border border-border">
                <img src={staged.uri} alt={staged.name} className="h-full w-full object-cover" />
                <span className="absolute inset-0 flex items-center justify-center bg-black/0 text-white opacity-0 transition-all group-hover:bg-black/35 group-hover:opacity-100 group-focus-visible:bg-black/35 group-focus-visible:opacity-100">
                  <Maximize2 size={18} />
                </span>
              </button>}
          <span className="min-w-0 flex-1 truncate text-sm" title={staged.name}>{staged.name}</span>
          <Button variant="ghost" size="sm" onClick={() => needsSource ? setSource(null) : setImage(null)}>Remove</Button>
        </div> :
          <p className="py-5 text-center text-sm text-muted">Drop a {needsSource ? 'video' : 'still image'} here.</p>}
      </div>
      {mode === 'generate' && maxRefs > 0 ? <Card {...refsZone.zoneProps}
        className={cn('mb-4 transition-colors', refsZone.dragging && 'border-accent bg-accent/5')}>
        <div className="mb-3 flex items-center justify-between gap-3"><p className="text-sm font-medium">Reference images · {refs.length}/{maxRefs}</p>
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" size="sm" icon={<Images size={14} />}
              onClick={() => setLibraryOpen(true)}>Library</Button>
            <label className="cursor-pointer text-xs text-accent"><ImagePlus size={14} className="mr-1 inline" />From disk
              <input hidden multiple type="file" accept="image/*" onChange={pick(addRefs)} /></label>
          </div></div>
        {refs.length ? <ReferenceLibrary items={refs} max={maxRefs} onChange={setRefs} /> :
          <p className="text-xs text-muted">Drop images here, or use Library / From disk. Assign each reference as a character, object, or style.</p>}
      </Card> : null}
      {framePreview ? <ImagePreview src={framePreview.uri} name={framePreview.name} onClose={() => setFramePreview(null)} /> : null}
      <Card>
        <Textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} className="mb-4" placeholder="Describe the shot and motion…" />
        {capability?.supports_negative_prompt ? <Textarea value={negativePrompt} onChange={(e) => setNegativePrompt(e.target.value)} rows={2} className="mb-4" placeholder="Negative prompt (optional)…" /> : null}
        <div className="flex flex-wrap items-end gap-3">
          <label className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg border border-border bg-surface-2 px-3 text-xs font-medium">
            {needsSource ? <Film size={14} /> : <ImagePlus size={14} />} {needsSource ? 'Choose video' : 'First frame'}
            <input hidden type="file" accept={needsSource ? 'video/*' : 'image/*'} onChange={pick(addMain)} />
          </label>
          {mode === 'generate' && capability?.first_last_frame && image ? <label className="inline-flex h-8 cursor-pointer items-center rounded-lg border border-border px-3 text-xs font-medium">
            {lastImage ? 'Replace end frame' : 'End frame'}<input hidden type="file" accept="image/*" onChange={pick(addLast)} /></label> : null}
          <ProviderModelPicker providers={caps.providers} provider={caps.provider} onProvider={caps.setProvider}
            models={caps.models} model={caps.model} onModel={caps.setModel} />
          {durations.length ? <Field label="Duration" className="w-24"><Select size="sm" value={duration} onChange={(e) => setDuration(Number(e.target.value))}>
            {durations.map((value) => <option key={value} value={value}>{value}s</option>)}</Select></Field> :
            capability?.duration_min != null && capability.duration_max != null ? <Field label={`Duration · ${duration}s`} className="w-40"><Slider min={capability.duration_min} max={capability.duration_max} value={duration} onChange={(e) => setDuration(Number(e.target.value))} /></Field> : null}
          {resolutions.length ? <Field label="Resolution" className="w-24"><Select size="sm" value={resolution} onChange={(e) => setResolution(e.target.value)}>
            {resolutions.map((value) => <option key={value}>{value}</option>)}</Select></Field> : null}
          {capability?.aspect_ratios.length ? <Field label="Aspect" className="w-24"><Select size="sm" value={ratio} onChange={(e) => setRatio(e.target.value)}>
            {capability.aspect_ratios.map((value) => <option key={value}>{value}</option>)}</Select></Field> : null}
          {capability?.supports_seed ? <Field label="Seed" className="w-28"><Input className="h-8" type="number" min="0" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="Random" /></Field> : null}
          {capability?.native_audio ? <label className="flex h-8 items-center gap-2 text-xs"><input type="checkbox" checked={audio} onChange={(e) => setAudio(e.target.checked)} /> Native audio</label> : null}
          <Button className="ml-auto" icon={<Film size={16} />} onClick={run} disabled={!prompt.trim() || !caps.model || (needsSource && !source)}>{mode === 'edit' ? 'Edit video' : mode === 'extend' ? 'Extend video' : 'Generate'}</Button>
        </div>
      </Card>
      {caps.error || jobsError ? <p className="mt-3 text-sm text-error">{caps.error || jobsError}</p> : null}
      <div className="mt-6"><GenQueue jobs={videoJobs.slice(0, 8)} onCancel={cancel} onRetry={retry}
        onClear={() => clearFinished('video')} onDismiss={dismiss} title="Jobs" /></div>
      {results.length ? <div className="mt-6"><h2 className="mb-2 text-sm font-semibold text-muted">Recent videos</h2>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-4">{results.map((art) =>
          <ArtifactCard key={art.id} conn={conn} art={art} mediaClassName="h-40 w-full rounded-lg"
            onDeleted={(id) => {
              forgetRecentArtifact(conn, id)
              setResults((items) => items.filter((x) => x.id !== id))
            }} />)}</div></div> : null}
      {libraryOpen ? <ReferencePicker conn={conn} max={maxRefs} current={refs} defaultRole="character"
        onAdd={(selected) => setRefs((current) => {
          const existing = new Set(current.map((item) => item.libraryId ?? item.artifactId).filter(Boolean))
          return [...current, ...selected.filter((item) => {
            const id = item.libraryId ?? item.artifactId
            return !id || !existing.has(id)
          })].slice(0, maxRefs)
        })} onClose={() => setLibraryOpen(false)} /> : null}
    </Page>
  )
}
