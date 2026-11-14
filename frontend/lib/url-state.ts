// Viewer state <-> URL query string (WiseView-style names). Round-trips losslessly.
import type { Diff, Mode, StretchKind } from "./types"
import { parseDec, parseRA } from "./coords"

export interface ViewerState {
  ra: number | null
  dec: number | null
  target: string | null // slug or free-text name, resolved by the app
  fov: number
  band: string
  mode: Mode
  diff: Diff
  window: number
  speed: number
  stretch: StretchKind
  min: string // "p0.5" or a number as string
  max: string
  invert: boolean
  zoom: number
  smooth: boolean
  gaia: boolean
  wise: boolean
  flags: boolean
  pm: boolean
  crosshair: boolean
  track: boolean
  zodi: boolean
  releases: string[] | null
}

export const DEFAULT_STATE: ViewerState = {
  ra: null,
  dec: null,
  target: null,
  fov: 180,
  band: "ALL",
  mode: "epochs",
  diff: "none",
  window: 30,
  speed: 500,
  stretch: "asinh",
  min: "p0.5",
  max: "p99.5",
  invert: false,
  zoom: 6,
  smooth: false,
  gaia: false,
  wise: false,
  flags: false,
  pm: true,
  crosshair: true,
  track: false,
  zodi: true,
  releases: null,
}

const MODES: Mode[] = ["epochs", "exposures", "stack"]
const DIFFS: Diff[] = ["none", "first", "previous", "mean"]
const STRETCHES: StretchKind[] = ["linear", "asinh", "log", "sqrt", "zscale"]
const BOOL_KEYS = ["invert", "smooth", "gaia", "wise", "flags", "pm", "crosshair", "track", "zodi"] as const

function num(v: string | null, fallback: number, min: number, max: number): number {
  if (v === null || v === "") return fallback
  const x = Number(v)
  return Number.isFinite(x) ? Math.min(max, Math.max(min, x)) : fallback
}

function pick<T extends string>(v: string | null, allowed: T[], fallback: T): T {
  return v !== null && (allowed as string[]).includes(v) ? (v as T) : fallback
}

function limitSpec(v: string | null, fallback: string): string {
  if (!v) return fallback
  if (/^p\d+(\.\d+)?$/.test(v) || Number.isFinite(Number(v))) return v
  return fallback
}

export function parseViewerState(params: URLSearchParams): ViewerState {
  const s: ViewerState = { ...DEFAULT_STATE }
  const ra = params.get("ra")
  const dec = params.get("dec")
  s.ra = ra !== null ? parseRA(ra) : null
  s.dec = dec !== null ? parseDec(dec) : null
  s.target = params.get("target")
  s.fov = num(params.get("fov"), s.fov, 30, 1800)
  s.band = params.get("band") || s.band
  s.mode = pick(params.get("mode"), MODES, s.mode)
  s.diff = pick(params.get("diff"), DIFFS, s.diff)
  s.window = num(params.get("window"), s.window, 0.5, 400)
  s.speed = num(params.get("speed"), s.speed, 50, 2000)
  s.stretch = pick(params.get("stretch"), STRETCHES, s.stretch)
  s.min = limitSpec(params.get("min"), s.min)
  s.max = limitSpec(params.get("max"), s.max)
  s.zoom = num(params.get("zoom"), s.zoom, 1, 16)
  for (const k of BOOL_KEYS) {
    const v = params.get(k)
    if (v !== null) s[k] = v === "1" || v === "true"
  }
  const rel = params.get("releases")
  s.releases = rel ? rel.split(",").map((r) => r.trim().toLowerCase()).filter(Boolean) : null
  return s
}

/** Only non-default values are written, so URLs stay short. */
export function serializeViewerState(s: ViewerState): URLSearchParams {
  const p = new URLSearchParams()
  if (s.target) p.set("target", s.target)
  if (s.ra !== null) p.set("ra", String(Number(s.ra.toFixed(6))))
  if (s.dec !== null) p.set("dec", String(Number(s.dec.toFixed(6))))
  const d = DEFAULT_STATE
  if (s.fov !== d.fov) p.set("fov", String(s.fov))
  if (s.band !== d.band) p.set("band", s.band)
  if (s.mode !== d.mode) p.set("mode", s.mode)
  if (s.diff !== d.diff) p.set("diff", s.diff)
  if (s.window !== d.window) p.set("window", String(s.window))
  if (s.speed !== d.speed) p.set("speed", String(s.speed))
  if (s.stretch !== d.stretch) p.set("stretch", s.stretch)
  if (s.min !== d.min) p.set("min", s.min)
  if (s.max !== d.max) p.set("max", s.max)
  if (s.zoom !== d.zoom) p.set("zoom", String(s.zoom))
  for (const k of BOOL_KEYS) if (s[k] !== d[k]) p.set(k, s[k] ? "1" : "0")
  if (s.releases && s.releases.length) p.set("releases", s.releases.join(","))
  return p
}

export function viewerUrl(path: string, s: ViewerState): string {
  const q = serializeViewerState(s).toString()
  return q ? `${path}?${q}` : path
}
