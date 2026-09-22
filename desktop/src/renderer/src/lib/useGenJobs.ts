// M11-F5: hook kolejki generacji — submit (obraz/wideo), polling aktywnych zadań,
// cancel/retry. Transport to REST polling (PLAN_M11 §0): odpytujemy `/genjobs`, gdy
// są zadania w toku; w spoczynku nie pollujemy. Stan serwera jest źródłem prawdy.

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  cancelGenJob,
  clearGenJobs,
  deleteGenJob,
  listGenJobs,
  retryGenJob,
  submitImageJob,
  submitVideoGenJob,
  type Conn,
  type GenJob,
  type GenJobKind,
  type ImageJobBody,
  type VideoGenJobBody
} from './api'
import { activeCount, isTerminal, mergeJob, mergeJobs } from './genjobs'

const POLL_INTERVAL_MS = 2500
// Switching modules unmounts Image/Video. Keep the lightweight queue snapshot
// outside the component so a quick switch does not start another database read.
// Active jobs still bypass this window through the normal polling loop.
const IDLE_CACHE_MS = 60_000
const ACTIVE_DEDUP_MS = 2_000

interface JobsCacheEntry {
  jobs: GenJob[]
  updatedAt: number
  inflight?: Promise<GenJob[]>
}

const jobsCache = new WeakMap<Conn, JobsCacheEntry>()

function cacheFor(conn: Conn): JobsCacheEntry {
  const cached = jobsCache.get(conn)
  if (cached) return cached
  const created: JobsCacheEntry = { jobs: [], updatedAt: 0 }
  jobsCache.set(conn, created)
  return created
}

function commitJobs(conn: Conn, update: (jobs: GenJob[]) => GenJob[]): GenJob[] {
  const cached = cacheFor(conn)
  cached.jobs = update(cached.jobs)
  cached.updatedAt = Date.now()
  return cached.jobs
}

function loadJobs(conn: Conn, force: boolean): Promise<GenJob[]> {
  const cached = cacheFor(conn)
  const maxAge = force ? ACTIVE_DEDUP_MS : IDLE_CACHE_MS
  if (cached.updatedAt > 0 && Date.now() - cached.updatedAt < maxAge) {
    return Promise.resolve(cached.jobs)
  }
  if (cached.inflight) return cached.inflight

  const request = listGenJobs(conn, { limit: 50 })
    .then((response) => {
      cached.jobs = mergeJobs(cached.jobs, response.jobs)
      cached.updatedAt = Date.now()
      return cached.jobs
    })
    .finally(() => {
      cached.inflight = undefined
    })
  cached.inflight = request
  return request
}

export interface UseGenJobs {
  jobs: GenJob[]
  loading: boolean
  error: string | null
  submitImage: (body: ImageJobBody) => Promise<GenJob | null>
  submitVideo: (body: VideoGenJobBody) => Promise<GenJob | null>
  cancel: (id: string) => Promise<void>
  retry: (id: string) => Promise<void>
  /** Clear finished jobs from the list (optionally one kind). Media artifacts kept. */
  clearFinished: (kind?: GenJobKind) => Promise<void>
  /** Remove one finished job from the list. */
  dismiss: (id: string) => Promise<void>
  refresh: () => void
}

export function useGenJobs(conn: Conn): UseGenJobs {
  const initialCache = cacheFor(conn)
  const [jobs, setJobs] = useState<GenJob[]>(initialCache.jobs)
  const [loading, setLoading] = useState(initialCache.updatedAt === 0)
  const [error, setError] = useState<string | null>(null)
  const aliveRef = useRef(true)
  const jobsRef = useRef<GenJob[]>([])
  jobsRef.current = jobs

  const fetchOnce = useCallback((force = false) => {
    loadJobs(conn, force)
      .then((nextJobs) => {
        if (!aliveRef.current) return
        setJobs(nextJobs)
        setError(null)
      })
      .catch((e) => {
        if (aliveRef.current) setError(String((e as Error).message || e))
      })
      .finally(() => {
        if (aliveRef.current) setLoading(false)
      })
  }, [conn])

  // Initial load + interval poll while any job is active (idle = no requests).
  useEffect(() => {
    aliveRef.current = true
    fetchOnce()
    const id = setInterval(() => {
      if (aliveRef.current && activeCount(jobsRef.current) > 0) fetchOnce(true)
    }, POLL_INTERVAL_MS)
    return () => {
      aliveRef.current = false
      clearInterval(id)
    }
  }, [fetchOnce])

  const submitImage = useCallback(
    async (body: ImageJobBody): Promise<GenJob | null> => {
      try {
        const r = await submitImageJob(conn, body)
        const nextJobs = commitJobs(conn, (current) => mergeJob(current, r.job))
        if (aliveRef.current) setJobs(nextJobs)
        return r.job
      } catch (e) {
        if (aliveRef.current) setError(String((e as Error).message || e))
        return null
      }
    },
    [conn]
  )

  const submitVideo = useCallback(
    async (body: VideoGenJobBody): Promise<GenJob | null> => {
      try {
        const r = await submitVideoGenJob(conn, body)
        const nextJobs = commitJobs(conn, (current) => mergeJob(current, r.job))
        if (aliveRef.current) setJobs(nextJobs)
        return r.job
      } catch (e) {
        if (aliveRef.current) setError(String((e as Error).message || e))
        return null
      }
    },
    [conn]
  )

  const cancel = useCallback(
    async (id: string): Promise<void> => {
      try {
        const r = await cancelGenJob(conn, id)
        const nextJobs = commitJobs(conn, (current) => mergeJob(current, r.job))
        if (aliveRef.current) setJobs(nextJobs)
      } catch (e) {
        if (aliveRef.current) setError(String((e as Error).message || e))
      }
    },
    [conn]
  )

  const retry = useCallback(
    async (id: string): Promise<void> => {
      try {
        const r = await retryGenJob(conn, id)
        const nextJobs = commitJobs(conn, (current) => mergeJob(current, r.job))
        if (aliveRef.current) setJobs(nextJobs)
      } catch (e) {
        if (aliveRef.current) setError(String((e as Error).message || e))
      }
    },
    [conn]
  )

  const clearFinished = useCallback(
    async (kind?: GenJobKind): Promise<void> => {
      try {
        await clearGenJobs(conn, kind)
        const nextJobs = commitJobs(conn, (current) =>
          current.filter((job) => !(isTerminal(job.status) && (!kind || job.kind === kind)))
        )
        if (aliveRef.current) setJobs(nextJobs)
      } catch (e) {
        if (aliveRef.current) setError(String((e as Error).message || e))
      }
    },
    [conn]
  )

  const dismiss = useCallback(
    async (id: string): Promise<void> => {
      try {
        await deleteGenJob(conn, id)
        const nextJobs = commitJobs(conn, (current) => current.filter((job) => job.id !== id))
        if (aliveRef.current) setJobs(nextJobs)
      } catch (e) {
        if (aliveRef.current) setError(String((e as Error).message || e))
      }
    },
    [conn]
  )

  return {
    jobs,
    loading,
    error,
    submitImage,
    submitVideo,
    cancel,
    retry,
    clearFinished,
    dismiss,
    refresh: () => fetchOnce(true)
  }
}
