import { listArtifacts, type Conn, type HubArtifact } from './api'

const ARTIFACT_CACHE_MS = 15_000

interface ArtifactCacheEntry {
  artifacts: HubArtifact[]
  updatedAt: number
  inflight?: Promise<HubArtifact[]>
  /** Sequence of the request that produced/updates this entry (newest wins). */
  sequence: number
}

const artifactCache = new WeakMap<Conn, Map<string, ArtifactCacheEntry>>()
let requestSequence = 0

function keyFor(mode: 'image' | 'video', projectId?: string): string {
  return `${mode}:${projectId ?? ''}`
}

/**
 * Reuse the recent-media query while the user moves between Image and Video.
 * A newly completed job can force a refresh, while concurrent callers share
 * the same request instead of stacking work in the sidecar.
 *
 * `force` always issues a NEW request. Joining an in-flight one would answer with
 * a list fetched before the job finished — and then stamp it as fresh — so a
 * just-generated image stayed invisible until the app was restarted.
 */
export function listRecentArtifacts(
  conn: Conn,
  mode: 'image' | 'video',
  projectId?: string,
  force = false
): Promise<HubArtifact[]> {
  let entries = artifactCache.get(conn)
  if (!entries) {
    entries = new Map()
    artifactCache.set(conn, entries)
  }
  const key = keyFor(mode, projectId)
  const cached = entries.get(key)
  if (!force && cached && Date.now() - cached.updatedAt < ARTIFACT_CACHE_MS) {
    return Promise.resolve(cached.artifacts)
  }
  if (!force && cached?.inflight) return cached.inflight

  requestSequence += 1
  const sequence = requestSequence
  const request = listArtifacts(conn, { mode, project_id: projectId, limit: 24 })
    .then((response) => {
      const current = entries!.get(key)
      // An older response must never overwrite a newer one (forced refreshes race
      // with the periodic one that is already on the wire).
      if (!current || current.sequence <= sequence) {
        entries!.set(key, {
          artifacts: response.artifacts,
          updatedAt: Date.now(),
          sequence,
          inflight: current?.inflight
        })
      }
      return response.artifacts
    })
    .catch((error) => {
      if (cached) return cached.artifacts
      throw error
    })
    .finally(() => {
      const current = entries!.get(key)
      if (current && current.inflight === request) current.inflight = undefined
    })
  entries.set(key, {
    artifacts: cached?.artifacts ?? [],
    updatedAt: cached?.updatedAt ?? 0,
    sequence: cached?.sequence ?? 0,
    inflight: request
  })
  return request
}

export function forgetRecentArtifact(conn: Conn, artifactId: string): void {
  const entries = artifactCache.get(conn)
  if (!entries) return
  for (const cached of entries.values()) {
    cached.artifacts = cached.artifacts.filter((artifact) => artifact.id !== artifactId)
  }
}
