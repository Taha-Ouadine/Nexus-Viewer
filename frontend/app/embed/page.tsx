"use client"

import { Suspense } from "react"
import { SkyViewer } from "@/components/viewer/SkyViewer"
import { useViewerState } from "@/hooks/useViewerState"

function EmbedInner() {
  const [state, update] = useViewerState()
  return <SkyViewer state={state} update={update} variant="embed" />
}

/** Chrome-less viewer for <iframe> embedding (frame-ancestors * is set for this route only). */
export default function EmbedPage() {
  return (
    <Suspense fallback={null}>
      <EmbedInner />
    </Suspense>
  )
}
