"use client"

import { Suspense } from "react"
import { SkyViewer } from "@/components/viewer/SkyViewer"
import { useViewerState } from "@/hooks/useViewerState"

function ViewerInner() {
  const [state, update] = useViewerState()
  return <SkyViewer state={state} update={update} variant="researcher" />
}

export default function ViewerPage() {
  return (
    <div className="mx-auto max-w-[1600px] px-3 py-4">
      <h1 className="sr-only">Nexus Viewer — Researcher mode</h1>
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading viewer…</p>}>
        <ViewerInner />
      </Suspense>
    </div>
  )
}
