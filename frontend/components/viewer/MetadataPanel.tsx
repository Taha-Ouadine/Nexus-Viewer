"use client"

import { Badge } from "@/components/ui/badge"
import { formatDec, formatRA } from "@/lib/coords"
import type { FrameMeta } from "@/lib/types"
import { InfoTip } from "./InfoTip"

export function MetadataPanel({ frame, total }: { frame: FrameMeta | undefined; total: number }) {
  if (!frame) return <div className="text-sm text-muted-foreground">No frame yet.</div>
  const flags = Object.entries(frame.flag_summary).filter(([k]) => k !== "SOURCE" && k !== "FULLSAMPLE")
  const npix = frame.width * frame.height
  return (
    <div className="space-y-2 text-sm">
      <Row k="Frame" v={`${frame.idx + 1} of ${total}`} />
      <Row k="Dates" v={`${frame.date_mid.slice(0, 10)}`} sub={`${mjd(frame.t_start)} → ${mjd(frame.t_end)}`} />
      <Row k="Exposures" v={String(frame.n_exposures)} sub={Object.entries(frame.detectors).map(([d, n]) => `${d}:${n}`).join(" ")} />
      <Row
        k="Wavelength"
        v={frame.lambda_um ? `${frame.lambda_um.toFixed(2)} µm` : "–"}
        sub={frame.lambda_range ? `range ${frame.lambda_range[0].toFixed(2)}–${frame.lambda_range[1].toFixed(2)} µm` : undefined}
        tip="Average wavelength at the centre of the field over the exposures in this frame."
      />
      {frame.channels.length > 1 && (
        <Row k="Colours" v={frame.channels.map((c, i) => `${["B", "G", "R"][i]}=${c.label}(${c.n_exposures})`).join(" ")} />
      )}
      <Row k="Centre" v={`${formatRA(frame.center.ra, 1)} ${formatDec(frame.center.dec, 0)}`} />
      {frame.target && <Row k="Target" v={`${frame.target.ra.toFixed(5)}, ${frame.target.dec.toFixed(5)}`} tip="Catalogue position moved to this frame's date with the proper motion." />}
      <Row k="Release" v={frame.releases.join(", ").toUpperCase()} sub={frame.versions.slice(-1)[0]} />
      <div>
        <div className="mb-1 flex items-center gap-1 text-xs text-muted-foreground">
          Flags in field <InfoTip text="Pixels the SPHEREx pipeline marked as possibly bad in at least one exposure (counted over the whole field). Turn on the flag overlay to see where." />
        </div>
        {flags.length === 0 ? (
          <span className="text-xs text-muted-foreground">none</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {flags.sort((a, b) => b[1] - a[1]).map(([k, n]) => (
              <Badge key={k} variant="secondary" className="text-[10px]">{k} {((100 * n) / npix).toFixed(0)}%</Badge>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function mjd(m: number) {
  return new Date((m - 40587) * 86400000).toISOString().slice(0, 10)
}

function Row({ k, v, sub, tip }: { k: string; v: string; sub?: string; tip?: string }) {
  return (
    <div className="grid grid-cols-[5.5rem_1fr] gap-2">
      <div className="flex items-center gap-1 text-xs text-muted-foreground">{k}{tip && <InfoTip text={tip} />}</div>
      <div>
        <div className="font-mono text-xs">{v}</div>
        {sub && <div className="font-mono text-[10px] text-muted-foreground">{sub}</div>}
      </div>
    </div>
  )
}
