// Typed client for the FastAPI backend. All calls go to /api/* on this origin,
// which next.config.mjs rewrites to BACKEND_URL.
import type {
  CatalogResponse, FrameMeta, JobRequest, JobStatus, LightCurveResponse, Pending, Release,
  Resolved, SpectrumResponse, Target,
} from "./types"

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = res.statusText
    try {
      const body = await res.json()
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body)
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg || `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

const base = "/api"

export const api = {
  health: () => fetch(`${base}/health`).then(json<{ ok: boolean; irsa: string; cache_backend: string }>),
  targets: () => fetch(`${base}/targets`).then(json<Target[]>),
  target: (slug: string) => fetch(`${base}/targets/${encodeURIComponent(slug)}`).then(json<Target>),
  releases: () => fetch(`${base}/releases`).then(json<Release[]>),
  resolve: (name: string) => fetch(`${base}/resolve?name=${encodeURIComponent(name)}`).then(json<Resolved>),

  createJob: (req: JobRequest) =>
    fetch(`${base}/jobs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(req),
    }).then(json<{ job_id: string; status: string; request_hash: string }>),
  getJob: (id: string) => fetch(`${base}/jobs/${id}`).then(json<JobStatus>),

  /** Raw float32 frame; channels are concatenated, row 0 = north. */
  async getFrame(meta: FrameMeta): Promise<Float32Array[]> {
    const res = await fetch(`${base}/frames/${meta.id}.bin`)
    if (!res.ok) throw new ApiError(res.status, "frame download failed")
    const buf = await res.arrayBuffer()
    const n = meta.width * meta.height
    const all = new Float32Array(buf)
    return Array.from({ length: meta.n_channels }, (_, c) => all.subarray(c * n, (c + 1) * n))
  },
  async getFlags(meta: FrameMeta): Promise<Uint32Array> {
    const res = await fetch(`${base}/frames/${meta.id}/flags.bin`)
    if (!res.ok) throw new ApiError(res.status, "flags download failed")
    return new Uint32Array(await res.arrayBuffer())
  },
  framePngUrl: (frameId: string, stretch = "asinh", scale = 4) =>
    `${base}/frames/${frameId}.png?stretch=${stretch}&scale=${scale}`,
  gifUrl: (hash: string, opts: { stretch?: string; speed_ms?: number; size?: number; diff?: string } = {}) => {
    const q = new URLSearchParams({
      stretch: opts.stretch ?? "asinh",
      speed_ms: String(opts.speed_ms ?? 500),
      size: String(opts.size ?? 256),
      diff: opts.diff ?? "none",
    })
    return `${base}/framesets/${hash}/animation.gif?${q}`
  },
  fitsUrl: (hash: string) => `${base}/framesets/${hash}/fits`,

  /** 200 -> result; 202 -> still measuring (poll again). */
  async spectrum(q: Record<string, string | number>): Promise<SpectrumResponse | Pending> {
    const res = await fetch(`${base}/spectrum?${new URLSearchParams(q as Record<string, string>)}`)
    if (res.status === 202) return (await res.json()) as Pending
    return json<SpectrumResponse>(res)
  },
  async lightcurve(q: Record<string, string | number>): Promise<LightCurveResponse | Pending> {
    const res = await fetch(`${base}/lightcurve?${new URLSearchParams(q as Record<string, string>)}`)
    if (res.status === 202) return (await res.json()) as Pending
    return json<LightCurveResponse>(res)
  },

  gaia: (ra: number, dec: number, fov: number) =>
    fetch(`${base}/overlays/gaia?ra=${ra}&dec=${dec}&fov_arcsec=${fov}`).then(json<CatalogResponse>),
  wise: (ra: number, dec: number, fov: number) =>
    fetch(`${base}/overlays/wise?ra=${ra}&dec=${dec}&fov_arcsec=${fov}&catalog=catwise_2020`).then(
      json<CatalogResponse>,
    ),
}

export function isPending(x: unknown): x is Pending {
  return typeof x === "object" && x !== null && (x as Pending).status === "running"
}
