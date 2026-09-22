import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type DragEvent } from 'react'
import { ImagePlus, Images, Sparkles } from 'lucide-react'
import { getArtifactInputBlock, type Conn, type HubArtifact } from '../lib/api'
import { compressImageIfNeeded } from '../lib/imageCompress'
import { useGenJobs } from '../lib/useGenJobs'
import { useHub } from '../lib/hub'
import { useMediaCapabilities } from '../lib/useMediaCapabilities'
import { usePersistentState } from '../lib/usePersistentState'
import { forgetRecentArtifact, listRecentArtifacts } from '../lib/recentArtifacts'
import {
  defaultReferenceRole,
  imageReferenceRoleOptions,
  normalizeReferenceRoles
} from '../lib/referenceRoles'
import { ArtifactCard } from './ArtifactCard'
import { GenQueue } from './GenQueue'
import { ProviderModelPicker } from './ProviderModelPicker'
import { ReferenceLibrary } from './ReferenceLibrary'
import { ReferencePicker } from './ReferencePicker'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'
import { Card } from './ui/Card'
import { Field, Page } from './ui/Page'
import { Input } from './ui/Input'
import { Select } from './ui/Select'
import { Textarea } from './ui/Textarea'

export function Image({ conn }: { conn: Conn }) {
  const [prompt, setPrompt] = useState('')
  const [n, setN] = usePersistentState('caelo.media.image.count.v1', 1,
    (value): value is number => typeof value === 'number' && [1, 2, 3, 4].includes(value))
  const [ratio, setRatio] = usePersistentState('caelo.media.image.aspect.v1', 'auto',
    (value): value is string => typeof value === 'string')
  const [resolution, setResolution] = usePersistentState('caelo.media.image.resolution.v1', '1k',
    (value): value is string => typeof value === 'string')
  const [quality, setQuality] = usePersistentState<'low' | 'medium' | 'high' | 'auto'>(
    'caelo.media.image.quality.v1', 'medium',
    (value): value is 'low' | 'medium' | 'high' | 'auto' =>
      value === 'low' || value === 'medium' || value === 'high' || value === 'auto')
  const [outputFormat, setOutputFormat] = usePersistentState<'png' | 'jpeg' | 'webp'>(
    'caelo.media.image.format.v1', 'png',
    (value): value is 'png' | 'jpeg' | 'webp' => value === 'png' || value === 'jpeg' || value === 'webp')
  const [background, setBackground] = usePersistentState<'auto' | 'opaque' | 'transparent'>(
    'caelo.media.image.background.v1', 'auto',
    (value): value is 'auto' | 'opaque' | 'transparent' =>
      value === 'auto' || value === 'opaque' || value === 'transparent')
  const [moderation, setModeration] = usePersistentState<'low' | 'auto'>(
    'caelo.media.image.moderation.v1', 'low',
    (value): value is 'low' | 'auto' => value === 'low' || value === 'auto')
  const [compression, setCompression] = usePersistentState('caelo.media.image.compression.v1', 90,
    (value): value is number => typeof value === 'number' && value >= 0 && value <= 100)
  const [thinking, setThinking] = usePersistentState<'minimal' | 'low' | 'medium' | 'high'>(
    'caelo.media.image.thinking.v1', 'medium',
    (value): value is 'minimal' | 'low' | 'medium' | 'high' =>
      value === 'minimal' || value === 'low' || value === 'medium' || value === 'high')
  const [grounding, setGrounding] = usePersistentState('caelo.media.image.grounding.v1', false,
    (value): value is boolean => typeof value === 'boolean')
  const [error, setError] = useState<string | null>(null)
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [results, setResults] = useState<HubArtifact[]>([])
  const { jobs, submitImage, cancel, retry, clearFinished, dismiss, error: jobsError } = useGenJobs(conn)
  const { currentProjectId, pendingSend, setPendingSend, imageRefs: images,
    setImageRefs: setImages, promptReuse, setPromptReuse } = useHub()
  const editing = images.length > 0
  const caps = useMediaCapabilities(conn, 'image', editing ? 'edit' : 'text2img')
  const capability = caps.descriptor?.capabilities
  const maxRefs = capability?.max_reference_images ?? 3
  const referenceRoleOptions = useMemo(() => imageReferenceRoleOptions(capability), [capability])
  const newReferenceRole = defaultReferenceRole(referenceRoleOptions)
  const imageJobs = jobs.filter((job) => job.kind === 'image')
  const doneCount = imageJobs.filter((job) => job.status === 'done').length

  useEffect(() => {
    if (!capability) return
    const ratios = capability?.aspect_ratios ?? []
    const resolutions = capability?.resolutions ?? []
    const qualityLevels = capability?.quality_levels ?? []
    const formats = capability?.output_formats ?? []
    const backgrounds = capability?.backgrounds ?? []
    const moderationLevels = capability?.moderation_levels ?? []
    if (ratios.length && !ratios.includes(ratio)) setRatio(ratios[0])
    if (resolutions.length && !resolutions.includes(resolution)) setResolution(resolutions[0])
    if (qualityLevels.length && !qualityLevels.includes(quality)) {
      setQuality((qualityLevels.includes('medium') ? 'medium' : qualityLevels[0]) as typeof quality)
    }
    if (formats.length && !formats.includes(outputFormat)) setOutputFormat(formats[0] as typeof outputFormat)
    if (backgrounds.length && !backgrounds.includes(background)) setBackground(backgrounds[0] as typeof background)
    if (moderationLevels.length && !moderationLevels.includes(moderation)) {
      setModeration(moderationLevels[0] as typeof moderation)
    }
    if (outputFormat === 'jpeg' && background === 'transparent') setBackground('auto')
    const limited = images.slice(0, maxRefs)
    const normalized = normalizeReferenceRoles(limited, referenceRoleOptions)
    if (normalized.length !== images.length || normalized.some((item, index) => item !== images[index])) {
      setImages(normalized)
    }
  }, [background, capability, images, maxRefs, moderation, outputFormat, quality, ratio,
    referenceRoleOptions, resolution, setBackground, setImages, setModeration, setOutputFormat,
    setQuality, setRatio, setResolution])

  const refreshResults = useCallback((force = false) => {
    listRecentArtifacts(conn, 'image', currentProjectId ?? undefined, force)
      .then(setResults).catch(() => undefined)
  }, [conn, currentProjectId])
  const previousDoneCount = useRef(doneCount)
  useEffect(() => {
    const force = doneCount > previousDoneCount.current
    previousDoneCount.current = doneCount
    refreshResults(force)
  }, [refreshResults, doneCount])

  useEffect(() => {
    if (promptReuse?.target !== 'Image') return
    setPrompt(promptReuse.text)
    setPromptReuse(null)
  }, [promptReuse, setPromptReuse])

  useEffect(() => {
    if (!pendingSend || pendingSend.target !== 'Image') return
    const block = pendingSend.block.block
    if (block.type === 'image_url') {
      setImages((items) => [...items, { name: pendingSend.label || 'reference',
        uri: block.image_url.url, artifactId: pendingSend.block.artifact_id,
        role: newReferenceRole }].slice(0, maxRefs))
    }
    setPendingSend(null)
  }, [pendingSend, setImages, setPendingSend, maxRefs, newReferenceRole])

  async function addFiles(files: FileList | null): Promise<void> {
    const selected = Array.from(files ?? []).filter((file) => file.type.startsWith('image/'))
    const loaded = await Promise.all(selected.map(async (file) => ({
      name: file.name, uri: (await compressImageIfNeeded(file)).uri, role: newReferenceRole
    })))
    setImages((items) => [...items, ...loaded].slice(0, maxRefs))
  }
  function onPick(event: ChangeEvent<HTMLInputElement>): void {
    void addFiles(event.target.files); event.target.value = ''
  }
  function onDrop(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault(); void addFiles(event.dataTransfer.files)
  }

  async function run(): Promise<void> {
    if (!prompt.trim() || !caps.model) return
    setError(null)
    const mimeType = outputFormat === 'jpeg' ? 'image/jpeg' :
      outputFormat === 'webp' ? 'image/webp' : 'image/png'
    await submitImage({ provider: caps.provider, model: caps.model,
      op: editing ? 'edit' : 'text2img', prompt: prompt.trim(), n,
      aspect_ratio: ratio, resolution,
      images: editing ? images.map((item) => item.uri) : undefined,
      reference_roles: editing ? images.map((item) => item.role ?? 'general') : undefined,
      source_artifact_ids: images.filter((item) => item.artifactId).map((item) => item.artifactId as string),
      source_artifact_roles: images.filter((item) => item.artifactId).map((item) => item.role ?? 'general'),
      quality: capability?.supports_quality ? quality : undefined,
      mime_type: capability?.output_formats?.length ? mimeType : undefined,
      output_format: capability?.output_formats?.length ? outputFormat : undefined,
      output_compression: capability?.supports_output_compression && outputFormat !== 'png' ? compression : undefined,
      background: capability?.backgrounds?.length ? background : undefined,
      moderation: capability?.moderation_levels?.length ? moderation : undefined,
      thinking_level: capability?.thinking ? thinking : undefined,
      search_grounding: capability?.search_grounding ? grounding : undefined })
  }

  async function makeVariations(art: HubArtifact): Promise<void> {
    try {
      const mimeType = outputFormat === 'jpeg' ? 'image/jpeg' :
        outputFormat === 'webp' ? 'image/webp' : 'image/png'
      const input = await getArtifactInputBlock(conn, art.id)
      if (!input.data_uri) throw new Error('This image cannot be used as a reference.')
      await submitImage({ provider: caps.provider, model: caps.model, op: 'variation',
        prompt: prompt.trim() || 'Make variations of this image', n, aspect_ratio: ratio,
        resolution, images: [input.data_uri], reference_roles: ['starting_image'],
        source_artifact_ids: [art.id], source_artifact_roles: ['starting_image'],
        quality: capability?.supports_quality ? quality : undefined,
        mime_type: capability?.output_formats?.length ? mimeType : undefined,
        output_format: capability?.output_formats?.length ? outputFormat : undefined,
        output_compression: capability?.supports_output_compression && outputFormat !== 'png' ? compression : undefined,
        background: capability?.backgrounds?.length ? background : undefined,
        moderation: capability?.moderation_levels?.length ? moderation : undefined })
    } catch (e) { setError(String((e as Error).message || e)) }
  }

  return (
    <Page title="Image" subtitle="Generate and edit with xAI, Google, or OpenAI. The form follows the selected model's capabilities."
      actions={<Badge tone={editing ? 'accent' : 'neutral'}>{editing ? `Edit · ${images.length}/${maxRefs}` : 'Generate'}</Badge>}>
      <div onDrop={onDrop} onDragOver={(e) => e.preventDefault()}
        className="mb-4 min-h-28 rounded-xl border border-dashed border-border-strong bg-surface/40 p-4">
        {images.length ? <ReferenceLibrary items={images} max={maxRefs} onChange={setImages}
          options={referenceRoleOptions} /> :
          <p className="py-8 text-center text-sm text-muted">Drop reference images here. This model accepts up to {maxRefs}.</p>}
      </div>
      <Card>
        <Textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={4}
          placeholder={editing ? 'Describe the edit…' : 'Describe the image…'} className="mb-4" />
        <div className="flex flex-wrap items-end gap-3">
          <ProviderModelPicker providers={caps.providers} provider={caps.provider} onProvider={caps.setProvider}
            models={caps.models} model={caps.model} onModel={caps.setModel} />
          <Field label="Images" className="w-24"><Select size="sm" value={n} onChange={(e) => setN(Number(e.target.value))}>
            {[1, 2, 3, 4].map((value) => <option key={value} value={value}>{value}</option>)}</Select></Field>
          {capability?.aspect_ratios.length ? <Field label="Aspect" className="w-28"><Select size="sm" value={ratio} onChange={(e) => setRatio(e.target.value)}>
            {capability.aspect_ratios.map((value) => <option key={value}>{value}</option>)}</Select></Field> : null}
          {capability?.resolutions.length ? <Field label="Resolution" className="w-24"><Select size="sm" value={resolution} onChange={(e) => setResolution(e.target.value)}>
            {capability.resolutions.map((value) => <option key={value}>{value}</option>)}</Select></Field> : null}
          {capability?.supports_quality ? <Field label="Quality" className="w-28"><Select size="sm" value={quality} onChange={(e) => setQuality(e.target.value as typeof quality)}>
            {capability.quality_levels.map((value) => <option key={value}>{value}</option>)}</Select></Field> : null}
          {capability?.output_formats?.length ? <Field label="Format" className="w-24"><Select size="sm" value={outputFormat} onChange={(e) => setOutputFormat(e.target.value as typeof outputFormat)}>
            {capability.output_formats.map((value) => <option key={value}>{value.toUpperCase()}</option>)}</Select></Field> : null}
          {capability?.backgrounds?.length ? <Field label="Background" className="w-28"><Select size="sm" value={background} onChange={(e) => setBackground(e.target.value as typeof background)}>
            {capability.backgrounds.filter((value) => outputFormat !== 'jpeg' || value !== 'transparent').map((value) => <option key={value}>{value}</option>)}</Select></Field> : null}
          {capability?.supports_output_compression && outputFormat !== 'png' ? <Field label="Compression" className="w-24"><Input className="h-8" type="number" min={0} max={100} value={compression}
            onChange={(e) => setCompression(Math.min(100, Math.max(0, Number(e.target.value))))} /></Field> : null}
          {capability?.moderation_levels?.length ? <Field label="Moderation" className="w-28"><Select size="sm" value={moderation} onChange={(e) => setModeration(e.target.value as typeof moderation)}>
            {capability.moderation_levels.map((value) => <option key={value}>{value}</option>)}</Select></Field> : null}
          {capability?.thinking ? <Field label="Thinking" className="w-28"><Select size="sm" value={thinking} onChange={(e) => setThinking(e.target.value as typeof thinking)}>
            {capability.thinking_levels.map((value) => <option key={value}>{value}</option>)}</Select></Field> : null}
          {capability?.search_grounding ? <label className="flex h-8 items-center gap-2 text-xs"><input type="checkbox" checked={grounding} onChange={(e) => setGrounding(e.target.checked)} /> Search grounding</label> : null}
          <Button type="button" variant="outline" size="sm" icon={<Images size={14} />}
            onClick={() => setLibraryOpen(true)}>Reference library</Button>
          <label className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg border border-border bg-surface-2 px-3 text-xs font-medium">
            <ImagePlus size={14} /> From disk<input hidden multiple type="file" accept="image/*" onChange={onPick} />
          </label>
          <Button className="ml-auto" icon={<Sparkles size={16} />} onClick={run} disabled={!prompt.trim() || !caps.model}>Generate</Button>
        </div>
      </Card>
      {error || caps.error || jobsError ? <p className="mt-3 text-sm text-error">{error || caps.error || jobsError}</p> : null}
      <div className="mt-6"><GenQueue jobs={imageJobs.slice(0, 8)} onCancel={cancel} onRetry={retry}
        onClear={() => clearFinished('image')} onDismiss={dismiss} title="Jobs" /></div>
      {results.length ? <div className="mt-6"><h2 className="mb-2 text-sm font-semibold text-muted">Recent images</h2>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4">{results.map((art) =>
          <ArtifactCard key={art.id} conn={conn} art={art} onDeleted={(id) => {
            forgetRecentArtifact(conn, id)
            setResults((items) => items.filter((x) => x.id !== id))
          }}>
            <Button variant="ghost" size="sm" onClick={() => makeVariations(art)}>Variations</Button>
          </ArtifactCard>)}</div></div> : null}
      {libraryOpen ? <ReferencePicker conn={conn} max={maxRefs} current={images} defaultRole={newReferenceRole}
        onAdd={(selected) => setImages((current) => {
          const existing = new Set(current.map((item) => item.libraryId ?? item.artifactId).filter(Boolean))
          return [...current, ...selected.filter((item) => {
            const id = item.libraryId ?? item.artifactId
            return !id || !existing.has(id)
          })].slice(0, maxRefs)
        })} onClose={() => setLibraryOpen(false)} /> : null}
    </Page>
  )
}
