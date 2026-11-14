// Contrast stretching done in the browser so sliders respond instantly.
// Mirrors backend/app/services/render.py.
import type { StretchKind } from "./types"

/** Percentile of finite values (p in 0..100). Uses a sorted sample for speed. */
export function percentile(values: ArrayLike<number>, p: number, maxSample = 20000): number {
  const finite: number[] = []
  const step = Math.max(1, Math.floor(values.length / maxSample))
  for (let i = 0; i < values.length; i += step) {
    const v = values[i]
    if (Number.isFinite(v)) finite.push(v)
  }
  if (finite.length === 0) return 0
  finite.sort((a, b) => a - b)
  const idx = Math.min(finite.length - 1, Math.max(0, (p / 100) * (finite.length - 1)))
  const lo = Math.floor(idx)
  const hi = Math.ceil(idx)
  return finite[lo] + (finite[hi] - finite[lo]) * (idx - lo)
}

/** Simplified zscale: fit a line through the sorted sample around its median. */
export function zscale(values: ArrayLike<number>, contrast = 0.25): [number, number] {
  const finite: number[] = []
  const step = Math.max(1, Math.floor(values.length / 2000))
  for (let i = 0; i < values.length; i += step) if (Number.isFinite(values[i])) finite.push(values[i])
  if (finite.length < 5) return [0, 1]
  finite.sort((a, b) => a - b)
  const n = finite.length
  const med = finite[Math.floor(n / 2)]
  // least-squares slope of value vs index
  let sx = 0, sy = 0, sxx = 0, sxy = 0
  for (let i = 0; i < n; i++) { sx += i; sy += finite[i]; sxx += i * i; sxy += i * finite[i] }
  const slope = (n * sxy - sx * sy) / (n * sxx - sx * sx || 1)
  const lo = Math.max(finite[0], med - (slope / contrast) * Math.floor(n / 2))
  const hi = Math.min(finite[n - 1], med + (slope / contrast) * (n - Math.floor(n / 2)))
  return [lo, hi > lo ? hi : lo + 1e-6]
}

/** Map a value to 0..1 with the chosen stretch. */
export function stretchValue(v: number, lo: number, hi: number, kind: StretchKind, invert = false): number {
  const span = hi > lo ? hi - lo : 1
  let x = Number.isFinite(v) ? (v - lo) / span : 0
  x = x < 0 ? 0 : x > 1 ? 1 : x
  if (kind === "asinh") x = Math.asinh(10 * x) / Math.asinh(10)
  else if (kind === "log") x = Math.log10(1 + 1000 * x) / Math.log10(1001)
  else if (kind === "sqrt") x = Math.sqrt(x)
  return invert ? 1 - x : x
}

/** Build a 256-entry lookup is not possible for float input, so we stretch per pixel. */
export function stretchToRGBA(
  channels: Float32Array[], width: number, height: number,
  lo: number[], hi: number[], kind: StretchKind, invert: boolean,
  out?: Uint8ClampedArray,
): Uint8ClampedArray {
  const n = width * height
  const rgba = out ?? new Uint8ClampedArray(n * 4)
  const k: StretchKind = kind === "zscale" ? "linear" : kind
  if (channels.length === 1) {
    const c = channels[0]
    for (let i = 0; i < n; i++) {
      const v = c[i]
      const g = Number.isFinite(v) ? Math.round(255 * stretchValue(v, lo[0], hi[0], k, invert)) : 0
      rgba[i * 4] = g
      rgba[i * 4 + 1] = g
      rgba[i * 4 + 2] = g
      rgba[i * 4 + 3] = Number.isFinite(v) ? 255 : 60
    }
  } else {
    // channels are given in (blue, green, red) order, like the band string RGB:<b>,<g>,<r>
    const [b, g, r] = channels
    for (let i = 0; i < n; i++) {
      rgba[i * 4] = Math.round(255 * stretchValue(r[i], lo[2], hi[2], k, invert))
      rgba[i * 4 + 1] = Math.round(255 * stretchValue(g[i], lo[1], hi[1], k, invert))
      rgba[i * 4 + 2] = Math.round(255 * stretchValue(b[i], lo[0], hi[0], k, invert))
      rgba[i * 4 + 3] = 255
    }
  }
  return rgba
}

/** Resolve a limit spec: "p99.5" -> percentile, "1.23" -> number. */
export function resolveLimit(spec: string, values: ArrayLike<number>): number {
  if (spec.startsWith("p")) return percentile(values, parseFloat(spec.slice(1)))
  const v = parseFloat(spec)
  return Number.isFinite(v) ? v : 0
}
