"use client"

import { useEffect, useRef, useState } from "react"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

// Pinned Aladin Lite v3 build (ES module) from the npm package on jsDelivr.
// (aladin.cds.unistra.fr/AladinLite/api/v3/... returned 404 during the build.)
const ALADIN_URL = "https://cdn.jsdelivr.net/npm/aladin-lite@3.6.5/dist/aladin.js"

const SURVEYS = [
  { id: "P/DSS2/color", label: "DSS2 (visible)" },
  { id: "P/2MASS/color", label: "2MASS (near-IR)" },
  { id: "P/allWISE/color", label: "AllWISE (mid-IR)" },
  { id: "P/PanSTARRS/DR1/color-z-zg-g", label: "Pan-STARRS" },
]

/* eslint-disable @typescript-eslint/no-explicit-any */
let aladinModule: Promise<any> | null = null
function loadAladin(): Promise<any> {
  if (!aladinModule) {
    // runtime import from the CDN (kept out of the bundle)
    const dynImport = new Function("u", "return import(u)") as (u: string) => Promise<any>
    aladinModule = dynImport(ALADIN_URL).then(async (m) => {
      const A = m.default
      await A.init
      return A
    })
  }
  return aladinModule
}

/** Context view of the surrounding sky with a box showing the SPHEREx field. */
export function AladinPanel({ ra, dec, fovArcsec }: { ra: number; dec: number; fovArcsec: number }) {
  const div = useRef<HTMLDivElement>(null)
  const inst = useRef<any>(null)
  const overlay = useRef<any>(null)
  const [survey, setSurvey] = useState(SURVEYS[2].id)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    loadAladin()
      .then((A) => {
        if (cancelled || !div.current) return
        if (!inst.current) {
          inst.current = A.aladin(div.current, {
            survey, fov: (fovArcsec * 3) / 3600, target: `${ra} ${dec}`, showReticle: false,
            showLayersControl: false, showGotoControl: false, showFullscreenControl: true,
            showFrame: false, showCooGridControl: false, showProjectionControl: false,
          })
          overlay.current = A.graphicOverlay({ color: "#D55E00", lineWidth: 2 })
          inst.current.addOverlay(overlay.current)
        }
        const half = fovArcsec / 2 / 3600
        const cosd = Math.cos((dec * Math.PI) / 180)
        overlay.current.removeAll()
        overlay.current.add(A.polygon([
          [ra - half / cosd, dec - half], [ra + half / cosd, dec - half],
          [ra + half / cosd, dec + half], [ra - half / cosd, dec + half],
        ]))
        inst.current.gotoRaDec(ra, dec)
        inst.current.setFoV((fovArcsec * 3) / 3600)
      })
      .catch((e) => setErr(String(e)))
    return () => {
      cancelled = true
    }
  }, [ra, dec, fovArcsec]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    inst.current?.setImageSurvey?.(survey)
  }, [survey])

  return (
    <div className="space-y-2">
      <Select value={survey} onValueChange={setSurvey}>
        <SelectTrigger className="h-8 text-xs" aria-label="Background survey"><SelectValue /></SelectTrigger>
        <SelectContent>
          {SURVEYS.map((s) => <SelectItem key={s.id} value={s.id} className="text-xs">{s.label}</SelectItem>)}
        </SelectContent>
      </Select>
      {err ? (
        <p className="text-xs text-muted-foreground">Aladin Lite could not load ({err.slice(0, 80)}). It needs WebGL2 and access to cdn.jsdelivr.net.</p>
      ) : (
        <div ref={div} className="h-56 w-full overflow-hidden rounded-md border border-border/60" />
      )}
      <p className="text-[10px] text-muted-foreground">Aladin Lite © CDS, Strasbourg. Box = SPHEREx field of view.</p>
    </div>
  )
}
