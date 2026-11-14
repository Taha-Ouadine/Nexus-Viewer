"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { parseViewerState, serializeViewerState, type ViewerState } from "@/lib/url-state"

/** Viewer state that lives in the URL query string (so any view can be shared/embedded). */
export function useViewerState(): [ViewerState, (patch: Partial<ViewerState>) => void] {
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const [state, setState] = useState<ViewerState>(() => parseViewerState(new URLSearchParams(params.toString())))
  const lastWritten = useRef<string>("")

  // Back/forward navigation or a link changed the URL -> adopt it.
  useEffect(() => {
    const qs = params.toString()
    if (qs !== lastWritten.current) setState(parseViewerState(new URLSearchParams(qs)))
  }, [params])

  const current = useRef(state)
  current.current = state

  const update = useCallback(
    (patch: Partial<ViewerState>) => {
      const next = { ...current.current, ...patch }
      current.current = next
      const qs = serializeViewerState(next).toString()
      lastWritten.current = qs
      setState(next)
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
    },
    [router, pathname],
  )

  return [state, update]
}
