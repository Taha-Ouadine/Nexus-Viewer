"use client"

// The left-hand control panels of the Researcher viewer.
// (BandSelector, ModeSelector, StretchControls, OverlayToggles, FovControl.)

import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { ControlLabel, InfoTip } from "./InfoTip"
import type { ViewerState } from "@/lib/url-state"
import type { Diff, Mode, StretchKind } from "@/lib/types"

type Update = (patch: Partial<ViewerState>) => void

export const DETECTORS = [
  { id: "D1", range: "0.75–1.09 µm" },
  { id: "D2", range: "1.10–1.62 µm" },
  { id: "D3", range: "1.63–2.41 µm" },
  { id: "D4", range: "2.42–3.82 µm" },
  { id: "D5", range: "3.83–4.41 µm" },
  { id: "D6", range: "4.42–5.00 µm" },
]

export const PRESETS = [
  { id: "motion", label: "Motion finder", band: "ALL", why: "All six detectors stacked: the cleanest picture for spotting movers." },
  { id: "brown-dwarf", label: "Brown dwarf hunter", band: "RGB:D2,D4,D5+D6", why: "Cold brown dwarfs are bright only at 4–5 µm, so they look red; normal stars look white or blue." },
  { id: "variable", label: "Variable star", band: "D1", why: "Short wavelengths show the biggest brightness swings of pulsating stars." },
  { id: "ices", label: "Ices / molecules", band: "RGB:D4,D5,D6", why: "Water, CO₂ and CO ices absorb between 2.5 and 5 µm." },
]

/** 102 nominal channels: each detector range split into 17 log-spaced bins (same as the backend). */
export const CHANNELS = (() => {
  const ranges: [number, number][] = [[0.75, 1.09], [1.1, 1.62], [1.63, 2.41], [2.42, 3.82], [3.83, 4.41], [4.42, 5.0]]
  const out: { id: string; label: string }[] = []
  ranges.forEach(([lo, hi], d) => {
    for (let i = 0; i < 17; i++) {
      const a = lo * Math.pow(hi / lo, i / 17)
      const b = lo * Math.pow(hi / lo, (i + 1) / 17)
      out.push({ id: `WL:${a.toFixed(3)}-${b.toFixed(3)}`, label: `#${d * 17 + i + 1}  ${((a + b) / 2).toFixed(3)} µm (D${d + 1})` })
    }
  })
  return out
})()

