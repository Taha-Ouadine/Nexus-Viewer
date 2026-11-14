"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { pixelToWorld, propagate, worldToPixel, formatRA, formatDec } from "@/lib/coords"
import { stretchToRGBA } from "@/lib/stretch"
import type { CatalogResponse, FrameMeta, StretchKind } from "@/lib/types"

// Okabe-Ito colour-blind-safe palette
export const COLORS = {
  target: "#D55E00", // vermillion
  gaia: "#56B4E9", // sky blue
  wise: "#E69F00", // orange
  pm: "#F0E442", // yellow
  pick: "#009E73", // green
  text: "#FFFFFF",
}

// flag families for the mask overlay
const FLAG_FAMILIES: { bits: number[]; rgba: [number, number, number, number] }[] = [
  { bits: [1, 15, 26, 27, 28], rgba: [213, 94, 0, 150] }, // saturation / nonlinear / bloom / snowball / halo
  { bits: [22, 23, 24, 25], rgba: [204, 121, 167, 150] }, // ghosts / streaks
  { bits: [0, 17, 19, 20], rgba: [240, 228, 66, 140] }, // transient / persistence / outlier / crosstalk
  { bits: [6, 7, 9, 10, 11, 14], rgba: [86, 180, 233, 140] }, // detector defects
]

export interface DisplaySettings {
  lo: number[]
  hi: number[]
  stretch: StretchKind
  invert: boolean
  zoom: number
  smooth: boolean
}

export interface OverlaySettings {
  crosshair: boolean
  pmVector: boolean
  flags: boolean
  badMask: number
  gaia: CatalogResponse | null
  wise: CatalogResponse | null
  pm: { pmra: number; pmdec: number } | null
  scaleBar: boolean
}

interface Props {
  meta: FrameMeta
  channels: Float32Array[]
  flags?: Uint32Array
  display: DisplaySettings
  overlays: OverlaySettings
  pick: { ra: number; dec: number } | null
  onPick?: (ra: number, dec: number, nearTarget: boolean) => void
  className?: string
  maxCssSize?: number
  /** scale the image up to fill maxCssSize (Explorer / embed) */
  fit?: boolean
}

