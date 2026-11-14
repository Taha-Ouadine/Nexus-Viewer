"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { AlertTriangle, ExternalLink, Loader2, Telescope } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { api, ApiError } from "@/lib/api"
import { formatDec, formatRA, jyearToMjd, propagate } from "@/lib/coords"
import { percentile, resolveLimit, zscale } from "@/lib/stretch"
import type { CatalogResponse, JobRequest, Target } from "@/lib/types"
import { serializeViewerState, type ViewerState } from "@/lib/url-state"
import { useJob } from "@/hooks/useJob"
import { useFrames, type LoadedFrame } from "@/hooks/useFrames"
import { usePlayback, useViewerKeys } from "@/hooks/usePlayback"
import { useLightCurve, useSpectrum, type PickPoint } from "@/hooks/usePhotometry"
import { FrameCanvas } from "./FrameCanvas"
import { CoordinateInput, type ResolvedInput } from "./CoordinateInput"
import { BandSelector, FovControl, ModeSelector, OverlayToggles, StretchControls, DETECTORS } from "./Controls"
import { PlaybackBar } from "./PlaybackBar"
import { MetadataPanel } from "./MetadataPanel"
import { LightCurveChart, SpectrumChart } from "./SpectrumChart"
import { AladinPanel } from "./AladinPanel"
import { ExportMenu } from "./ExportMenu"
import { InfoTip } from "./InfoTip"

export type Variant = "researcher" | "explorer" | "embed"

interface ResolvedTarget {
  name: string
  ra: number
  dec: number
  pm: { pmra: number; pmdec: number; ref_epoch: number; ra: number; dec: number } | null
  target: Target | null
}

const DEFAULT_BAD_MASK = [0, 1, 6, 7, 9, 10, 11, 14, 15, 17, 19, 20, 22, 23, 24, 25, 26, 27, 28].reduce((m, b) => (m | (1 << b)) >>> 0, 0)
const VIEW_EPOCH_MJD = jyearToMjd(2026.0)

async function resolveTarget(t: string): Promise<ResolvedTarget> {
  if (/^[a-z0-9-]+$/.test(t)) {
    try {
      const x = await api.target(t)
      return {
        name: x.name, ra: x.view_ra, dec: x.view_dec, target: x,
        pm: x.pmra_masyr != null ? { pmra: x.pmra_masyr, pmdec: x.pmdec_masyr ?? 0, ref_epoch: x.ref_epoch, ra: x.ra_deg, dec: x.dec_deg } : null,
      }
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 404)) throw e
    }
  }
  const r = await api.resolve(t)
  // Catalogue positions are for J2000; SPHEREx observed in 2025-26, so move fast stars there.
  const v = propagate(r.ra, r.dec, r.pmra, r.pmdec, r.ref_epoch, VIEW_EPOCH_MJD)
  return {
    name: r.name, ra: v.ra, dec: v.dec, target: null,
    pm: r.pmra != null || r.pmdec != null ? { pmra: r.pmra ?? 0, pmdec: r.pmdec ?? 0, ref_epoch: r.ref_epoch, ra: r.ra, dec: r.dec } : null,
  }
}

function differenceFrames(loaded: LoadedFrame[], how: ViewerState["diff"]): Float32Array[][] {
  if (how === "none" || loaded.length === 0) return loaded.map((f) => f.channels)
  const nCh = loaded[0].channels.length
  const n = loaded[0].channels[0].length
  return loaded.map((f, i) =>
    Array.from({ length: nCh }, (_, c) => {
      const out = new Float32Array(n)
      const cur = f.channels[c]
      if (how === "first" || how === "previous") {
        const ref = loaded[how === "first" ? 0 : Math.max(0, i - 1)].channels[c]
        for (let k = 0; k < n; k++) out[k] = cur[k] - ref[k]
      } else {
        for (let k = 0; k < n; k++) {
          let s = 0, m = 0
          for (let j = 0; j < loaded.length; j++) {
            if (j === i) continue
            const v = loaded[j].channels[c][k]
            if (Number.isFinite(v)) { s += v; m++ }
          }
          out[k] = m ? cur[k] - s / m : 0
        }
      }
      return out
    }),
  )
}

