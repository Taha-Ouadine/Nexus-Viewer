"use client"

import { Suspense } from "react"
import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { Badge } from "@/components/ui/badge"
import { SkyViewer } from "@/components/viewer/SkyViewer"
import { useViewerState } from "@/hooks/useViewerState"
import { api } from "@/lib/api"

function ExploreInner() {
  const [state, update] = useViewerState()
  const targets = useQuery({ queryKey: ["targets"], queryFn: api.targets, staleTime: Infinity })
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">Try:</span>
        {(targets.data ?? []).filter((t) => t.is_featured).map((t) => (
          <button key={t.slug} type="button"
            onClick={() => update({
              target: t.slug, ra: null, dec: null, band: t.recommended_view.band, fov: t.recommended_view.fov,
              zoom: t.recommended_view.zoom, diff: "none", mode: t.recommended_view.mode ?? "epochs",
              window: t.recommended_view.window ?? 30, max: "p99.5", min: "p0.5",
            })}>
            <Badge variant={state.target === t.slug ? "default" : "secondary"} className="cursor-pointer px-3 py-1 text-sm">{t.name}</Badge>
          </button>
        ))}
      </div>
      <SkyViewer state={state} update={update} variant="explorer" />
    </div>
  )
}

export default function ExplorePage() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <h1 className="mb-1 text-3xl font-bold">Explore the moving sky</h1>
      <p className="mb-6 text-muted-foreground">
        Pick a star, press play, and watch for anything that jumps or flickers. Want every control?{" "}
        <Link href="/viewer" className="text-primary underline">Switch to Researcher mode</Link>.
      </p>
      <Suspense fallback={null}>
        <ExploreInner />
      </Suspense>
    </div>
  )
}
