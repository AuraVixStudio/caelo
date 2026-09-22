import { useEffect, useMemo, useState } from 'react'
import { getCapabilities, getProviders, type Conn, type ModelDescriptor, type ProviderDescriptor } from './api'
import { GENERATED_MODEL_REGISTRY } from './generated/models'
import { usePersistentState } from './usePersistentState'

const isString = (value: unknown): value is string => typeof value === 'string'
const CAPABILITIES_CACHE_MS = 5 * 60_000

type MediaType = 'image' | 'video'

interface CapabilitySnapshot {
  providers: ProviderDescriptor[]
  models: ModelDescriptor[]
  defaultProvider?: string
}

interface CapabilityCacheEntry extends CapabilitySnapshot {
  updatedAt: number
  inflight?: Promise<CapabilitySnapshot>
}

const capabilitiesCache = new WeakMap<Conn, Map<MediaType, CapabilityCacheEntry>>()

function generatedSnapshot(mediaType: MediaType): CapabilitySnapshot {
  return {
    providers: GENERATED_MODEL_REGISTRY.providers
      .filter((item) => item.id !== 'mock'
        && (item.modalities as readonly string[]).includes(mediaType)) as unknown as ProviderDescriptor[],
    models: GENERATED_MODEL_REGISTRY.models
      .filter((item) => item.media_type === mediaType) as unknown as ModelDescriptor[]
  }
}

function cachedSnapshot(conn: Conn, mediaType: MediaType): CapabilityCacheEntry | undefined {
  return capabilitiesCache.get(conn)?.get(mediaType)
}

function loadCapabilities(conn: Conn, mediaType: MediaType): Promise<CapabilitySnapshot> {
  let byMedia = capabilitiesCache.get(conn)
  if (!byMedia) {
    byMedia = new Map()
    capabilitiesCache.set(conn, byMedia)
  }
  const cached = byMedia.get(mediaType)
  if (cached && Date.now() - cached.updatedAt < CAPABILITIES_CACHE_MS) {
    return Promise.resolve(cached)
  }
  if (cached?.inflight) return cached.inflight

  const fallback = cached ?? { ...generatedSnapshot(mediaType), updatedAt: 0 }
  const request = Promise.all([getProviders(conn), getCapabilities(conn, { media_type: mediaType })])
    .then(([providers, capabilities]): CapabilitySnapshot => ({
      providers: providers.providers
        .filter((item) => item.id !== 'mock' && item.modalities.includes(mediaType)),
      models: capabilities.capabilities ?? [],
      defaultProvider: providers.default
    }))
    .catch(() => generatedSnapshot(mediaType))
    .then((snapshot) => {
      byMedia!.set(mediaType, { ...snapshot, updatedAt: Date.now() })
      return snapshot
    })
  byMedia.set(mediaType, { ...fallback, inflight: request })
  return request
}

export function useMediaCapabilities(conn: Conn, mediaType: MediaType, operation: string) {
  const initial = cachedSnapshot(conn, mediaType) ?? generatedSnapshot(mediaType)
  const [providers, setProviders] = useState<ProviderDescriptor[]>(initial.providers)
  const [allModels, setAllModels] = useState<ModelDescriptor[]>(initial.models)
  const [provider, setProvider] = usePersistentState(`caelo.media.${mediaType}.provider.v1`, 'xai', isString)
  const [model, setModel] = usePersistentState(`caelo.media.${mediaType}.model.v1`, '', isString)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    loadCapabilities(conn, mediaType)
      .then((snapshot) => {
        if (!alive) return
        setProviders(snapshot.providers)
        setAllModels(snapshot.models)
        setProvider((current) => current || snapshot.defaultProvider || snapshot.providers[0]?.id || '')
        setError(null)
      })
    return () => { alive = false }
  }, [conn, mediaType, setProvider])

  const models = useMemo(
    () => allModels.filter((item) => item.provider === provider && item.capabilities.operations.includes(operation)),
    [allModels, provider, operation]
  )

  useEffect(() => {
    if (!providers.length || providers.some((item) => item.id === provider)) return
    setProvider(providers[0].id)
  }, [provider, providers, setProvider])

  useEffect(() => {
    if (models.some((item) => item.id === model)) return
    setModel(models.find((item) => item.is_default)?.id ?? models[0]?.id ?? '')
  }, [models, model, setModel])

  const descriptor = models.find((item) => item.id === model) ?? models[0]
  return { providers, provider, setProvider, models, model, setModel, descriptor, error }
}
