"""Building a frame set: query -> select -> cluster -> fetch -> align -> coadd -> store.

Jobs run as asyncio tasks inside the API process. Network I/O is async (shared
`CutoutFetcher` with one global concurrency limit); CPU work (reprojection,
coadds) runs in worker threads via `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from astropy.time import Time

from app.core.config import get_settings
from app.schemas.models import JobRequest
from app.services.alignment import Grid, align, make_grid
from app.services.cache import Job, get_cache, get_job_store, stable_hash
from app.services.coadd import bad_mask_value, coadd, difference, fill_holes, flag_summary, robust_stats
from app.services.cutouts import CutoutFetcher, snap_half, window_half_px
from app.services.epochs import cluster_times
from app.services.fitsio import DEFAULT_FLAG_NAMES, Cutout
from app.services.irsa import Exposure, cached_exposures, find_exposures, release_versions, thin_exposures
from app.services.releases import active_releases
from app.services.render import flags_bytes, frame_bytes
from app.services.resolver import mjd_to_jyear, propagate
from app.services.wavelength import BandGroup, parse_band

log = logging.getLogger(__name__)

_fetcher: CutoutFetcher | None = None
_job_slots: asyncio.Semaphore | None = None
_tasks: set[asyncio.Task[None]] = set()  # keep references so tasks are not garbage-collected


_loop: asyncio.AbstractEventLoop | None = None


def _ensure_loop() -> None:
    """Async primitives belong to one event loop; recreate them if the loop changed
    (uvicorn uses one loop for its lifetime; scripts/tests may use several)."""
    global _fetcher, _job_slots, _loop
    loop = asyncio.get_running_loop()
    if loop is not _loop:
        _loop = loop
        _fetcher = CutoutFetcher()
        _job_slots = asyncio.Semaphore(2)  # at most 2 jobs download at once


def get_fetcher() -> CutoutFetcher:
    _ensure_loop()
    assert _fetcher is not None
    return _fetcher


def _slots() -> asyncio.Semaphore:
    _ensure_loop()
    assert _job_slots is not None
    return _job_slots


# ---------------------------------------------------------------- planning
@dataclass
class FramePlan:
    idx: int
    exposures: list[Exposure]
    groups: list[list[int]]  # for each band group, indices into `exposures` eligible for it


def select_exposures(exposures: list[Exposure], groups: list[BandGroup]) -> list[Exposure]:
    dets = {d for g in groups for d in g.detectors}
    return [e for e in exposures if e.detector in dets]


def plan_frames(exposures: list[Exposure], groups: list[BandGroup], mode: str, window_days: float) -> list[FramePlan]:
    if not exposures:
        return []
    if mode == "exposures" and len(groups) == 1:
        clusters = [[i] for i in sorted(range(len(exposures)), key=lambda i: exposures[i].t_mid)]
    elif mode == "stack":
        clusters = [list(range(len(exposures)))]
    else:
        clusters = cluster_times([e.t_mid for e in exposures], window_days)
    plans = []
    for k, idx in enumerate(clusters):
        exps = [exposures[i] for i in idx]
        per_group = [[j for j, e in enumerate(exps) if g.accepts_detector(e.detector)] for g in groups]
        plans.append(FramePlan(k, exps, per_group))
    return plans


def cap_exposures(exposures: list[Exposure], cap: int) -> list[Exposure]:
    return thin_exposures(exposures, cap)


def request_hash(req: JobRequest, versions: dict[str, str], bad_bits: list[int]) -> str:
    norm = req.normalized()
    norm["bad_flag_bits"] = bad_bits
    return stable_hash({"v": 7, "req": norm, "versions": versions})


def mjd_iso(mjd: float) -> str:
    return str(Time(mjd, format="mjd").isot)[:19] + "Z"


# ---------------------------------------------------------------- building
def _frame_centre(req: JobRequest, mjd: float) -> tuple[float, float]:
    if req.track_pm and req.pm is not None:
        ra0 = req.pm.ra if req.pm.ra is not None else req.ra
        dec0 = req.pm.dec if req.pm.dec is not None else req.dec
        return propagate(ra0, dec0, req.pm.pmra, req.pm.pmdec, req.pm.ref_epoch, mjd)
    return req.ra, req.dec


def _target_at(req: JobRequest, mjd: float, grid: Grid) -> dict[str, float] | None:
    if req.pm is None:
        return None
    ra0 = req.pm.ra if req.pm.ra is not None else req.ra
    dec0 = req.pm.dec if req.pm.dec is not None else req.dec
    tra, tdec = propagate(ra0, dec0, req.pm.pmra, req.pm.pmdec, req.pm.ref_epoch, mjd)
    x, y = grid.wcs().world_to_pixel_values(tra, tdec)
    # x: column from the left; convert FITS y (from bottom) to display row (from top)
    return {"ra": tra, "dec": tdec, "x": float(x), "y": float(grid.npix - 1 - float(y))}


def build_frame(
    plan: FramePlan, cutouts: list[Cutout | None], req: JobRequest, groups: list[BandGroup],
    grid: Grid, bad_mask: int,
) -> tuple[dict[str, Any], list[np.ndarray], np.ndarray] | None:
    aligned = []
    for c in cutouts:
        if c is None:
            aligned.append(None)
            continue
        a = align(c, grid, subtract_zodi=req.subtract_zodi)
        # keep exposures covering at least half the field (saturated stars may have NaN
        # cores in short bands; those pixels are simply masked in the coadd)
        aligned.append(a if a.coverage >= 0.5 else None)

    channels: list[np.ndarray] = []
    chan_meta: list[dict[str, Any]] = []
    used: set[int] = set()
    all_flags = np.zeros((grid.npix, grid.npix), np.uint32)
    for g, members in zip(groups, plan.groups):
        sel = []
        for j in members:
            a = aligned[j]
            if a is None:
                continue
            if g.lam_range is not None:
                if a.lambda_um is None or not (g.lam_range[0] <= a.lambda_um <= g.lam_range[1]):
                    continue
            sel.append(j)
        if sel:
            co = coadd([aligned[j].image for j in sel], [aligned[j].variance for j in sel],  # type: ignore[union-attr]
                       [aligned[j].flags for j in sel], bad_mask, level_background=True)  # type: ignore[union-attr]
            img, holes = fill_holes(co.image)
            channels.append(img)
            # filled pixels keep their flags; mark them OVERFLOW if nothing else explains them
            co.flags[holes & (co.flags == 0)] |= np.uint32(1 << 1)
            all_flags |= co.flags
            lams = [aligned[j].lambda_um for j in sel if aligned[j].lambda_um is not None]  # type: ignore[union-attr]
            chan_meta.append({"label": g.label, "n_exposures": len(sel),
                              "lambda_um": float(np.mean(lams)) if lams else None})
            used.update(sel)
        else:
            channels.append(np.full((grid.npix, grid.npix), np.nan, np.float32))
            chan_meta.append({"label": g.label, "n_exposures": 0, "lambda_um": None})
    if not used:
        return None

    exps = [plan.exposures[j] for j in sorted(used)]
    lams = [aligned[j].lambda_um for j in sorted(used) if aligned[j].lambda_um is not None]  # type: ignore[union-attr]
    t_start = min(e.t_min for e in exps)
    t_end = max(e.t_max for e in exps)
    t_mid = float(np.mean([e.t_mid for e in exps]))
    dets: dict[str, int] = {}
    for e in exps:
        dets[f"D{e.detector}"] = dets.get(f"D{e.detector}", 0) + 1
    names = next((c.flag_names for c in cutouts if c is not None), DEFAULT_FLAG_NAMES)
    meta = {
        "idx": plan.idx, "t_start": t_start, "t_end": t_end, "t_mid": t_mid, "date_mid": mjd_iso(t_mid),
        "jyear": round(mjd_to_jyear(t_mid), 4),
        "n_exposures": len(exps), "obs_ids": [e.key for e in exps][:400],
        "detectors": dict(sorted(dets.items())),
        "releases": sorted({e.release for e in exps}), "versions": sorted({e.version or "" for e in exps}),
        "lambda_um": float(np.mean(lams)) if lams else None,
        "lambda_range": [float(min(lams)), float(max(lams))] if lams else None,
        "channels": chan_meta, "flag_summary": flag_summary(all_flags, names),
        "stats": [robust_stats(c) for c in channels],
        "center": {"ra": grid.ra, "dec": grid.dec},
        "width": grid.npix, "height": grid.npix, "n_channels": len(channels),
    }
    return meta, channels, all_flags


async def run_job(job: Job, req: JobRequest) -> None:
    store = get_job_store()
    cache = get_cache()
    s = get_settings()
    try:
        async with _slots():
            await _run(job, req, store, cache, s)
    except Exception as exc:
        log.exception("job %s failed", job.id)
        msg = str(exc)
        if "unavailable" in msg.lower():
            msg = "The IRSA archive is not responding right now. Please try again in a minute."
        store.update(job, status="failed", error=msg, stage="failed")


async def _run(job: Job, req: JobRequest, store: Any, cache: Any, s: Any) -> None:
    t0 = time.time()
    store.update(job, status="running", stage="querying the IRSA archive", progress=0.02)
    releases = active_releases(req.releases)
    exposures = await asyncio.to_thread(find_exposures, req.ra, req.dec, releases)
    bad_bits0 = req.bad_flag_bits if req.bad_flag_bits is not None else s.bad_flag_bits
    real_hash = _hash_for(req, exposures, releases, bad_bits0)
    if real_hash != job.request_hash:
        # the job was created before the exposure list was known (slow SIA query)
        store.update(job, request_hash=real_hash)
        rec = await asyncio.to_thread(cache.get_record, "frame_sets", real_hash)
        if rec and rec.get("status") == "done":
            store.update(job, status="done", stage="done (cached)", progress=1.0,
                         frames=rec.get("frames", []), info={**rec.get("info", {}), "cached": True})
            return
    groups = parse_band(req.band)
    selected = select_exposures(exposures, groups)
    total_found = len(selected)
    selected = cap_exposures(selected, s.max_exposures_per_job)
    plans = plan_frames(selected, groups, req.mode, req.window_days)
    info = {"n_exposures_found": len(exposures), "n_selected": total_found, "n_used_cap": len(selected),
            "n_frames_planned": len(plans), "releases": [r.id for r in releases]}
    if not plans:
        info["reason"] = "SPHEREx has no exposures of this position in the selected releases/bands yet."
        store.update(job, status="done", stage="no coverage", progress=1.0, info=info)
        return

    bad_bits = req.bad_flag_bits if req.bad_flag_bits is not None else s.bad_flag_bits
    bad_mask = bad_mask_value(bad_bits)
    scale = s.pixel_scale_arcsec / req.oversample
    half = snap_half(window_half_px(req.fov_arcsec, s.pixel_scale_arcsec))
    fetcher = get_fetcher()

    n_total = sum(len(p.exposures) for p in plans)
    done_count = 0
    frames_out: dict[int, tuple[dict[str, Any], list[np.ndarray]]] = {}
    fetch_errors: list[str] = []

    def progress(*_: Any) -> None:
        nonlocal done_count
        done_count += 1
        store.update(job, stage=f"downloading {done_count}/{n_total} exposures",
                     progress=0.05 + 0.85 * done_count / max(n_total, 1))

    async def do_frame(plan: FramePlan) -> None:
        t_mid = float(np.mean([e.t_mid for e in plan.exposures]))
        cra, cdec = _frame_centre(req, t_mid)
        grid = make_grid(cra, cdec, req.fov_arcsec, scale)
        cuts = await fetcher.get_many(plan.exposures, [(cra, cdec)] * len(plan.exposures), half, progress,
                                      errors=fetch_errors)
        res = await asyncio.to_thread(build_frame, plan, cuts, req, groups, grid, bad_mask)
        if res is None:
            return
        meta, channels, flags = res
        meta["target"] = _target_at(req, meta["t_mid"], grid)
        meta["grid"] = grid.as_dict()
        frames_out[plan.idx] = (meta, channels)
        await asyncio.to_thread(cache.put_blob, s.cache_bucket,
                                f"{job.request_hash}/flags_{plan.idx}.bin", flags_bytes(flags))
        if req.diff == "none":
            await _publish(meta, channels)

    async def _publish(meta: dict[str, Any], channels: list[np.ndarray]) -> None:
        meta["id"] = f"{job.request_hash}-{meta['idx']}"
        await asyncio.to_thread(cache.put_blob, s.cache_bucket, f"{job.request_hash}/{meta['idx']}.bin",
                                frame_bytes(channels))
        frames = sorted([*job.frames, meta], key=lambda m: m["idx"])
        store.update(job, frames=frames)

    await asyncio.gather(*(do_frame(p) for p in plans))

    if req.diff != "none" and frames_out:
        store.update(job, stage="computing difference images", progress=0.93)
        order = sorted(frames_out)
        n_ch = frames_out[order[0]][1].__len__()
        diffed: list[list[np.ndarray]] = [[] for _ in order]
        for ci in range(n_ch):
            outs = difference([frames_out[i][1][ci].astype(np.float32) for i in order], req.diff)
            for k, arr in enumerate(outs):
                diffed[k].append(arr)
        for k, i in enumerate(order):
            meta = frames_out[i][0]
            meta["stats"] = [robust_stats(c) for c in diffed[k]]
            await _publish(meta, diffed[k])

    # renumber frames contiguously (some planned epochs may have had no usable data)
    frames = sorted(job.frames, key=lambda m: m["t_mid"])
    grid_info = frames[0]["grid"] if frames else None
    gstats = _global_stats(job.request_hash, frames, cache, s)
    info.update({"seconds": round(time.time() - t0, 1), "global_stats": gstats,
                 "bytes_downloaded": fetcher.bytes_downloaded})
    if not frames:
        info["reason"] = "Exposures were found, but none had usable pixels at this position."
    info["n_fetch_errors"] = len(fetch_errors)
    record = {"request": req.normalized(), "release_versions": release_versions(exposures),
              "frames": frames, "grid": grid_info, "info": info, "status": "done"}
    if len(fetch_errors) > 0.1 * n_total:
        # Too many downloads failed (archive hiccup): show what we have, but do not cache it
        # as the definitive answer, so the next request tries again.
        info["warning"] = f"{len(fetch_errors)} of {n_total} exposures could not be downloaded; result not cached."
        log.warning("job %s: %d/%d fetch errors, not caching", job.id, len(fetch_errors), n_total)
    else:
        await asyncio.to_thread(cache.put_record, "frame_sets", job.request_hash, record,
                                {"status": "done", "n_frames": len(frames), "request": req.normalized(),
                                 "release_versions": release_versions(exposures), "wcs": grid_info})
    store.update(job, status="done", stage="done", progress=1.0, frames=frames, info=info)
    log.info("job %s done: %d frames in %.1fs", job.id, len(frames), time.time() - t0)


def _global_stats(h: str, frames: list[dict[str, Any]], cache: Any, s: Any) -> list[dict[str, float]]:
    """Percentile limits across ALL frames (per channel) so the blink is stable."""
    if not frames:
        return []
    n_ch = frames[0]["n_channels"]
    out = []
    from app.services.render import decode_frame

    per_ch: list[list[np.ndarray]] = [[] for _ in range(n_ch)]
    for m in frames:
        raw = cache.get_blob(s.cache_bucket, f"{h}/{m['idx']}.bin")
        if raw is None:
            continue
        for ci, c in enumerate(decode_frame(raw, m["width"], m["height"], n_ch)):
            per_ch[ci].append(c.ravel())
    for arrs in per_ch:
        out.append(robust_stats(np.concatenate(arrs)) if arrs else robust_stats(np.array([])))
    return out


# ---------------------------------------------------------------- entry point
def _hash_for(req: JobRequest, exposures: list[Exposure], releases: list[Any], bad_bits: list[int]) -> str:
    # Versions come from the exposure list; a new processing version or release
    # changes the hash, which invalidates old frame sets automatically.
    return request_hash(req, release_versions(exposures) | {"_ids": ",".join(r.id for r in releases)}, bad_bits)


async def submit(req: JobRequest) -> Job:
    """Create (or reuse) a job for this request. Returns immediately: if the exposure
    list for this position is not cached yet (the SIA query can take >1 min in deep
    fields), the job starts with a provisional hash that is replaced once it is known."""
    store = get_job_store()
    cache = get_cache()
    s = get_settings()
    releases = active_releases(req.releases)
    bad_bits = req.bad_flag_bits if req.bad_flag_bits is not None else s.bad_flag_bits
    exposures = await asyncio.to_thread(cached_exposures, req.ra, req.dec, releases)
    if exposures is not None:
        h = _hash_for(req, exposures, releases, bad_bits)
    else:
        h = "pending-" + stable_hash({"req": req.normalized(), "rel": [r.id for r in releases], "bits": bad_bits}, 32)
    active = store.find_active(h)
    if active:
        return active
    job = store.create(h)
    if exposures is not None:
        rec = await asyncio.to_thread(cache.get_record, "frame_sets", h)
        if rec and rec.get("status") == "done":
            store.update(job, status="done", stage="done (cached)", progress=1.0,
                         frames=rec.get("frames", []), info={**rec.get("info", {}), "cached": True})
            return job
    task = asyncio.get_running_loop().create_task(run_job(job, req))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return job