export function FrameCanvas({ meta, channels, flags, display, overlays, pick, onPick, className, maxCssSize, fit }: Props) {
  const imgRef = useRef<HTMLCanvasElement>(null)
  const ovRef = useRef<HTMLCanvasElement>(null)
  const [hover, setHover] = useState<{ x: number; y: number; ra: number; dec: number; v: number } | null>(null)
  const w = meta.width
  const h = meta.height
  const zoom = maxCssSize
    ? Math.max(1, fit ? Math.floor(maxCssSize / w) : Math.min(display.zoom, Math.floor(maxCssSize / w)))
    : display.zoom
  const cssW = w * zoom
  const cssH = h * zoom

  // ---- image layer (native resolution; CSS scales it up) ----
  useEffect(() => {
    const c = imgRef.current
    if (!c || channels.length === 0) return
    c.width = w
    c.height = h
    const ctx = c.getContext("2d")
    if (!ctx) return
    const img = ctx.createImageData(w, h)
    stretchToRGBA(channels, w, h, display.lo, display.hi, display.stretch, display.invert, img.data)
    if (overlays.flags && flags && flags.length === w * h) {
      for (let i = 0; i < w * h; i++) {
        const f = flags[i] & overlays.badMask
        if (!f) continue
        for (const fam of FLAG_FAMILIES) {
          if (fam.bits.some((b) => f & (1 << b))) {
            const a = fam.rgba[3] / 255
            img.data[i * 4] = img.data[i * 4] * (1 - a) + fam.rgba[0] * a
            img.data[i * 4 + 1] = img.data[i * 4 + 1] * (1 - a) + fam.rgba[1] * a
            img.data[i * 4 + 2] = img.data[i * 4 + 2] * (1 - a) + fam.rgba[2] * a
            break
          }
        }
      }
    }
    ctx.putImageData(img, 0, 0)
  }, [channels, flags, w, h, display.lo, display.hi, display.stretch, display.invert, overlays.flags, overlays.badMask])

  // catalog sources moved to this frame's date
  const gaiaPix = useMemo(() => project(overlays.gaia, meta), [overlays.gaia, meta])
  const wisePix = useMemo(() => project(overlays.wise, meta), [overlays.wise, meta])

  // ---- vector overlay layer (CSS resolution) ----
  useEffect(() => {
    const c = ovRef.current
    if (!c) return
    const dpr = typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1
    c.width = cssW * dpr
    c.height = cssH * dpr
    const ctx = c.getContext("2d")
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, cssW, cssH)
    const P = (x: number) => (x + 0.5) * zoom // pixel centre -> css

    ctx.lineWidth = 1.5
    if (gaiaPix.length) {
      ctx.strokeStyle = COLORS.gaia
      for (const s of gaiaPix) {
        ctx.beginPath()
        ctx.arc(P(s.x), P(s.y), Math.max(4, 1.2 * zoom), 0, Math.PI * 2)
        ctx.stroke()
      }
    }
    if (wisePix.length) {
      ctx.strokeStyle = COLORS.wise
      for (const s of wisePix) {
        const r = Math.max(5, 1.5 * zoom)
        ctx.beginPath()
        ctx.moveTo(P(s.x), P(s.y) - r)
        ctx.lineTo(P(s.x) + r, P(s.y))
        ctx.lineTo(P(s.x), P(s.y) + r)
        ctx.lineTo(P(s.x) - r, P(s.y))
        ctx.closePath()
        ctx.stroke()
      }
    }
    if (overlays.crosshair && meta.target) {
      const x = P(meta.target.x)
      const y = P(meta.target.y)
      const gap = Math.max(6, 2.5 * zoom)
      const len = Math.max(10, 4 * zoom)
      ctx.strokeStyle = COLORS.target
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(x - gap - len, y); ctx.lineTo(x - gap, y)
      ctx.moveTo(x + gap, y); ctx.lineTo(x + gap + len, y)
      ctx.moveTo(x, y - gap - len); ctx.lineTo(x, y - gap)
      ctx.moveTo(x, y + gap); ctx.lineTo(x, y + gap + len)
      ctx.stroke()
    }
    if (overlays.pmVector && meta.target && overlays.pm && (overlays.pm.pmra || overlays.pm.pmdec)) {
      // arrow showing where the target goes in 10 years
      const scale = meta.grid.scale_arcsec
      const dx = (-overlays.pm.pmra / 1000) * 10 / scale // east is left
      const dy = (-overlays.pm.pmdec / 1000) * 10 / scale // north is up
      const x0 = P(meta.target.x)
      const y0 = P(meta.target.y)
      const x1 = x0 + dx * zoom
      const y1 = y0 + dy * zoom
      ctx.strokeStyle = COLORS.pm
      ctx.fillStyle = COLORS.pm
      ctx.lineWidth = 2
      ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke()
      const ang = Math.atan2(y1 - y0, x1 - x0)
      ctx.beginPath()
      ctx.moveTo(x1, y1)
      ctx.lineTo(x1 - 9 * Math.cos(ang - 0.4), y1 - 9 * Math.sin(ang - 0.4))
      ctx.lineTo(x1 - 9 * Math.cos(ang + 0.4), y1 - 9 * Math.sin(ang + 0.4))
      ctx.closePath(); ctx.fill()
      ctx.font = "11px sans-serif"
      ctx.fillText("10 yr", x1 + 4, y1 - 4)
    }
    if (pick) {
      const p = worldToPixel(meta.grid, pick.ra, pick.dec)
      ctx.strokeStyle = COLORS.pick
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.arc(P(p.x), P(p.y), Math.max(6, 2 * zoom), 0, Math.PI * 2)
      ctx.stroke()
    }
    if (overlays.scaleBar) {
      // scale bar (bottom-left) and compass (bottom-right)
      const arcsec = meta.grid.npix * meta.grid.scale_arcsec > 400 ? 120 : 30
      const len = (arcsec / meta.grid.scale_arcsec) * zoom
      ctx.strokeStyle = COLORS.text
      ctx.fillStyle = COLORS.text
      ctx.lineWidth = 2
      ctx.font = "11px sans-serif"
      ctx.beginPath(); ctx.moveTo(8, cssH - 10); ctx.lineTo(8 + len, cssH - 10); ctx.stroke()
      ctx.fillText(`${arcsec}″`, 8, cssH - 14)
      const cx = cssW - 14
      const cy = cssH - 12
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx, cy - 22); ctx.moveTo(cx, cy); ctx.lineTo(cx - 22, cy); ctx.stroke()
      ctx.fillText("N", cx - 3, cy - 25)
      ctx.fillText("E", cx - 33, cy + 4)
    }
  }, [cssW, cssH, zoom, meta, overlays, gaiaPix, wisePix, pick])

  function eventPixel(e: React.MouseEvent<HTMLDivElement>) {
    const r = e.currentTarget.getBoundingClientRect()
    const x = ((e.clientX - r.left) / r.width) * w - 0.5
    const y = ((e.clientY - r.top) / r.height) * h - 0.5
    return { x, y }
  }

  return (
    <div className={className}>
      <div
        className="relative mx-auto cursor-crosshair select-none bg-black"
        style={{ width: cssW, height: cssH }}
        onMouseMove={(e) => {
          const { x, y } = eventPixel(e)
          const s = pixelToWorld(meta.grid, x, y)
          const ix = Math.round(x)
          const iy = Math.round(y)
          const v = ix >= 0 && iy >= 0 && ix < w && iy < h ? channels[0]?.[iy * w + ix] ?? NaN : NaN
          setHover({ x, y, ra: s.ra, dec: s.dec, v })
        }}
        onMouseLeave={() => setHover(null)}
        onClick={(e) => {
          if (!onPick) return
          const { x, y } = eventPixel(e)
          const s = pixelToWorld(meta.grid, x, y)
          const near = !!meta.target && Math.hypot(x - meta.target.x, y - meta.target.y) <= 2.5
          onPick(s.ra, s.dec, near)
        }}
        role="img"
        aria-label={`SPHEREx frame ${meta.idx + 1}, ${meta.date_mid.slice(0, 10)}`}
      >
        <canvas
          ref={imgRef}
          className="absolute inset-0"
          style={{ width: cssW, height: cssH, imageRendering: display.smooth ? "auto" : "pixelated" }}
        />
        <canvas ref={ovRef} className="pointer-events-none absolute inset-0" style={{ width: cssW, height: cssH }} />
      </div>
      <div className="mt-1 h-5 text-center font-mono text-xs text-muted-foreground" aria-live="off">
        {hover
          ? `${formatRA(hover.ra, 2)} ${formatDec(hover.dec, 1)}  ·  ${hover.ra.toFixed(5)}°, ${hover.dec.toFixed(5)}°  ·  ${Number.isFinite(hover.v) ? hover.v.toPrecision(3) + " MJy/sr" : "no data"}`
          : "Hover for coordinates · click to measure spectrum & light curve"}
      </div>
    </div>
  )
}

/** Catalogue sources moved to the frame date and projected; only the `limit` brightest
 *  (catalogues come sorted by brightness) so crowded Milky Way fields stay readable. */
function project(cat: CatalogResponse | null, meta: FrameMeta, limit = 60): { x: number; y: number }[] {
  if (!cat) return []
  const out: { x: number; y: number }[] = []
  for (const s of cat.sources) {
    const p = propagate(s.ra, s.dec, s.pmra, s.pmdec, cat.ref_epoch, meta.t_mid)
    const px = worldToPixel(meta.grid, p.ra, p.dec)
    if (px.x >= -1 && px.y >= -1 && px.x <= meta.width && px.y <= meta.height) out.push(px)
    if (out.length >= limit) break
  }
  return out
}
