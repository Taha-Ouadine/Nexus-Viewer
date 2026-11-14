"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { api, ApiError } from "@/lib/api"
import { subscribeToJob } from "@/lib/supabase"
import type { JobRequest, JobStatus } from "@/lib/types"

/** Submit a frame-building job whenever `req` changes and follow it until it finishes.
 *  Progress comes from polling every second (or Supabase Realtime when configured). */
export function useJob(req: JobRequest | null) {
  const key = useMemo(() => (req ? JSON.stringify(req) : null), [req])
  const [jobId, setJobId] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  // Bumped to resubmit the same request when the backend has forgotten the job (restart).
  const [resubmit, setResubmit] = useState(0)
  const resubmits = useRef<{ key: string | null; n: number }>({ key: null, n: 0 })

  useEffect(() => {
    setJobId(null)
    setSubmitError(null)
    if (!key) return
    let cancelled = false
    api
      .createJob(JSON.parse(key) as JobRequest)
      .then((r) => !cancelled && setJobId(r.job_id))
      .catch((e: Error) => !cancelled && setSubmitError(e.message))
    return () => {
      cancelled = true
    }
  }, [key, resubmit])

  const q = useQuery<JobStatus>({
    queryKey: ["job", jobId],
    queryFn: () => api.getJob(jobId as string),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const s = query.state.data?.status
      if (query.state.error instanceof ApiError && query.state.error.status === 404) return false
      return s === "done" || s === "failed" ? false : 1000
    },
    retry: (n, err) => !(err instanceof ApiError && err.status === 404) && n < 2,
  })

  // 404 = the backend restarted and lost its in-memory jobs: submit the request again
  // (finished frames are cached, so this is cheap). At most twice per request.
  useEffect(() => {
    if (!(q.error instanceof ApiError) || q.error.status !== 404) return
    if (resubmits.current.key !== key) resubmits.current = { key, n: 0 }
    if (resubmits.current.n >= 2) return
    resubmits.current.n += 1
    setResubmit((v) => v + 1)
  }, [q.error, key])

  // Optional Realtime: refetch as soon as the job row changes.
  useEffect(() => {
    if (!jobId) return
    const unsub = subscribeToJob(jobId, () => void q.refetch())
    return () => unsub?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId])

  return {
    job: q.data ?? null,
    error: submitError ?? (q.error ? (q.error as Error).message : null) ?? (q.data?.status === "failed" ? q.data.error ?? "Job failed" : null),
    submitting: !!key && !jobId && !submitError,
  }
}
