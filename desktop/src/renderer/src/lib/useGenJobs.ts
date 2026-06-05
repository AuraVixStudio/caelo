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
  const [jobs, setJobs] = useState<GenJob[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const aliveRef = useRef(true)
  const jobsRef = useRef<GenJob[]>([])
  jobsRef.current = jobs

  const fetchOnce = useCallback(() => {
    listGenJobs(conn, { limit: 50 })
      .then((r) => {
        if (!aliveRef.current) return
        setJobs((prev) => mergeJobs(prev, r.jobs))
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
      if (aliveRef.current && activeCount(jobsRef.current) > 0) fetchOnce()
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
        if (aliveRef.current) setJobs((prev) => mergeJob(prev, r.job))
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
        if (aliveRef.current) setJobs((prev) => mergeJob(prev, r.job))
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
        if (aliveRef.current) setJobs((prev) => mergeJob(prev, r.job))
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
        if (aliveRef.current) setJobs((prev) => mergeJob(prev, r.job))
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
        if (aliveRef.current) {
          setJobs((prev) =>
            prev.filter((j) => !(isTerminal(j.status) && (!kind || j.kind === kind)))
          )
        }
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
        if (aliveRef.current) setJobs((prev) => prev.filter((j) => j.id !== id))
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
    refresh: fetchOnce
  }
}