export function SkyViewer({ state, update, variant }: {
  state: ViewerState
  update: (p: Partial<ViewerState>) => void
  variant: Variant
}) {
  // ---------------- what are we looking at? ----------------
  const targetQ = useQuery({
    queryKey: ["target", state.target],
    queryFn: () => resolveTarget(state.target as string),
    enabled: !!state.target,
    staleTime: Infinity,
    retry: 1,
  })
  const centre = state.ra !== null && state.dec !== null
    ? { ra: state.ra, dec: state.dec }
    : targetQ.data ? { ra: targetQ.data.ra, dec: targetQ.data.dec } : null
  const pm = targetQ.data?.pm ?? null

  const jobReq: JobRequest | null = useMemo(() => {
    if (!centre) return null
    return {
      ra: Number(centre.ra.toFixed(6)), dec: Number(centre.dec.toFixed(6)), fov_arcsec: state.fov, band: state.band,
      mode: state.mode, diff: "none", window_days: state.window, subtract_zodi: state.zodi,
      track_pm: state.track && !!pm, pm, releases: state.releases,
    }
  }, [centre?.ra, centre?.dec, state.fov, state.band, state.mode, state.window, state.zodi, state.track, pm, state.releases]) // eslint-disable-line react-hooks/exhaustive-deps

  const { job, error: jobError, submitting } = useJob(jobReq)
  const metas = useMemo(() => job?.frames ?? [], [job?.frames])
  const { loaded } = useFrames(metas, state.flags)
  const shown = useMemo(() => differenceFrames(loaded, state.diff), [loaded, state.diff])

  // ---------------- playback ----------------
  const reduced = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
  const pb = usePlayback(loaded.length, state.speed, variant !== "researcher" && !reduced)
  const keyHandlers = useMemo(() => ({
    toggle: () => pb.setPlaying(!pb.playing),
    step: pb.step,
    zoom: (d: number) => update({ zoom: Math.min(16, Math.max(1, state.zoom + d)) }),
  }), [pb, state.zoom, update])
  useViewerKeys(keyHandlers)
  useEffect(() => {
    if (job?.status === "done" && loaded.length > 1 && variant === "researcher" && !reduced) pb.setPlaying(true)
  }, [job?.status, loaded.length > 1]) // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------- contrast limits (shared by all frames so the blink is stable) ----------------
  const limits = useMemo(() => {
    if (shown.length === 0) return { lo: [0], hi: [1] }
    const nCh = shown[0].length
    const gs = job?.info.global_stats
    const lo: number[] = []
    const hi: number[] = []
    for (let c = 0; c < nCh; c++) {
      if (state.diff === "none" && state.stretch !== "zscale" && gs && gs[c] && state.min === "p0.5" && state.max === "p99.5") {
        lo.push(gs[c].p0_5)
        hi.push(gs[c].p99_5)
        continue
      }
      const all = new Float32Array(shown.length * shown[0][c].length)
      shown.forEach((f, i) => all.set(f[c], i * f[c].length))
      if (state.stretch === "zscale") {
        const [a, b] = zscale(all)
        lo.push(a); hi.push(b)
      } else if (state.diff !== "none") {
        // difference images: symmetric around zero so "no change" is mid-grey
        const m = Math.max(Math.abs(percentile(all, parseFloat(state.min.slice(1)) || 0.5)), Math.abs(percentile(all, parseFloat(state.max.slice(1)) || 99.5)))
        lo.push(-m); hi.push(m)
      } else {
        lo.push(resolveLimit(state.min, all)); hi.push(resolveLimit(state.max, all))
      }
    }
    return { lo, hi }
  }, [shown, job?.info.global_stats, state.min, state.max, state.stretch, state.diff])

  // ---------------- catalogue overlays ----------------
  const gaiaQ = useQuery<CatalogResponse>({
    queryKey: ["gaia", centre?.ra, centre?.dec, state.fov],
    queryFn: () => api.gaia(centre!.ra, centre!.dec, state.fov),
    enabled: !!centre && state.gaia, staleTime: Infinity, retry: 1,
  })
  const wiseQ = useQuery<CatalogResponse>({
    queryKey: ["wise", centre?.ra, centre?.dec, state.fov],
    queryFn: () => api.wise(centre!.ra, centre!.dec, state.fov),
    enabled: !!centre && state.wise, staleTime: Infinity, retry: 1,
  })
  useEffect(() => { if (gaiaQ.error) toast.error("Gaia catalogue unavailable", { description: (gaiaQ.error as Error).message }) }, [gaiaQ.error])
  useEffect(() => { if (wiseQ.error) toast.error("CatWISE catalogue unavailable", { description: (wiseQ.error as Error).message }) }, [wiseQ.error])

  // ---------------- click to measure ----------------
  const [pick, setPick] = useState<PickPoint | null>(null)
  const [tab, setTab] = useState("spectrum")
  const [lcBand, setLcBand] = useState<string | null>(null)
  const effLcBand = lcBand ?? (/^D[1-6]$/.test(state.band) || state.band.startsWith("WL:") ? state.band : "D1")
  const spec = useSpectrum(pick, state.releases)
  const lc = useLightCurve(pick, effLcBand, state.releases)
  const onPick = useCallback((ra: number, dec: number, nearTarget: boolean) => {
    setPick(nearTarget && pm && targetQ.data
      ? { ra: targetQ.data.ra, dec: targetQ.data.dec, pm } // follow the moving target
      : { ra, dec, pm: null })
    if (variant === "researcher") setTab((t) => (t === "exposures" ? "spectrum" : t))
  }, [pm, targetQ.data, variant])

  // ---------------- search ----------------
  const onSearch = (v: ResolvedInput) => {
    setPick(null)
    if (v.kind === "coords") update({ ra: v.ra!, dec: v.dec!, target: null, track: false })
    else update({ target: v.name!, ra: null, dec: null })
  }

  const current = loaded[Math.min(pb.index, loaded.length - 1)]
  const currentShown = shown[Math.min(pb.index, shown.length - 1)]
  const running = submitting || (job && (job.status === "queued" || job.status === "running"))
  const title = targetQ.data?.name ?? (centre ? `${formatRA(centre.ra, 1)} ${formatDec(centre.dec, 0)}` : "")

  const canvas = current && currentShown ? (
    <FrameCanvas
      meta={current.meta}
      channels={currentShown}
      flags={current.flags}
      display={{ lo: limits.lo, hi: limits.hi, stretch: state.stretch, invert: state.invert, zoom: state.zoom, smooth: state.smooth }}
      overlays={{
        crosshair: state.crosshair, pmVector: state.pm && !!pm, flags: state.flags, badMask: DEFAULT_BAD_MASK,
        gaia: state.gaia ? gaiaQ.data ?? null : null, wise: state.wise ? wiseQ.data ?? null : null,
        pm: pm ? { pmra: pm.pmra, pmdec: pm.pmdec } : null, scaleBar: true,
      }}
      pick={pick}
      onPick={variant === "embed" ? undefined : onPick}
      maxCssSize={variant === "embed" ? 380 : variant === "explorer" ? 520 : 720}
      fit={variant !== "researcher"}
    />
  ) : null

  const status = (
    <StatusBox
      hasCentre={!!centre}
      resolving={targetQ.isLoading}
      resolveError={targetQ.error ? (targetQ.error as Error).message : null}
      running={!!running}
      stage={job?.stage ?? (submitting ? "submitting" : "")}
      progress={job?.progress ?? 0}
      error={jobError}
      reason={job?.status === "done" && metas.length === 0 ? job.info.reason ?? "No frames could be built here." : null}
      haveFrames={loaded.length > 0}
      variant={variant}
    />
  )

  const playback = loaded.length > 0 && (
    <PlaybackBar
      frames={loaded.map((f) => f.meta)} index={pb.index} setIndex={pb.setIndex} playing={pb.playing}
      setPlaying={pb.setPlaying} step={pb.step} speed={state.speed} setSpeed={(ms) => update({ speed: ms })}
      compact={variant === "embed"}
    />
  )

  // ======================= EMBED =======================
  if (variant === "embed") {
    return (
      <div className="flex min-h-screen flex-col items-center gap-2 bg-black p-2 text-foreground">
        <div className="flex w-full items-center justify-between text-xs">
          <span className="font-semibold">{title}</span>
          <span className="text-muted-foreground">{state.band}{state.diff !== "none" ? " · difference" : ""}</span>
        </div>
        {status}
        {canvas}
        <div className="w-full">{playback}</div>
        <a href={`/viewer?${serializeViewerState(state).toString()}`} target="_blank" rel="noreferrer"
          className="flex items-center gap-1 text-xs text-primary hover:underline">
          Open in Nexus Viewer <ExternalLink className="h-3 w-3" />
        </a>
        <p className="text-[10px] text-muted-foreground">SPHEREx data: NASA/IPAC IRSA</p>
      </div>
    )
  }

  // ======================= EXPLORER =======================
  if (variant === "explorer") {
    const pop = state.max.startsWith("p") ? parseFloat(state.max.slice(1)) : 99.5
    return (
      <div className="space-y-4">
        <CoordinateInput onSubmit={onSearch} busy={targetQ.isLoading} size="lg" />
        {centre && (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-2xl font-bold">{title}</h2>
            <WhatAmILookingAt target={targetQ.data?.target ?? null} />
          </div>
        )}
        {targetQ.data?.target && (
          <p className="rounded-md border border-primary/40 bg-primary/10 p-3 text-sm">💡 {targetQ.data.target.what_to_see}</p>
        )}
        {status}
        <div className="flex flex-col items-center gap-3">{canvas}</div>
        {playback}
        {loaded.length > 0 && (
          <div className="grid gap-4 rounded-lg border border-border/60 bg-card/60 p-4 sm:grid-cols-3">
            <div>
              <Label className="text-sm">Make it pop</Label>
              <p className="mb-2 text-xs text-muted-foreground">Brighten faint things (bright stars will saturate).</p>
              <Slider min={0} max={100} step={1} value={[Math.round(((99.95 - pop) / (99.95 - 95)) * 100)]}
                onValueChange={([v]) => update({ max: `p${(99.95 - (v / 100) * (99.95 - 95)).toFixed(2)}` })} aria-label="Make it pop" />
            </div>
            <div>
              <div className="flex items-center justify-between">
                <Label htmlFor="ex-diff" className="text-sm">Show difference</Label>
                <Switch id="ex-diff" checked={state.diff !== "none"} onCheckedChange={(v) => update({ diff: v ? "first" : "none" })} />
              </div>
              <p className="mt-1 text-xs text-muted-foreground">Subtract the first picture: anything that did not change turns grey, so movers and flickering stars stand out as black/white pairs.</p>
            </div>
            <div>
              <Label className="text-sm">Colour of light</Label>
              <div className="mt-2 flex flex-wrap gap-1">
                {[{ b: "ALL", l: "All" }, { b: "D1", l: "Short (0.8 µm)" }, { b: "D6", l: "Long (4.7 µm)" }, { b: "RGB:D2,D4,D5+D6", l: "False colour" }].map((x) => (
                  <Button key={x.b} size="sm" variant={state.band === x.b ? "default" : "outline"} onClick={() => update({ band: x.b })}>{x.l}</Button>
                ))}
              </div>
            </div>
          </div>
        )}
        {loaded.length > 0 && (
          <p className="text-center text-sm text-muted-foreground">
            Tip: press <kbd className="rounded border px-1">space</kbd> to pause, <kbd className="rounded border px-1">←</kbd>/<kbd className="rounded border px-1">→</kbd> to step. Click the star to see its light split into colours.
          </p>
        )}
        {pick && (
          <Card className="bg-card/70">
            <CardHeader className="pb-2"><CardTitle className="text-base">Spectrum at the point you clicked</CardTitle></CardHeader>
            <CardContent><SpectrumChart data={spec.data} error={spec.error} /></CardContent>
          </Card>
        )}
      </div>
    )
  }

  // ======================= RESEARCHER =======================
  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
        <div className="lg:w-[30rem]"><CoordinateInput onSubmit={onSearch} busy={targetQ.isLoading} /></div>
        <div className="flex flex-1 flex-wrap items-center gap-2">
          {centre && <span className="text-sm font-semibold">{title}</span>}
          {centre && <span className="font-mono text-xs text-muted-foreground">{centre.ra.toFixed(5)}°, {centre.dec.toFixed(5)}°</span>}
          {pm && <span className="text-xs text-muted-foreground">μ = {(Math.hypot(pm.pmra, pm.pmdec) / 1000).toFixed(2)}″/yr</span>}
        </div>
        <ReleasePicker value={state.releases} onChange={(r) => update({ releases: r })} />
        <ExportMenu state={state} hash={job?.status === "done" ? job.request_hash : null} frameId={current?.meta.id ?? null} />
      </div>

      <div className="grid gap-3 lg:grid-cols-[15rem_1fr_17rem]">
        <aside className="space-y-5 rounded-lg border border-border/60 bg-card/60 p-3">
          <BandSelector band={state.band} update={update} />
          <FovControl fov={state.fov} update={update} />
          <ModeSelector state={state} update={update} />
          <StretchControls state={state} update={update} />
          <OverlayToggles state={state} update={update} hasPm={!!pm} />
        </aside>

        <main className="min-w-0 space-y-3" id="main" tabIndex={-1}>
          {status}
          <div className="overflow-auto rounded-lg border border-border/60 bg-black/60 p-2">
            {canvas ?? <div className="flex h-72 items-center justify-center text-sm text-muted-foreground"><Telescope className="mr-2 h-5 w-5" />Frames will appear here</div>}
          </div>
          {playback}
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList>
              <TabsTrigger value="spectrum">Spectrum</TabsTrigger>
              <TabsTrigger value="lightcurve">Light curve</TabsTrigger>
              <TabsTrigger value="exposures">Frames table</TabsTrigger>
            </TabsList>
            <TabsContent value="spectrum" className="rounded-lg border border-border/60 bg-card/60 p-3">
              {pick ? <SpectrumChart data={spec.data} error={spec.error} /> : <ClickHint />}
            </TabsContent>
            <TabsContent value="lightcurve" className="rounded-lg border border-border/60 bg-card/60 p-3">
              <div className="mb-2 flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Band</span>
                <Select value={effLcBand} onValueChange={setLcBand}>
                  <SelectTrigger className="h-7 w-28 text-xs" aria-label="Light curve band"><SelectValue /></SelectTrigger>
                  <SelectContent>{DETECTORS.map((d) => <SelectItem key={d.id} value={d.id} className="text-xs">{d.id} ({d.range})</SelectItem>)}{effLcBand.startsWith("WL:") && <SelectItem value={effLcBand} className="text-xs">{effLcBand}</SelectItem>}</SelectContent>
                </Select>
                <InfoTip text="Brightness over time measured in one detector. Variable stars change between epochs." />
              </div>
              {pick ? <LightCurveChart data={lc.data} error={lc.error} /> : <ClickHint />}
            </TabsContent>
            <TabsContent value="exposures" className="overflow-x-auto rounded-lg border border-border/60 bg-card/60 p-3">
              <table className="w-full text-left text-xs">
                <thead className="text-muted-foreground"><tr><th className="p-1">#</th><th className="p-1">Date</th><th className="p-1">Exposures</th><th className="p-1">Detectors</th><th className="p-1">λ (µm)</th><th className="p-1">Release</th></tr></thead>
                <tbody>
                  {metas.map((m, i) => (
                    <tr key={m.id} className={`cursor-pointer border-t border-border/40 ${i === pb.index ? "bg-primary/10" : ""}`} onClick={() => { pb.setPlaying(false); pb.setIndex(i) }}>
                      <td className="p-1">{i + 1}</td><td className="p-1 font-mono">{m.date_mid.slice(0, 10)}</td><td className="p-1">{m.n_exposures}</td>
                      <td className="p-1 font-mono">{Object.entries(m.detectors).map(([d, n]) => `${d}:${n}`).join(" ")}</td>
                      <td className="p-1">{m.lambda_um?.toFixed(2) ?? "–"}</td><td className="p-1">{m.releases.join(",").toUpperCase()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {job?.info.n_exposures_found !== undefined && (
                <p className="mt-2 text-xs text-muted-foreground">{job.info.n_exposures_found} exposures cover this position; {job.info.n_selected} match the band. {job.info.cached ? "Served from cache." : job.info.seconds ? `Built in ${job.info.seconds} s.` : ""}</p>
              )}
            </TabsContent>
          </Tabs>
        </main>

        <aside className="space-y-3">
          <Card className="bg-card/60">
            <CardHeader className="pb-2"><CardTitle className="text-sm">This frame</CardTitle></CardHeader>
            <CardContent><MetadataPanel frame={current?.meta} total={loaded.length} /></CardContent>
          </Card>
          {centre && (
            <Card className="bg-card/60">
              <CardHeader className="pb-2"><CardTitle className="flex items-center gap-1 text-sm">Sky context <InfoTip text="Aladin Lite shows older surveys of the same area for comparison. The box is the SPHEREx field." /></CardTitle></CardHeader>
              <CardContent><AladinPanel ra={centre.ra} dec={centre.dec} fovArcsec={state.fov} /></CardContent>
            </Card>
          )}
        </aside>
      </div>
    </div>
  )
}

function ClickHint() {
  return <p className="py-6 text-center text-sm text-muted-foreground">Click a star in the image to measure its spectrum and light curve in every SPHEREx exposure.</p>
}

function ReleasePicker({ value, onChange }: { value: string[] | null; onChange: (r: string[] | null) => void }) {
  const q = useQuery({ queryKey: ["releases"], queryFn: api.releases, staleTime: Infinity })
  const active = (q.data ?? []).filter((r) => r.is_active)
  const v = value?.join(",") ?? "all"
  return (
    <div className="flex items-center gap-1">
      <Select value={v} onValueChange={(x) => onChange(x === "all" ? null : x.split(","))}>
        <SelectTrigger className="h-8 w-40 text-xs" aria-label="Data releases"><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value="all" className="text-xs">All releases ({active.map((r) => r.id.toUpperCase()).join("+") || "…"})</SelectItem>
          {active.map((r) => <SelectItem key={r.id} value={r.id} className="text-xs">{r.label} only</SelectItem>)}
        </SelectContent>
      </Select>
      <InfoTip text="SPHEREx data come in releases. DR1 holds 2025 to mid-2026; QR3 holds newer exposures. Using all gives the longest time span." />
    </div>
  )
}

function StatusBox({ hasCentre, resolving, resolveError, running, stage, progress, error, reason, haveFrames, variant }: {
  hasCentre: boolean; resolving: boolean; resolveError: string | null; running: boolean; stage: string; progress: number
  error: string | null; reason: string | null; haveFrames: boolean; variant: Variant
}) {
  if (resolveError) return <Alert text={resolveError} />
  if (error) return <Alert text={error} />
  if (reason) return <Alert text={reason} soft />
  if (resolving) return <Info text="Looking up the object…" spin />
  if (!hasCentre) {
    return variant === "embed" ? <Info text="No position given." /> : (
      <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        Type a star name or coordinates above, or pick a <Link href="/targets" className="text-primary underline">featured target</Link>.
      </div>
    )
  }
  if (running) {
    return (
      <div className="space-y-1 rounded-lg border border-border/60 bg-card/60 p-3">
        <div className="flex items-center gap-2 text-sm"><Loader2 className="h-4 w-4 animate-spin" />{stage || "working"}{haveFrames ? " — first frames are ready below" : ""}</div>
        <Progress value={progress * 100} className="h-1.5" />
        {!haveFrames && <p className="text-xs text-muted-foreground">The first time a field is opened, every SPHEREx exposure is downloaded from NASA&apos;s IRSA archive (about a minute). After that it is cached and instant.</p>}
      </div>
    )
  }
  return null
}

function Alert({ text, soft }: { text: string; soft?: boolean }) {
  return (
    <div className={`flex items-start gap-2 rounded-lg border p-3 text-sm ${soft ? "border-amber-500/50 bg-amber-500/10" : "border-destructive/60 bg-destructive/10"}`} role="alert">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{text}
    </div>
  )
}

function Info({ text, spin }: { text: string; spin?: boolean }) {
  return <div className="flex items-center gap-2 text-sm text-muted-foreground">{spin && <Loader2 className="h-4 w-4 animate-spin" />}{text}</div>
}

function WhatAmILookingAt({ target }: { target: Target | null }) {
  return (
    <Sheet>
      <SheetTrigger asChild><Button variant="outline" size="sm">What am I looking at?</Button></SheetTrigger>
      <SheetContent className="overflow-y-auto">
        <SheetHeader>
          <SheetTitle>What am I looking at?</SheetTitle>
          <SheetDescription>A short guide to the flip-book.</SheetDescription>
        </SheetHeader>
        <div className="space-y-3 px-4 pb-6 text-sm">
          {target && <p><b>{target.name}.</b> {target.description}</p>}
          <p>Each picture is a <b>3-arcminute patch of sky</b> (about a tenth of the Moon&apos;s width) photographed by NASA&apos;s <b>SPHEREx</b> telescope in infrared light, which our eyes cannot see.</p>
          <p>SPHEREx scans the whole sky every six months. The flip-book shows the <b>same patch at different dates</b>. Everything far away stays put; <b>nearby stars and brown dwarfs shift a little</b>, and some stars <b>change brightness</b>.</p>
          <p>The <span style={{ color: "#D55E00" }}>red crosshair</span> marks where the catalogues say the target should be on each date. The <span style={{ color: "#F0E442" }}>yellow arrow</span> shows where it will go in 10 years.</p>
          <p>Each square pixel is 6 arcseconds wide. Barnard&apos;s Star moves about one pixel every six months, so watch carefully!</p>
          <p><Link href="/learn" className="text-primary underline">Learn more about the science →</Link></p>
        </div>
      </SheetContent>
    </Sheet>
  )
}
