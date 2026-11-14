"use client"

import { useQuery } from "@tanstack/react-query"
import { api, isPending } from "@/lib/api"
import type { LightCurveResponse, Pending, SpectrumResponse } from "@/lib/types"

export interface PickPoint {
  ra: number
  dec: number
  pm?: { pmra: number; pmdec: number; ref_epoch: number; ra: number; dec: number } | null
}

function params(p: PickPoint, extra: Record<string, string | number> = {}) {
  const q: Record<string, string | number> = { ra: p.ra.toFixed(6), dec: p.dec.toFixed(6), ...extra }
  if (p.pm) {
    q.pmra = p.pm.pmra
    q.pmdec = p.pm.pmdec
    q.ref_epoch = p.pm.ref_epoch
    q.pm_ra = p.pm.ra
    q.pm_dec = p.pm.dec
  }
  return q
}

/** Spectrum / light curve at a clicked position. The backend answers 202 while it is
 *  still measuring, so we poll every 2 s until the result arrives. */
export function useSpectrum(p: PickPoint | null, releases: string[] | null) {
  return useQuery<SpectrumResponse | Pending>({
    queryKey: ["spectrum", p, releases],
    queryFn: () => api.spectrum(params(p as PickPoint, { epochs: "split", ...(releases ? { releases: releases.join(",") } : {}) })),
    enabled: !!p,
    refetchInterval: (q) => (q.state.data && isPending(q.state.data) ? 2000 : false),
    staleTime: Infinity,
  })
}

export function useLightCurve(p: PickPoint | null, band: string, releases: string[] | null) {
  return useQuery<LightCurveResponse | Pending>({
    queryKey: ["lightcurve", p, band, releases],
    queryFn: () => api.lightcurve(params(p as PickPoint, { band, ...(releases ? { releases: releases.join(",") } : {}) })),
    enabled: !!p,
    refetchInterval: (q) => (q.state.data && isPending(q.state.data) ? 2000 : false),
    staleTime: Infinity,
  })
}
