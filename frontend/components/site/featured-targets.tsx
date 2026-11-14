"use client"

import Link from "next/link"
import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import type { Target } from "@/lib/types"

export function targetViewerHref(t: Target, path = "/viewer") {
  const v = t.recommended_view
  const q = new URLSearchParams({ target: t.slug, band: v.band, fov: String(v.fov), zoom: String(v.zoom) })
  if (v.diff && v.diff !== "none") q.set("diff", v.diff)
  if (v.window) q.set("window", String(v.window))
  if (v.mode && v.mode !== "epochs") q.set("mode", v.mode)
  return `${path}?${q}`
}

function Thumb({ slug, name }: { slug: string; name: string }) {
  const [ok, setOk] = useState(true)
  return ok ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={`/targets/${slug}.gif`} alt={`Animated SPHEREx frames of ${name}`} onError={() => setOk(false)}
      className="aspect-square w-full bg-black object-cover" style={{ imageRendering: "pixelated" }} />
  ) : (
    <div className="flex aspect-square w-full items-center justify-center bg-black text-xs text-muted-foreground">
      preview not generated yet
    </div>
  )
}

export function FeaturedTargets({ limit, all }: { limit?: number; all?: boolean }) {
  const q = useQuery({ queryKey: ["targets"], queryFn: api.targets, staleTime: Infinity })
  if (q.isLoading) {
    return <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-80" />)}</div>
  }
  if (q.error) return <p className="text-center text-sm text-destructive">Could not reach the backend: {(q.error as Error).message}</p>
  const list = (q.data ?? []).filter((t) => all || t.is_featured).slice(0, limit)
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {list.map((t) => (
        <Card key={t.slug} className="overflow-hidden bg-card/70 backdrop-blur">
          <Thumb slug={t.slug} name={t.name} />
          <CardContent className="space-y-2 p-4">
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-semibold">{t.name}</h3>
              <Badge variant="secondary" className="text-[10px]">{t.category}</Badge>
            </div>
            <p className="text-sm text-muted-foreground">{t.description}</p>
            <p className="text-xs"><b>What to look for:</b> {t.what_to_see}</p>
            {t.pmra_masyr != null && (
              <p className="font-mono text-[11px] text-muted-foreground">
                proper motion {(Math.hypot(t.pmra_masyr, t.pmdec_masyr ?? 0) / 1000).toFixed(2)}″/yr
              </p>
            )}
            <div className="flex gap-2 pt-1">
              <Button asChild size="sm"><Link href={targetViewerHref(t, "/explore")}>Explore</Link></Button>
              <Button asChild size="sm" variant="outline"><Link href={targetViewerHref(t)}>Open in viewer</Link></Button>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
