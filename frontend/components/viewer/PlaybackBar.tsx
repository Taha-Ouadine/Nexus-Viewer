"use client"

import { Pause, Play, SkipBack, SkipForward } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import { InfoTip } from "./InfoTip"
import type { FrameMeta } from "@/lib/types"

export function PlaybackBar({
  frames, index, setIndex, playing, setPlaying, step, speed, setSpeed, compact,
}: {
  frames: FrameMeta[]
  index: number
  setIndex: (i: number) => void
  playing: boolean
  setPlaying: (p: boolean) => void
  step: (d: number) => void
  speed: number
  setSpeed: (ms: number) => void
  compact?: boolean
}) {
  const t0 = frames[0]?.t_mid ?? 0
  const t1 = frames[frames.length - 1]?.t_mid ?? 1
  const span = Math.max(t1 - t0, 1)
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border/60 bg-card/60 p-3 sm:flex-row sm:items-center">
      <div className="flex items-center gap-1">
        <Button size="icon" variant="ghost" onClick={() => step(-1)} aria-label="Previous frame (←)" title="Previous frame (←)">
          <SkipBack className="h-4 w-4" />
        </Button>
        <Button size="icon" onClick={() => setPlaying(!playing)} aria-label={playing ? "Pause (space)" : "Play (space)"} title="Play / pause (space)">
          {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
        </Button>
        <Button size="icon" variant="ghost" onClick={() => step(1)} aria-label="Next frame (→)" title="Next frame (→)">
          <SkipForward className="h-4 w-4" />
        </Button>
      </div>
      {!compact && (
        <div className="flex w-full items-center gap-2 sm:w-48">
          <span className="whitespace-nowrap text-xs text-muted-foreground">{speed} ms</span>
          <Slider min={50} max={2000} step={50} value={[speed]} onValueChange={([v]) => setSpeed(v)} aria-label="Milliseconds per frame" />
          <InfoTip text="How long each frame stays on screen. ~500 ms is good for blinking." />
        </div>
      )}
      <div className="relative h-8 flex-1" aria-label="Epoch timeline">
        <div className="absolute left-2 right-2 top-1/2 h-px bg-border" />
        {frames.map((f, i) => {
          const left = frames.length === 1 ? 50 : ((f.t_mid - t0) / span) * 100
          return (
            <button
              key={f.id}
              type="button"
              onClick={() => { setPlaying(false); setIndex(i) }}
              className={`absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 transition ${i === index ? "scale-125 border-primary bg-primary" : "border-muted-foreground bg-background hover:border-primary"}`}
              style={{ left: `calc(0.5rem + (100% - 1rem) * ${left / 100})` }}
              title={`${f.date_mid.slice(0, 10)} · ${f.n_exposures} exposures`}
              aria-label={`Frame ${i + 1}: ${f.date_mid.slice(0, 10)}`}
            />
          )
        })}
      </div>
      <div className="min-w-[9rem] text-right font-mono text-xs">
        {frames[index] ? `${index + 1}/${frames.length} · ${frames[index].date_mid.slice(0, 10)}` : "–"}
      </div>
    </div>
  )
}
