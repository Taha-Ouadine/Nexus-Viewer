// Mirrors backend/app/schemas/models.py and the JSON returned by the API.

export type Mode = "epochs" | "exposures" | "stack"
export type Diff = "none" | "first" | "previous" | "mean"
export type StretchKind = "linear" | "asinh" | "log" | "sqrt" | "zscale"

export interface ProperMotion {
  pmra: number
  pmdec: number
  ref_epoch: number
  ra?: number | null
  dec?: number | null
}

export interface JobRequest {
  ra: number
  dec: number
  fov_arcsec: number
  band: string
  mode: Mode
  diff: Diff
  window_days: number
  subtract_zodi: boolean
  bad_flag_bits?: number[] | null
  track_pm: boolean
  pm?: ProperMotion | null
  releases?: string[] | null
  oversample?: 1 | 2
}

export interface GridWcs {
  ctype: [string, string]
  crval: [number, number]
  crpix: [number, number]
  cdelt: [number, number]
  npix: number
  scale_arcsec: number
  row0: "north"
}

export interface ChannelStats {
  p0_5: number
  p99_5: number
  median: number
  mad: number
  min: number
  max: number
}

export interface FrameMeta {
  id: string
  idx: number
  t_start: number
  t_end: number
  t_mid: number
  date_mid: string
  jyear: number
  n_exposures: number
  obs_ids: string[]
  detectors: Record<string, number>
  releases: string[]
  versions: string[]
  lambda_um: number | null
  lambda_range: [number, number] | null
  channels: { label: string; n_exposures: number; lambda_um: number | null }[]
  flag_summary: Record<string, number>
  stats: ChannelStats[]
  center: { ra: number; dec: number }
  target: { ra: number; dec: number; x: number; y: number } | null
  grid: GridWcs
  width: number
  height: number
  n_channels: number
}

export interface JobStatus {
  job_id: string
  request_hash: string
  status: "queued" | "running" | "done" | "failed"
  progress: number
  stage: string
  error?: string | null
  frames: FrameMeta[]
  info: {
    n_exposures_found?: number
    n_selected?: number
    n_frames_planned?: number
    reason?: string
    seconds?: number
    cached?: boolean
    global_stats?: ChannelStats[]
    releases?: string[]
  }
}

export interface Target {
  slug: string
  name: string
  ra_deg: number
  dec_deg: number
  ref_epoch: number
  pmra_masyr: number | null
  pmdec_masyr: number | null
  parallax_mas: number | null
  category: string
  description: string
  what_to_see: string
  recommended_view: { band: string; fov: number; zoom: number; diff: Diff; window?: number; mode?: Mode }
  view_ra: number
  view_dec: number
  view_epoch: number
  is_featured: boolean
  sort_order: number
}

export interface Resolved {
  name: string
  ra: number
  dec: number
  pmra: number | null
  pmdec: number | null
  parallax: number | null
  ref_epoch: number
  otype: string | null
  source: string
}

export interface CatalogSource {
  source_id: string
  ra: number
  dec: number
  pmra: number | null
  pmdec: number | null
  gmag?: number | null
  w1?: number | null
  w2?: number | null
}

export interface CatalogResponse {
  catalog: string
  ref_epoch: number
  sources: CatalogSource[]
}

export interface PhotPoint {
  t_mid: number
  flux_uJy: number
  err_uJy: number
  lambda_um: number | null
  bandwidth_um?: number | null
  detector: number
  flagged: boolean
  flags?: string[]
  epoch: number
  obs_id: string
}

export interface SpectrumResponse {
  ra: number
  dec: number
  aperture_arcsec: number
  points: PhotPoint[]
  binned: { channel: number; lambda_um: number; flux_uJy: number; err_uJy: number; n: number }[]
  epochs: { index: number; t_start: number; t_end: number; n_points: number }[]
  n_exposures: number
  n_exposures_found?: number
  pm_tracked: boolean
}

export interface LightCurveResponse {
  band: string
  points: PhotPoint[]
  per_epoch: { epoch: number; t_mid: number; flux_uJy: number; err_uJy: number; scatter_uJy: number; n: number; flagged?: boolean }[]
  epochs: { index: number; t_start: number; t_end: number }[]
}

export interface Pending {
  status: "running"
  progress: number
  stage: string
}

export interface Release {
  id: string
  label: string
  doi: string | null
  is_active: boolean
  notes: string | null
}
