"""Frame-set jobs and frame downloads."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.core.config import get_settings
from app.core.ratelimit import limiter
from app.schemas.models import JobCreated, JobRequest, JobStatus
from app.services.cache import get_cache, get_job_store
from app.services.render import (
    decode_frame,
    fits_cube_bytes,
    gif_bytes,
    png_bytes,
    resolve_limit,
    to_uint8_image,
    zscale_limits,
)
from app.workers.job_runner import submit

router = APIRouter()


@router.post("/jobs", response_model=JobCreated)
@limiter.limit(lambda: get_settings().rate_limit_jobs)
async def create_job(request: Request, body: JobRequest) -> JobCreated:
    s = get_settings()
    if body.fov_arcsec > s.max_fov_arcsec:
        raise HTTPException(422, f"Field of view is limited to {s.max_fov_arcsec:.0f} arcsec.")
    job = await submit(body)
    return JobCreated(job_id=job.id, status=job.status, request_hash=job.request_hash)


@router.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job(job_id: str) -> Any:
    job = get_job_store().get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job (the server may have restarted). Please submit it again.")
    return job.public()


def _frameset(h: str) -> dict[str, Any]:
    rec = get_cache().get_record("frame_sets", h)
    if rec:
        return rec
    # a job that is still running: serve what is ready
    for j in list(get_job_store()._jobs.values()):
        if j.request_hash == h:
            return {"frames": j.frames, "info": j.info, "status": j.status}
    raise HTTPException(404, "Unknown frame set.")


def _split_id(frame_id: str) -> tuple[str, int]:
    try:
        h, idx = frame_id.rsplit("-", 1)
        return h, int(idx)
    except ValueError as exc:
        raise HTTPException(404, "Bad frame id") from exc


def _frame_meta(h: str, idx: int) -> dict[str, Any]:
    for m in _frameset(h).get("frames", []):
        if m["idx"] == idx:
            return m
    raise HTTPException(404, "Unknown frame.")


@router.get("/framesets/{h}")
async def frameset(h: str) -> dict[str, Any]:
    return _frameset(h)


@router.get("/frames/{frame_id}.bin")
async def frame_bin(frame_id: str) -> Response:
    h, idx = _split_id(frame_id)
    meta = _frame_meta(h, idx)
    data = await asyncio.to_thread(get_cache().get_blob, get_settings().cache_bucket, f"{h}/{idx}.bin")
    if data is None:
        raise HTTPException(404, "Frame data missing.")
    return Response(data, media_type="application/octet-stream", headers={
        "X-Width": str(meta["width"]), "X-Height": str(meta["height"]), "X-Channels": str(meta["n_channels"]),
        "Cache-Control": "public, max-age=86400, immutable",
        "Access-Control-Expose-Headers": "X-Width, X-Height, X-Channels",
    })


@router.get("/frames/{frame_id}/flags.bin")
async def frame_flags(frame_id: str) -> Response:
    h, idx = _split_id(frame_id)
    meta = _frame_meta(h, idx)
    data = await asyncio.to_thread(get_cache().get_blob, get_settings().cache_bucket, f"{h}/flags_{idx}.bin")
    if data is None:
        raise HTTPException(404, "Flag data missing.")
    return Response(data, media_type="application/octet-stream", headers={
        "X-Width": str(meta["width"]), "X-Height": str(meta["height"]),
        "Cache-Control": "public, max-age=86400, immutable",
    })


def _limits(channels: list[Any], gstats: list[dict[str, float]] | None, vmin: str | None, vmax: str | None,
            stretch: str) -> tuple[list[float], list[float]]:
    los, his = [], []
    for ci, c in enumerate(channels):
        if stretch == "zscale" and not vmin and not vmax:
            lo, hi = zscale_limits(c)
        elif gstats and not vmin and not vmax and ci < len(gstats):
            lo, hi = gstats[ci]["p0_5"], gstats[ci]["p99_5"]
        else:
            lo, hi = resolve_limit(vmin, c, 0.5), resolve_limit(vmax, c, 99.5)
        los.append(lo)
        his.append(hi)
    return los, his


@router.get("/frames/{frame_id}.png")
async def frame_png(
    frame_id: str, stretch: str = "asinh", min: str | None = None, max: str | None = None,
    invert: int = 0, scale: int = Query(4, ge=1, le=16),
) -> Response:
    h, idx = _split_id(frame_id)
    meta = _frame_meta(h, idx)
    data = await asyncio.to_thread(get_cache().get_blob, get_settings().cache_bucket, f"{h}/{idx}.bin")
    if data is None:
        raise HTTPException(404, "Frame data missing.")
    chans = decode_frame(data, meta["width"], meta["height"], meta["n_channels"])
    gstats = _frameset(h).get("info", {}).get("global_stats")
    lo, hi = _limits(chans, gstats, min, max, stretch)
    img = to_uint8_image(chans, lo, hi, "linear" if stretch == "zscale" else stretch, bool(invert), scale)
    return Response(png_bytes(img), media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


@router.get("/framesets/{h}/animation.gif")
async def frameset_gif(
    h: str, stretch: str = "asinh", speed_ms: int = Query(500, ge=50, le=5000),
    size: int = Query(256, ge=32, le=1024), invert: int = 0, diff: str = "none",
) -> Response:
    from app.services.coadd import difference

    fs = _frameset(h)
    frames = fs.get("frames", [])
    if not frames:
        raise HTTPException(404, "No frames.")
    cache = get_cache()
    bucket = get_settings().cache_bucket
    path = f"{h}/anim_{stretch}_{speed_ms}_{size}_{invert}_{diff}.gif"
    cached = await asyncio.to_thread(cache.get_blob, bucket, path)
    if cached:
        return Response(cached, media_type="image/gif")
    all_ch = []
    for m in frames:
        raw = await asyncio.to_thread(cache.get_blob, bucket, f"{h}/{m['idx']}.bin")
        if raw is not None:
            all_ch.append(decode_frame(raw, m["width"], m["height"], m["n_channels"]))
    if diff != "none" and all_ch:
        n_ch = len(all_ch[0])
        per = [difference([f[ci] for f in all_ch], diff) for ci in range(n_ch)]
        all_ch = [[per[ci][k] for ci in range(n_ch)] for k in range(len(all_ch))]
        gstats = None
    else:
        gstats = fs.get("info", {}).get("global_stats")
    import numpy as np

    lo, hi = _limits([np.concatenate([f[ci].ravel() for f in all_ch]) for ci in range(len(all_ch[0]))],
                     gstats, None, None, stretch)
    scale = max(1, size // frames[0]["width"])
    imgs = [to_uint8_image(ch, lo, hi, "linear" if stretch == "zscale" else stretch, bool(invert), scale)
            for ch in all_ch]
    data = gif_bytes(imgs, speed_ms)
    await asyncio.to_thread(cache.put_blob, bucket, path, data, "image/gif")
    return Response(data, media_type="image/gif", headers={"Cache-Control": "public, max-age=3600"})


@router.get("/framesets/{h}/fits")
async def frameset_fits(h: str) -> Response:
    fs = _frameset(h)
    frames = fs.get("frames", [])
    if not frames:
        raise HTTPException(404, "No frames.")
    cache = get_cache()
    bucket = get_settings().cache_bucket
    chans = []
    for m in frames:
        raw = await asyncio.to_thread(cache.get_blob, bucket, f"{h}/{m['idx']}.bin")
        chans.append(decode_frame(raw or b"", m["width"], m["height"], m["n_channels"]))
    data = await asyncio.to_thread(fits_cube_bytes, chans, frames, frames[0]["grid"], fs.get("request", {}))
    return Response(data, media_type="application/fits", headers={
        "Content-Disposition": f'attachment; filename="nexus-viewer-{h[:10]}.fits"'})