export function BandSelector({ band, update, compact }: { band: string; update: Update; compact?: boolean }) {
  const isWl = band.startsWith("WL:")
  const isRgb = band.startsWith("RGB:")
  return (
    <section>
      <ControlLabel tip="Which wavelengths to show. Each SPHEREx detector sees a different slice of infrared light; ALL stacks them for the clearest picture.">
        Band
      </ControlLabel>
      <div className="grid grid-cols-4 gap-1">
        {["ALL", ...DETECTORS.map((d) => d.id)].map((b) => (
          <Button
            key={b}
            size="sm"
            variant={band === b ? "default" : "outline"}
            className="h-8 px-0 text-xs"
            onClick={() => update({ band: b })}
            title={b === "ALL" ? "All detectors stacked" : DETECTORS.find((d) => d.id === b)?.range}
          >
            {b}
          </Button>
        ))}
      </div>
      {!compact && (
        <div className="mt-2 space-y-2">
          <Select value={PRESETS.find((p) => p.band === band)?.id ?? ""} onValueChange={(id) => {
            const p = PRESETS.find((x) => x.id === id)
            if (p) update({ band: p.band })
          }}>
            <SelectTrigger className="h-8 text-xs" aria-label="Band presets"><SelectValue placeholder="Presets…" /></SelectTrigger>
            <SelectContent>
              {PRESETS.map((p) => (
                <SelectItem key={p.id} value={p.id} className="text-xs">{p.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {PRESETS.find((p) => p.band === band) && (
            <p className="text-xs text-muted-foreground">{PRESETS.find((p) => p.band === band)?.why}</p>
          )}
          <div className="flex items-center gap-1">
            <Select value={isWl ? band : ""} onValueChange={(v) => update({ band: v })}>
              <SelectTrigger className="h-8 text-xs" aria-label="Narrow wavelength channel"><SelectValue placeholder="Narrow channel (102)…" /></SelectTrigger>
              <SelectContent className="max-h-72">
                {CHANNELS.map((c) => (
                  <SelectItem key={c.id} value={c.id} className="font-mono text-xs">{c.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <InfoTip text="One of 102 narrow wavelength channels. Only exposures in which the target falls at that wavelength are used (fewer exposures, noisier)." />
          </div>
          {isRgb && <p className="text-xs text-muted-foreground">False colour: blue = {band.slice(4).split(",")[0]}, green = {band.slice(4).split(",")[1]}, red = {band.slice(4).split(",")[2]}</p>}
        </div>
      )}
    </section>
  )
}

export function FovControl({ fov, update }: { fov: number; update: Update }) {
  const options = [60, 120, 180, 300, 600, 900, 1800]
  return (
    <section>
      <ControlLabel tip="Field of view: how much sky to cut out around the position. Bigger fields take longer to download.">
        Field of view
      </ControlLabel>
      <Select value={String(fov)} onValueChange={(v) => update({ fov: Number(v) })}>
        <SelectTrigger className="h-8 text-xs" aria-label="Field of view"><SelectValue /></SelectTrigger>
        <SelectContent>
          {(options.includes(fov) ? options : [...options, fov].sort((a, b) => a - b)).map((o) => (
            <SelectItem key={o} value={String(o)} className="text-xs">{o}″ ({(o / 60).toFixed(o < 120 ? 1 : 0)}′)</SelectItem>
          ))}
        </SelectContent>
      </Select>
      {fov > 600 && <p className="mt-1 text-xs text-amber-400">Large field: the first load can take several minutes.</p>}
    </section>
  )
}

export function ModeSelector({ state, update }: { state: ViewerState; update: Update }) {
  return (
    <section className="space-y-3">
      <div>
        <ControlLabel tip="Epochs: one picture per sky survey (~6 months apart). All exposures: every single snapshot (noisier, best for fast asteroids). Stack: one deep picture.">
          Frames
        </ControlLabel>
        <Select value={state.mode} onValueChange={(v) => update({ mode: v as Mode })}>
          <SelectTrigger className="h-8 text-xs" aria-label="Frame mode"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="epochs" className="text-xs">Epochs (one per visit)</SelectItem>
            <SelectItem value="exposures" className="text-xs">All exposures</SelectItem>
            <SelectItem value="stack" className="text-xs">Stack everything</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {state.mode === "epochs" && (
        <div>
          <ControlLabel tip="Exposures closer together than this many days are combined into one frame. Use 1–7 days near the ecliptic poles, where SPHEREx looks very often.">
            Window: {state.window} d
          </ControlLabel>
          <Slider min={1} max={90} step={1} value={[state.window]} onValueChange={([v]) => update({ window: v })} aria-label="Epoch window in days" />
        </div>
      )}
      <div>
        <ControlLabel tip="Difference images subtract one picture from another, so everything that stayed the same disappears and only changes (motion, brightening) remain.">
          Difference
        </ControlLabel>
        <Select value={state.diff} onValueChange={(v) => update({ diff: v as Diff })}>
          <SelectTrigger className="h-8 text-xs" aria-label="Difference mode"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="none" className="text-xs">Off (normal images)</SelectItem>
            <SelectItem value="first" className="text-xs">Minus first frame</SelectItem>
            <SelectItem value="previous" className="text-xs">Minus previous frame</SelectItem>
            <SelectItem value="mean" className="text-xs">Minus mean of the others</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </section>
  )
}

export function StretchControls({ state, update, compact }: { state: ViewerState; update: Update; compact?: boolean }) {
  const pmin = state.min.startsWith("p") ? parseFloat(state.min.slice(1)) : 0.5
  const pmax = state.max.startsWith("p") ? parseFloat(state.max.slice(1)) : 99.5
  return (
    <section className="space-y-3">
      <ControlLabel tip="Contrast: which brightness range maps to black and white. 'asinh' and 'log' bring out faint things next to bright stars.">
        Stretch
      </ControlLabel>
      {!compact && (
        <Select value={state.stretch} onValueChange={(v) => update({ stretch: v as StretchKind })}>
          <SelectTrigger className="h-8 text-xs" aria-label="Stretch function"><SelectValue /></SelectTrigger>
          <SelectContent>
            {["linear", "asinh", "log", "sqrt", "zscale"].map((s) => (
              <SelectItem key={s} value={s} className="text-xs">{s}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      <div>
        <Label className="text-xs text-muted-foreground">Black point: {pmin}th percentile</Label>
        <Slider min={0} max={50} step={0.5} value={[pmin]} onValueChange={([v]) => update({ min: `p${v}` })} aria-label="Black point percentile" />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">White point: {pmax}th percentile</Label>
        <Slider min={80} max={100} step={0.1} value={[pmax]} onValueChange={([v]) => update({ max: `p${Number(v.toFixed(1))}` })} aria-label="White point percentile" />
      </div>
      <div>
        <Label className="text-xs text-muted-foreground">Zoom: {state.zoom}×</Label>
        <Slider min={1} max={16} step={1} value={[state.zoom]} onValueChange={([v]) => update({ zoom: v })} aria-label="Zoom" />
      </div>
      <ToggleRow label="Invert" tip="Black stars on white sky; some people find faint things easier to see this way." checked={state.invert} onChange={(v) => update({ invert: v })} />
      {!compact && (
        <ToggleRow label="Smooth pixels" tip="Off: big square pixels (honest). On: the browser smooths them (prettier, but can hide tiny shifts)." checked={state.smooth} onChange={(v) => update({ smooth: v })} />
      )}
    </section>
  )
}

export function ToggleRow({ label, tip, checked, onChange, disabled }: {
  label: string; tip: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean
}) {
  const id = `t-${label.replace(/\W+/g, "-").toLowerCase()}`
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="flex items-center gap-1.5">
        <Label htmlFor={id} className="text-xs">{label}</Label>
        <InfoTip text={tip} />
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onChange} disabled={disabled} />
    </div>
  )
}

export function OverlayToggles({ state, update, hasPm }: { state: ViewerState; update: Update; hasPm: boolean }) {
  return (
    <section className="space-y-2">
      <ControlLabel tip="Extra layers drawn on top of the picture.">Overlays</ControlLabel>
      <ToggleRow label="Crosshair" tip="Red crosshair at the target's catalogue position, moved to each frame's date using its known motion." checked={state.crosshair} onChange={(v) => update({ crosshair: v })} />
      <ToggleRow label="Motion arrow" tip="Yellow arrow: where the target will be in 10 years, from its catalogue proper motion." checked={state.pm} onChange={(v) => update({ pm: v })} disabled={!hasPm} />
      <ToggleRow label="Gaia DR3 stars" tip="Blue circles: stars measured by ESA's Gaia satellite, moved to each frame's date. Fast stars' circles move with them." checked={state.gaia} onChange={(v) => update({ gaia: v })} />
      <ToggleRow label="CatWISE sources" tip="Orange diamonds: infrared sources from NASA's WISE mission (CatWISE2020 catalogue), good for brown dwarfs." checked={state.wise} onChange={(v) => update({ wise: v })} />
      <ToggleRow label="Bad-pixel flags" tip="Colour pixels the SPHEREx pipeline flagged: red = saturated, pink = ghost/streak, yellow = transient/persistence, blue = detector defect." checked={state.flags} onChange={(v) => update({ flags: v })} />
      <ToggleRow label="Track target" tip="Off: the sky stays fixed and the target moves. On: the view follows the target, so the background stars move instead." checked={state.track} onChange={(v) => update({ track: v })} disabled={!hasPm} />
      <ToggleRow label="Remove zodiacal light" tip="Subtract the pipeline's model of sunlight scattered by interplanetary dust (a smooth glow)." checked={state.zodi} onChange={(v) => update({ zodi: v })} />
    </section>
  )
}
