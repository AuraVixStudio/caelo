import { useCallback, useEffect, useRef, useState, type ChangeEvent, type DragEvent } from 'react'
import { Film, ImagePlus, Images, Maximize2, X } from 'lucide-react'
import { type Conn, type HubArtifact } from '../lib/api'
import { cn } from '../lib/cn'
import { fileToDataUri } from '../lib/files'
import { compressImageIfNeeded } from '../lib/imageCompress'
import { useGenJobs } from '../lib/useGenJobs'
import { useHub, type StagedImage } from '../lib/hub'
import { formatKeyframeTime, keyframeTimes, keyframesValid, nextKeyframeTime } from '../lib/videoKeyframes'
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
  const [audio, setAudio] = usePersistentState('caelo.media.video.audio.v1', true,
    (value): value is boolean => typeof value === 'boolean')
  const [seed, setSeed] = usePersistentState('caelo.media.video.seed.v1', '',
    (value): value is string => typeof value === 'string')
  const [negativePrompt, setNegativePrompt] = usePersistentState('caelo.media.video.negative-prompt.v1', '',
    (value): value is string => typeof value === 'string')
  // Głosy presetowe (xAI 1.5, `reference_audios`) — kolejność wyboru = <AUDIO_0>, <AUDIO_1>…
  const [voices, setVoices] = usePersistentState<string[]>('caelo.media.video.voices.v1', [],
    (value): value is string[] => Array.isArray(value) && value.every((item) => typeof item === 'string'))
  const [results, setResults] = useState<HubArtifact[]>([])
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [framePreview, setFramePreview] = useState<StagedImage | null>(null)
  const { jobs, submitVideo, cancel, retry, clearFinished, dismiss, error: jobsError } = useGenJobs(conn)
  const { currentProjectId, pendingSend, setPendingSend, videoFrame: image, setVideoFrame: setImage,
    videoRefs: refs, setVideoRefs: setRefs, videoSource: source, setVideoSource: setSource,
    videoLastFrame: lastImage, setVideoLastFrame: setLastImage, videoKeyframes: keyframes,
    setVideoKeyframes: setKeyframes,
    videoCommandMode, setVideoCommandMode, promptReuse, setPromptReuse } = useHub()
  const operation = mode === 'edit' ? 'edit' : mode === 'extend' ? 'extend' :
    refs.length || voices.length ? 'reference_to_video' : image && lastImage ? 'first_last_frame' :
      image ? 'img2video' : 'text2video'
  const caps = useMediaCapabilities(conn, 'video', operation)
  const capability = caps.descriptor?.capabilities
  const maxRefs = capability?.max_reference_images ?? 3
  const maxVoices = capability?.max_reference_audios ?? 0
  const voiceRoster = capability?.voices ?? []
  const maxKeyframes = capability?.max_keyframes ?? 0
  const usesRefs = mode === 'generate' && refs.length > 0
  // Referencje ograniczają klip (xAI: ≤720p, bazowy ≤10 s) — pokaż tylko dozwolone wartości.
  const durationMax = usesRefs && capability?.reference_duration_max != null
    ? Math.min(capability.reference_duration_max, capability.duration_max ?? Infinity) : capability?.duration_max
  // Bazowy grok-imagine-video nie łączy kadru startowego z referencjami — trzeba wybrać jedno.
  const frameRefConflict = usesRefs && !!image && capability?.reference_with_first_frame === false
  // xAI numeruje tagi od <IMAGE_0>; wysłany kadr startowy zajmuje <IMAGE_0>.
  const refTagStart = image && !frameRefConflict ? 1 : 0
  // Image→video: proporcje wynikają z kadru startowego, a `aspect_ratio` jest ignorowane —
  // pokaż „Auto" i nie wysyłaj pola (wybór usera zostaje na czas bez kadru).
  const autoAspect = mode === 'generate' && !!image && !frameRefConflict
    && !!capability?.image_to_video_auto_aspect
  const needsSource = mode !== 'generate'
  const videoJobs = jobs.filter((job) => job.kind === 'video')
  const doneCount = videoJobs.filter((job) => job.status === 'done').length

  useEffect(() => {
    const base = mode === 'extend' && capability?.extension_resolutions.length
      ? capability.extension_resolutions : capability?.resolutions ?? []
    const resolutions = usesRefs && capability?.reference_resolutions?.length
      ? base.filter((value) => capability.reference_resolutions.includes(value)) : base
    if (resolutions.length && !resolutions.includes(resolution)) setResolution(resolutions[0])
    if (capability?.aspect_ratios.length && !capability.aspect_ratios.includes(ratio)) setRatio(capability.aspect_ratios[0])
    if (capability?.durations.length && !capability.durations.includes(duration)) setDuration(capability.durations[0])
    if (!capability?.durations.length && capability?.duration_min != null && duration < capability.duration_min) {
      setDuration(capability.duration_min)
    }
    if (!capability?.durations.length && durationMax != null && duration > durationMax) {
      setDuration(durationMax)
    }
    if (mode === 'extend' && capability?.extension_seconds) setDuration(capability.extension_seconds)
    if (refs.length > maxRefs) setRefs((items) => items.slice(0, maxRefs))
    if (voices.length > maxVoices) setVoices((items) => items.slice(0, maxVoices))
    // Skrócony klip wypycha klatki poza wnętrze — przenieś je na najbliższy wolny punkt.
    if (keyframes.length && !keyframesValid(keyframes.map((item) => item.timestamp), duration)) {
      setKeyframes((items) => items.reduce<typeof items>((acc, item) => {
        const fits = keyframesValid([...acc.map((x) => x.timestamp), item.timestamp], duration)
        const timestamp = fits ? item.timestamp : nextKeyframeTime(acc.map((x) => x.timestamp), duration)
        return timestamp == null ? acc : [...acc, { ...item, timestamp }]
      }, []))
    }
  }, [capability, duration, durationMax, keyframes, maxRefs, maxVoices, mode, ratio, refs.length, resolution,
    setDuration, setKeyframes, setRatio, setRefs, setResolution, setVoices, usesRefs, voices.length])

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
  async function addKeyframes(files: FileList | null): Promise<void> {
    const loaded = await Promise.all(Array.from(files ?? []).filter((file) => file.type.startsWith('image/'))
      .map(async (file) => ({ name: file.name, uri: (await compressImageIfNeeded(file)).uri })))
    setKeyframes((items) => loaded.reduce((acc, item) => {
      if (acc.length >= maxKeyframes) return acc
      const timestamp = nextKeyframeTime(acc.map((x) => x.timestamp), duration)
      return timestamp == null ? acc : [...acc, { ...item, timestamp }]
    }, items))
  }
  function toggleVoice(voice: string): void {
    setVoices((items) => items.includes(voice) ? items.filter((item) => item !== voice)
      : items.length < maxVoices ? [...items, voice] : items)
  }
  function pick(handler: (files: FileList | null) => Promise<void>) {
    return (event: ChangeEvent<HTMLInputElement>) => { void handler(event.target.files); event.target.value = '' }
  }
  const mainZone = useDropZone((files) => void addMain(files))
  const refsZone = useDropZone((files) => void addRefs(files))
  const keyframesZone = useDropZone((files) => void addKeyframes(files))

  const sendKeyframes = mode === 'generate' && maxKeyframes > 0 && keyframes.length > 0
  const sendVoices = mode === 'generate' && maxVoices > 0 && voices.length > 0
  async function run(): Promise<void> {
    if (!prompt.trim() || !caps.model || (needsSource && !source) || frameRefConflict) return
    const sources = [
      { id: source?.artifactId, role: 'source_video' }, { id: image?.artifactId, role: 'first_frame' },
      { id: lastImage?.artifactId, role: 'last_frame' },
      ...refs.map((item) => ({ id: item.artifactId, role: item.role ?? 'character' }))
    ].filter((item): item is { id: string; role: string } => !!item.id)
    await submitVideo({ provider: caps.provider, model: caps.model, op: operation,
      prompt: prompt.trim(), duration, resolution, aspect_ratio: autoAspect ? 'Original' : ratio,
      image: mode === 'generate' ? image?.uri : undefined,
      last_image: operation === 'first_last_frame' ? lastImage?.uri : undefined,
      video: needsSource ? source?.uri : undefined,
      reference_images: operation === 'reference_to_video' ? refs.map((item) => item.uri) : undefined,
      reference_roles: operation === 'reference_to_video' ? refs.map((item) => item.role ?? 'character') : undefined,
      reference_audios: sendVoices ? voices : undefined,
      keyframe_images: sendKeyframes ? keyframes.map((item) => item.uri) : undefined,
      keyframe_times: sendKeyframes ? keyframes.map((item) => item.timestamp) : undefined,
      generate_audio: capability?.native_audio ? audio : undefined,
      seed: capability?.supports_seed && seed ? Number(seed) : undefined,
      negative_prompt: capability?.supports_negative_prompt && negativePrompt.trim() ? negativePrompt.trim() : undefined,
      source_artifact_ids: sources.map((item) => item.id),
      source_artifact_roles: sources.map((item) => item.role) })
  }

  const staged = needsSource ? source : image
  const durations = capability?.durations ?? []
  const baseResolutions = mode === 'extend' && capability?.extension_resolutions.length
    ? capability.extension_resolutions : capability?.resolutions ?? []
  const resolutions = usesRefs && capability?.reference_resolutions?.length
    ? baseResolutions.filter((value) => capability.reference_resolutions.includes(value)) : baseResolutions
  const keyframeGrid = keyframeTimes(duration)
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
        {refs.length ? <>
          <ReferenceLibrary items={refs} max={maxRefs} onChange={setRefs} tagStart={refTagStart} />
          <p className="mt-2 text-xs text-muted">Refer to them in the prompt by their tags. Clips with references are limited to {capability?.reference_resolutions?.at(-1) ?? '720p'}{capability?.reference_duration_max ? ` and ${capability.reference_duration_max}s` : ''}.</p>
          {frameRefConflict ? <p className="mt-2 text-xs text-error">This model can't combine a first frame with reference images. Remove one of them, or switch to grok-imagine-video-1.5.</p> : null}
        </> :
          <p className="text-xs text-muted">Drop images here, or use Library / From disk. Assign each reference as a character, object, or style.</p>}
      </Card> : null}
      {mode === 'generate' && maxVoices > 0 && voiceRoster.length ? <Card className="mb-4">
        <div className="mb-2 flex items-center justify-between gap-3">
          <p className="text-sm font-medium">Voices · {voices.length}/{maxVoices}</p>
          {voices.length ? <Button type="button" variant="ghost" size="sm" onClick={() => setVoices([])}>Clear</Button> : null}
        </div>
        <div className="flex flex-wrap gap-2">{voiceRoster.map((voice) => {
          const index = voices.indexOf(voice)
          const selected = index >= 0
          return <button key={voice} type="button" aria-pressed={selected} onClick={() => toggleVoice(voice)}
            disabled={!selected && voices.length >= maxVoices}
            className={cn('rounded-full border px-3 py-1 text-xs font-medium capitalize transition-colors disabled:opacity-40',
              selected ? 'border-accent bg-accent/10 text-fg' : 'border-border text-muted')}>
            {voice}{selected ? <span className="ml-1.5 font-mono normal-case text-accent">&lt;AUDIO_{index}&gt;</span> : null}
          </button>
        })}</div>
        <p className="mt-2 text-xs text-muted">Give up to {maxVoices} speaking characters a preset voice with lip-synced speech. Refer to each by its tag in the prompt.</p>
      </Card> : null}
      {mode === 'generate' && maxKeyframes > 0 ? <Card {...keyframesZone.zoneProps}
        className={cn('mb-4 transition-colors', keyframesZone.dragging && 'border-accent bg-accent/5')}>
        <div className="mb-3 flex items-center justify-between gap-3">
          <p className="text-sm font-medium">Keyframes · {keyframes.length}/{maxKeyframes}</p>
          {keyframes.length < maxKeyframes ? <label className="cursor-pointer text-xs text-accent"><ImagePlus size={14} className="mr-1 inline" />From disk
            <input hidden multiple type="file" accept="image/*" onChange={pick(addKeyframes)} /></label> : null}
        </div>
        {keyframes.length ? <div className="flex flex-wrap gap-3">{keyframes.map((item, index) =>
          <div key={`${item.name}-${index}`} className="w-28 rounded-lg border border-border bg-surface p-1.5">
            <div className="relative h-20">
              <img src={item.uri} alt={item.name} className="h-full w-full rounded-md object-cover" />
              <button type="button" aria-label={`Remove ${item.name}`} onClick={() => setKeyframes((items) => items.filter((_, i) => i !== index))}
                className="absolute -right-2 -top-2 flex h-6 w-6 items-center justify-center rounded-full bg-error text-white">
                <X size={12} />
              </button>
            </div>
            <Select size="sm" aria-label={`Time of ${item.name}`} className="mt-1 w-full" value={String(Math.round(item.timestamp * 3))}
              onChange={(e) => setKeyframes((items) => items.map((x, i) => i === index ? { ...x, timestamp: Number(e.target.value) / 3 } : x))}>
              {keyframeGrid.map((t) => {
                const q = Math.round(t * 3)
                const taken = keyframes.some((x, i) => i !== index && Math.round(x.timestamp * 3) === q)
                return <option key={q} value={q} disabled={taken}>{formatKeyframeTime(t)}</option>
              })}
            </Select>
          </div>)}</div> :
          <p className="text-xs text-muted">Drop up to {maxKeyframes} stills to pin them at chosen moments of the clip; the model fills in the motion between them.</p>}
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
            capability?.duration_min != null && durationMax != null ? <Field label={`Duration · ${duration}s`} className="w-40"><Slider min={capability.duration_min} max={durationMax} value={duration} onChange={(e) => setDuration(Number(e.target.value))} /></Field> : null}
          {resolutions.length ? <Field label="Resolution" className="w-24"><Select size="sm" value={resolution} onChange={(e) => setResolution(e.target.value)}>
            {resolutions.map((value) => <option key={value}>{value}</option>)}</Select></Field> : null}
          {autoAspect ? <Field label="Aspect" className="w-40"><Select size="sm" value="auto" disabled
            title="The clip matches the first frame's aspect ratio.">
            <option value="auto">Auto · first frame</option></Select></Field> :
            capability?.aspect_ratios.length ? <Field label="Aspect" className="w-24"><Select size="sm" value={ratio} onChange={(e) => setRatio(e.target.value)}>
            {capability.aspect_ratios.map((value) => <option key={value}>{value}</option>)}</Select></Field> : null}
          {capability?.supports_seed ? <Field label="Seed" className="w-28"><Input className="h-8" type="number" min="0" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="Random" /></Field> : null}
          {capability?.native_audio ? <label className="flex h-8 items-center gap-2 text-xs"><input type="checkbox" checked={audio} onChange={(e) => setAudio(e.target.checked)} /> Native audio</label> : null}
          <Button className="ml-auto" icon={<Film size={16} />} onClick={run} disabled={!prompt.trim() || !caps.model || (needsSource && !source) || frameRefConflict}>{mode === 'edit' ? 'Edit video' : mode === 'extend' ? 'Extend video' : 'Generate'}</Button>
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
