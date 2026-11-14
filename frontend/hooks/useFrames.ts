"use client"

import { useEffect, useRef, useState } from "react"
import { api } from "@/lib/api"
import type { FrameMeta } from "@/lib/types"

export interface LoadedFrame {
  meta: FrameMeta
  channels: Float32Array[]
  flags?: Uint32Array
}

/** Download the raw float32 pixels of every frame (progressively, as the job publishes them). */
export function useFrames(frames: FrameMeta[] | undefined, withFlags: boolean) {
  const cache = useRef(new Map<string, LoadedFrame>())
  const flagCache = useRef(new Map<string, Uint32Array>())
  const [version, setVersion] = useState(0)

  useEffect(() => {
    if (!frames) return
    let cancelled = false
    for (const m of frames) {
      if (!cache.current.has(m.id)) {
        cache.current.set(m.id, { meta: m, channels: [] }) // placeholder: mark as loading
        api
          .getFrame(m)
          .then((ch) => {
            cache.current.set(m.id, { meta: m, channels: ch })
            if (!cancelled) setVersion((v) => v + 1)
          })
          .catch(() => cache.current.delete(m.id))
      }
      if (withFlags && !flagCache.current.has(m.id)) {
        flagCache.current.set(m.id, new Uint32Array(0))
        api
          .getFlags(m)
          .then((f) => {
            flagCache.current.set(m.id, f)
            if (!cancelled) setVersion((v) => v + 1)
          })
          .catch(() => flagCache.current.delete(m.id))
      }
    }
    return () => {
      cancelled = true
    }
  }, [frames, withFlags])

  const loaded: LoadedFrame[] = (frames ?? [])
    .map((m): LoadedFrame | null => {
      const f = cache.current.get(m.id)
      if (!f || f.channels.length === 0) return null
      const flags = flagCache.current.get(m.id)
      return { ...f, meta: m, flags: flags && flags.length ? flags : undefined }
    })
    .filter((x): x is LoadedFrame => x !== null)

  return { loaded, version }
}
