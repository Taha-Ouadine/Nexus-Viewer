"use client"

import { useCallback, useEffect, useRef, useState } from "react"

/** Flip-book playback: index, play/pause, speed (ms per frame), keyboard shortcuts. */
export function usePlayback(count: number, speedMs: number, autoplay: boolean) {
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(autoplay)
  const last = useRef(0)

  useEffect(() => {
    if (index >= count && count > 0) setIndex(count - 1)
  }, [count, index])

  useEffect(() => {
    if (!playing || count < 2) return
    let raf = 0
    const tick = (t: number) => {
      if (t - last.current >= speedMs) {
        last.current = t
        setIndex((i) => (i + 1) % count)
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing, count, speedMs])

  const step = useCallback(
    (d: number) => {
      if (count === 0) return
      setPlaying(false)
      setIndex((i) => (i + d + count) % count)
    },
    [count],
  )

  return { index, setIndex, playing, setPlaying, step }
}

/** Space = play/pause, arrows = step, +/- = zoom. Ignored while typing in inputs. */
export function useViewerKeys(handlers: {
  toggle: () => void
  step: (d: number) => void
  zoom: (d: number) => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)) return
      if (e.key === " ") {
        e.preventDefault()
        handlers.toggle()
      } else if (e.key === "ArrowRight") handlers.step(1)
      else if (e.key === "ArrowLeft") handlers.step(-1)
      else if (e.key === "+" || e.key === "=") handlers.zoom(1)
      else if (e.key === "-") handlers.zoom(-1)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [handlers])
}
