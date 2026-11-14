// Coordinate helpers: sexagesimal parsing/formatting, TAN projection, proper motion.
import type { GridWcs } from "./types"

const D2R = Math.PI / 180
const R2D = 180 / Math.PI
export const MJD_J2000 = 51544.5

/** Parse "133.795", "08h55m10.8s", "08:55:10.8" or "08 55 10.8" (hours) into degrees. */
export function parseRA(input: string): number | null {
  const s = input.trim().toLowerCase()
  if (!s) return null
  if (/^[+-]?\d+(\.\d+)?(d|deg)?$/.test(s)) {
    const v = parseFloat(s)
    return v >= 0 && v < 360 ? v : null
  }
  const parts = s.replace(/[hms:]/g, " ").trim().split(/\s+/).map(Number)
  if (parts.length < 2 || parts.length > 3 || parts.some((p) => Number.isNaN(p))) return null
  const [h, m, sec = 0] = parts
  if (h < 0 || h >= 24 || m < 0 || m >= 60 || sec < 0 || sec >= 60) return null
  return (h + m / 60 + sec / 3600) * 15
}

/** Parse "-7.245", "-07d14m42.5s", "-07:14:42.5" into degrees. */
export function parseDec(input: string): number | null {
  const s = input.trim().toLowerCase()
  if (!s) return null
  if (/^[+-]?\d+(\.\d+)?(d|deg)?$/.test(s)) {
    const v = parseFloat(s)
    return v >= -90 && v <= 90 ? v : null
  }
  const neg = s.startsWith("-")
  const parts = s.replace(/^[+-]/, "").replace(/[dms:'"°]/g, " ").trim().split(/\s+/).map(Number)
  if (parts.length < 2 || parts.length > 3 || parts.some((p) => Number.isNaN(p))) return null
  const [d, m, sec = 0] = parts
  if (d > 90 || m >= 60 || sec >= 60) return null
  const v = d + m / 60 + sec / 3600
  return neg ? -v : v
}

/** "133.795 -7.245" or "08h55m10.8s -07d14m42s" in one string. */
export function parseCoordPair(input: string): { ra: number; dec: number } | null {
  const s = input.trim().replace(/,/g, " ")
  // split at the sign of the declination, or at whitespace in the middle
  const m = s.match(/^(.+?)\s+([+-]?\d.*)$/)
  if (!m) return null
  const ra = parseRA(m[1])
  const dec = parseDec(m[2])
  return ra === null || dec === null ? null : { ra, dec }
}

function pad(n: number, w: number, dp = 0): string {
  const s = n.toFixed(dp)
  const [i, f] = s.split(".")
  return i.padStart(w, "0") + (f ? "." + f : "")
}

export function formatRA(deg: number, dp = 2): string {
  let t = (((deg % 360) + 360) % 360) / 15
  let h = Math.floor(t)
  t = (t - h) * 60
  let m = Math.floor(t)
  let s = Number(((t - m) * 60).toFixed(dp))
  if (s >= 60) { s = 0; m += 1 }
  if (m >= 60) { m = 0; h = (h + 1) % 24 }
  return `${pad(h, 2)}h${pad(m, 2)}m${pad(s, 2, dp)}s`
}

export function formatDec(deg: number, dp = 1): string {
  const sign = deg < 0 ? "-" : "+"
  let t = Math.abs(deg)
  let d = Math.floor(t)
  t = (t - d) * 60
  let m = Math.floor(t)
  let s = Number(((t - m) * 60).toFixed(dp))
  if (s >= 60) { s = 0; m += 1 }
  if (m >= 60) { m = 0; d += 1 }
  return `${sign}${pad(d, 2)}°${pad(m, 2)}′${pad(s, 2, dp)}″`
}

/** Sky -> frame pixel (col from left, row from TOP), for the north-up TAN grid of a frame. */
export function worldToPixel(w: GridWcs, ra: number, dec: number): { x: number; y: number } {
  const a0 = w.crval[0] * D2R
  const d0 = w.crval[1] * D2R
  const a = ra * D2R
  const d = dec * D2R
  const cosc = Math.sin(d0) * Math.sin(d) + Math.cos(d0) * Math.cos(d) * Math.cos(a - a0)
  const xi = (Math.cos(d) * Math.sin(a - a0)) / cosc
  const eta = (Math.cos(d0) * Math.sin(d) - Math.sin(d0) * Math.cos(d) * Math.cos(a - a0)) / cosc
  const xFits = w.crpix[0] + (xi * R2D) / w.cdelt[0] - 1 // 0-based
  const yFits = w.crpix[1] + (eta * R2D) / w.cdelt[1] - 1
  return { x: xFits, y: w.npix - 1 - yFits }
}

/** Frame pixel (col, row from top) -> sky. */
export function pixelToWorld(w: GridWcs, x: number, y: number): { ra: number; dec: number } {
  const yFits = w.npix - 1 - y
  const xi = (x + 1 - w.crpix[0]) * w.cdelt[0] * D2R
  const eta = (yFits + 1 - w.crpix[1]) * w.cdelt[1] * D2R
  const a0 = w.crval[0] * D2R
  const d0 = w.crval[1] * D2R
  const rho = Math.hypot(xi, eta)
  if (rho === 0) return { ra: w.crval[0], dec: w.crval[1] }
  const c = Math.atan(rho)
  const dec = Math.asin(Math.cos(c) * Math.sin(d0) + (eta * Math.sin(c) * Math.cos(d0)) / rho)
  const ra = a0 + Math.atan2(xi * Math.sin(c), rho * Math.cos(d0) * Math.cos(c) - eta * Math.sin(d0) * Math.sin(c))
  return { ra: (((ra * R2D) % 360) + 360) % 360, dec: dec * R2D }
}

/** Linear proper-motion propagation (mas/yr, pmra includes cos dec) from Julian year to MJD. */
export function propagate(
  ra: number, dec: number, pmra: number | null | undefined, pmdec: number | null | undefined,
  refEpoch: number, mjd: number,
): { ra: number; dec: number } {
  if (!pmra && !pmdec) return { ra, dec }
  const dtYr = (mjd - (MJD_J2000 + (refEpoch - 2000) * 365.25)) / 365.25
  const ddec = ((pmdec ?? 0) * dtYr) / 3.6e6
  const dra = ((pmra ?? 0) * dtYr) / 3.6e6 / Math.max(Math.cos(dec * D2R), 1e-6)
  return { ra: (((ra + dra) % 360) + 360) % 360, dec: dec + ddec }
}

export function mjdToDate(mjd: number): Date {
  return new Date((mjd - 40587) * 86400000)
}

export function mjdToISODate(mjd: number): string {
  return mjdToDate(mjd).toISOString().slice(0, 10)
}

export function jyearToMjd(y: number): number {
  return MJD_J2000 + (y - 2000) * 365.25
}
