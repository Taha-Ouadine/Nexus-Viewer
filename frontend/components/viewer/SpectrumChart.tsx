"use client"

import { useMemo, useState } from "react"
import {
  CartesianGrid, ErrorBar, Legend, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from "recharts"
import { Loader2 } from "lucide-react"
import { Progress } from "@/components/ui/progress"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import { isPending } from "@/lib/api"
import type { LightCurveResponse, Pending, SpectrumResponse } from "@/lib/types"
import { mjdToISODate } from "@/lib/coords"

// Okabe-Ito colours, one per epoch
const EPOCH_COLORS = ["#56B4E9", "#E69F00", "#009E73", "#CC79A7", "#F0E442", "#0072B2", "#D55E00", "#999999"]

function Waiting({ data, error, what }: { data: unknown; error: unknown; what: string }) {
  if (error) return <p className="text-sm text-destructive">Could not measure the {what}: {(error as Error).message}</p>
  const p = data && isPending(data) ? (data as Pending) : null
  return (
    <div className="space-y-2 py-6 text-center text-sm text-muted-foreground">
      <Loader2 className="mx-auto h-5 w-5 animate-spin" />
      <p>{p ? p.stage : "Starting…"} — measuring the star in every SPHEREx exposure (first time can take a minute or two).</p>
      {p && <Progress value={p.progress * 100} className="mx-auto h-1.5 max-w-sm" />}
    </div>
  )
}

export function SpectrumChart({ data, error }: { data: SpectrumResponse | Pending | undefined; error: unknown }) {
  const [logY, setLogY] = useState(false)
  const [binned, setBinned] = useState(false)
  const series = useMemo(() => {
    if (!data || isPending(data)) return []
    const s = data as SpectrumResponse
    return s.epochs.map((e) => ({
      name: `${mjdToISODate(e.t_start)}…`,
      color: EPOCH_COLORS[e.index % EPOCH_COLORS.length],
      good: s.points.filter((p) => p.epoch === e.index && !p.flagged && p.lambda_um)
        .map((p) => ({ x: p.lambda_um as number, y: p.flux_uJy, err: p.err_uJy })),
    }))
  }, [data])
  if (!data || isPending(data) || error) return <Waiting data={data} error={error} what="spectrum" />
  const s = data as SpectrumResponse
  const flagged = s.points.filter((p) => p.flagged && p.lambda_um).map((p) => ({ x: p.lambda_um as number, y: p.flux_uJy, err: p.err_uJy }))
  const pos = (arr: { y: number }[]) => (logY ? arr.filter((p) => p.y > 0) : arr)
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
        <span>{s.points.length} measurements from {s.n_exposures} exposures{s.n_exposures_found && s.n_exposures_found > s.n_exposures ? ` (thinned from ${s.n_exposures_found})` : ""} · aperture {s.aperture_arcsec}″{s.pm_tracked ? " · following the target's motion" : ""}</span>
        <div className="flex items-center gap-1.5"><Switch id="logy" checked={logY} onCheckedChange={setLogY} /><Label htmlFor="logy" className="text-xs">log scale</Label></div>
        <div className="flex items-center gap-1.5"><Switch id="binned" checked={binned} onCheckedChange={setBinned} /><Label htmlFor="binned" className="text-xs">102-channel average</Label></div>
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <ScatterChart margin={{ top: 10, right: 20, bottom: 30, left: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334" />
          <XAxis type="number" dataKey="x" name="wavelength" unit=" µm" domain={[0.7, 5.05]} tickCount={10}
            label={{ value: "Wavelength (µm)", position: "insideBottom", offset: -18, fill: "#aab" }} stroke="#aab" />
          <YAxis type="number" dataKey="y" name="flux" unit=" µJy" scale={logY ? "log" : "auto"} domain={logY ? ["auto", "auto"] : undefined}
            allowDataOverflow stroke="#aab" width={80} tickFormatter={(v: number) => (Math.abs(v) >= 1e4 ? v.toExponential(0) : String(Math.round(v)))} />
          <Tooltip cursor={{ strokeDasharray: "3 3" }} formatter={(v: number) => v.toPrecision(4)} contentStyle={{ background: "#111827", border: "1px solid #334" }} />
          <Legend verticalAlign="top" height={24} />
          {binned ? (
            <Scatter name="102-channel average" data={pos(s.binned.map((b) => ({ x: b.lambda_um, y: b.flux_uJy, err: b.err_uJy })))} fill="#F0E442">
              <ErrorBar dataKey="err" width={0} stroke="#F0E442" direction="y" />
            </Scatter>
          ) : (
            series.map((ser) => (
              <Scatter key={ser.name} name={ser.name} data={pos(ser.good)} fill={ser.color} shape="circle">
                <ErrorBar dataKey="err" width={0} stroke={ser.color} direction="y" />
              </Scatter>
            ))
          )}
          {!binned && flagged.length > 0 && <Scatter name="flagged" data={pos(flagged)} fill="#666" shape="cross" />}
        </ScatterChart>
      </ResponsiveContainer>
      <p className="mt-1 text-xs text-muted-foreground">
        Each dot is one exposure: SPHEREx&apos;s filters change colour across the detector, so every snapshot sees the star at a slightly different wavelength. Grey crosses had flagged pixels in the aperture.
      </p>
    </div>
  )
}

export function LightCurveChart({ data, error }: { data: LightCurveResponse | Pending | undefined; error: unknown }) {
  if (!data || isPending(data) || error) return <Waiting data={data} error={error} what="light curve" />
  const lc = data as LightCurveResponse
  const pts = lc.points.filter((p) => !p.flagged).map((p) => ({ x: p.t_mid, y: p.flux_uJy, err: p.err_uJy }))
  const flagged = lc.points.filter((p) => p.flagged).map((p) => ({ x: p.t_mid, y: p.flux_uJy }))
  const ep = lc.per_epoch.map((p) => ({ x: p.t_mid, y: p.flux_uJy, err: Math.max(p.err_uJy, p.scatter_uJy / Math.sqrt(p.n)) }))
  const change = lc.per_epoch.length >= 2
    ? Math.max(...lc.per_epoch.map((p) => p.flux_uJy)) / Math.max(1e-9, Math.min(...lc.per_epoch.map((p) => p.flux_uJy)))
    : null
  return (
    <div>
      <div className="mb-2 text-xs text-muted-foreground">
        Band {lc.band}: {lc.points.length} measurements, {lc.per_epoch.length} epochs
        {change && Number.isFinite(change) && change > 0 ? ` · brightest/faintest epoch ratio ${change.toFixed(2)}×` : ""}
        {lc.per_epoch.some((p) => p.flagged) && (
          <span className="block text-amber-400">This star is bright enough to saturate SPHEREx here: epoch averages use flagged (saturated) measurements, so treat the absolute numbers with care — changes between epochs are still meaningful.</span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <ScatterChart margin={{ top: 10, right: 20, bottom: 30, left: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334" />
          <XAxis type="number" dataKey="x" name="date" domain={["auto", "auto"]} stroke="#aab"
            tickFormatter={(v: number) => mjdToISODate(v).slice(0, 7)}
            label={{ value: "Date", position: "insideBottom", offset: -18, fill: "#aab" }} />
          <YAxis type="number" dataKey="y" name="flux" unit=" µJy" stroke="#aab" width={80}
            tickFormatter={(v: number) => (Math.abs(v) >= 1e4 ? v.toExponential(0) : String(Math.round(v)))} />
          <Tooltip formatter={(v: number, n: string) => (n === "date" ? mjdToISODate(v) : v.toPrecision(4))} contentStyle={{ background: "#111827", border: "1px solid #334" }} />
          <Legend verticalAlign="top" height={24} />
          <Scatter name="single exposures" data={pts} fill="#56B4E9" opacity={0.6}>
            <ErrorBar dataKey="err" width={0} stroke="#56B4E9" direction="y" />
          </Scatter>
          {flagged.length > 0 && <Scatter name="flagged" data={flagged} fill="#666" shape="cross" />}
          <Scatter name="epoch average" data={ep} fill="#E69F00" shape="diamond" line={{ stroke: "#E69F00" }}>
            <ErrorBar dataKey="err" width={4} stroke="#E69F00" direction="y" />
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
      <p className="mt-1 text-xs text-muted-foreground">
        Inside one band the exact wavelength changes from exposure to exposure, so some scatter is the star&apos;s colour, not a real change. Big differences between epochs (orange) are real variability.
      </p>
    </div>
  )
}
