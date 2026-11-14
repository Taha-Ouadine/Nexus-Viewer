import { describe, expect, it } from "vitest"
import { DEFAULT_STATE, parseViewerState, serializeViewerState, type ViewerState } from "./url-state"
import { formatDec, formatRA, parseCoordPair, parseDec, parseRA, pixelToWorld, propagate, worldToPixel, MJD_J2000 } from "./coords"
import { percentile, stretchValue, zscale } from "./stretch"
import type { GridWcs } from "./types"

describe("url-state", () => {
  it("round-trips a full state losslessly", () => {
    const s: ViewerState = {
      ...DEFAULT_STATE, ra: 133.79513, dec: -7.24515, target: "wise-0855", fov: 300, band: "RGB:D2,D4,D5+D6",
      mode: "exposures", diff: "first", window: 7, speed: 250, stretch: "log", min: "p1", max: "p99.9",
      invert: true, zoom: 8, smooth: true, gaia: true, wise: true, flags: true, pm: false, crosshair: false,
      track: true, zodi: false, releases: ["dr1", "qr3"],
    }
    const back = parseViewerState(new URLSearchParams(serializeViewerState(s).toString()))
    expect(back).toEqual(s)
  })
  it("defaults produce an empty query", () => {
    expect(serializeViewerState(DEFAULT_STATE).toString()).toBe("")
  })
  it("accepts the plan's example URL", () => {
    const s = parseViewerState(new URLSearchParams(
      "ra=133.79513&dec=-7.24515&fov=180&band=D6&mode=epochs&diff=none&window=30&speed=500&stretch=asinh&min=p0.5&max=p99.5&invert=0&zoom=4&gaia=1&wise=0&flags=0&pm=1&zodi=1&releases=dr1,qr3",
    ))
    expect(s.ra).toBeCloseTo(133.79513)
    expect(s.band).toBe("D6")
    expect(s.zoom).toBe(4)
    expect(s.gaia).toBe(true)
    expect(s.releases).toEqual(["dr1", "qr3"])
  })
  it("accepts sexagesimal coordinates and clamps junk", () => {
    const s = parseViewerState(new URLSearchParams("ra=08h55m10.831s&dec=-07d14m42.53s&zoom=999&mode=bogus"))
    expect(s.ra).toBeCloseTo(133.795129, 5)
    expect(s.dec).toBeCloseTo(-7.245147, 5)
    expect(s.zoom).toBe(16)
    expect(s.mode).toBe("epochs")
  })
})

describe("coords", () => {
  it("parses RA/Dec in several formats", () => {
    expect(parseRA("133.795")).toBeCloseTo(133.795)
    expect(parseRA("08:55:10.831")).toBeCloseTo(133.795129, 5)
    expect(parseRA("08 55 10.831")).toBeCloseTo(133.795129, 5)
    expect(parseDec("-07:14:42.53")).toBeCloseTo(-7.245147, 5)
    expect(parseDec("+66d45m17.9s")).toBeCloseTo(66.754972, 5)
    expect(parseRA("25h00m00s")).toBeNull()
    expect(parseDec("95")).toBeNull()
  })
  it("parses a pair", () => {
    expect(parseCoordPair("269.446 4.768")).toEqual({ ra: 269.446, dec: 4.768 })
    expect(parseCoordPair("08h55m10.8s -07d14m42s")?.dec).toBeLessThan(0)
    expect(parseCoordPair("Barnard's Star")).toBeNull()
  })
  it("formats and re-parses", () => {
    expect(parseRA(formatRA(133.795129, 3))).toBeCloseTo(133.795129, 5)
    expect(parseDec(formatDec(-7.245147, 2).replace("°", "d").replace("′", "m").replace("″", "s"))).toBeCloseTo(-7.245147, 5)
  })
  it("TAN projection is invertible, north up and east left", () => {
    const w: GridWcs = { ctype: ["RA---TAN", "DEC--TAN"], crval: [269.446, 4.768], crpix: [15, 15], cdelt: [-6.15 / 3600, 6.15 / 3600], npix: 29, scale_arcsec: 6.15, row0: "north" }
    const c = worldToPixel(w, 269.446, 4.768)
    expect(c.x).toBeCloseTo(14)
    expect(c.y).toBeCloseTo(14)
    const north = worldToPixel(w, 269.446, 4.768 + 6.15 / 3600)
    expect(north.y).toBeCloseTo(13, 3) // up = smaller row
    const east = worldToPixel(w, 269.446 + 6.15 / 3600 / Math.cos((4.768 * Math.PI) / 180), 4.768)
    expect(east.x).toBeCloseTo(13, 2) // east = left
    const back = pixelToWorld(w, 3.3, 20.7)
    const again = worldToPixel(w, back.ra, back.dec)
    expect(again.x).toBeCloseTo(3.3, 6)
    expect(again.y).toBeCloseTo(20.7, 6)
  })
  it("propagates proper motion like the backend", () => {
    const p = propagate(269.4520769586187, 4.69336496657667, -801.551, 10362.394, 2000, MJD_J2000 + 26 * 365.25)
    expect((p.dec - 4.69336496657667) * 3600).toBeCloseTo(10.362394 * 26, 6)
  })
})

describe("stretch", () => {
  it("percentile and zscale", () => {
    const a = Float32Array.from({ length: 1001 }, (_, i) => i)
    expect(percentile(a, 50)).toBeCloseTo(500)
    expect(percentile(a, 0)).toBe(0)
    const [lo, hi] = zscale(a)
    expect(lo).toBeLessThan(hi)
  })
  it("stretch functions are bounded and monotonic", () => {
    for (const k of ["linear", "asinh", "log", "sqrt"] as const) {
      let prev = -1
      for (let v = -0.5; v <= 1.5; v += 0.1) {
        const y = stretchValue(v, 0, 1, k)
        expect(y).toBeGreaterThanOrEqual(0)
        expect(y).toBeLessThanOrEqual(1)
        expect(y).toBeGreaterThanOrEqual(prev)
        prev = y
      }
    }
    expect(stretchValue(0, 0, 1, "linear", true)).toBe(1)
    expect(stretchValue(NaN, 0, 1, "linear")).toBe(0)
  })
})
