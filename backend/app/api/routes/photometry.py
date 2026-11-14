"""Spectrum and light curve at a position.

Measuring hundreds of exposures can take a minute or more when nothing is cached,
so these endpoints work asynchronously: the first call starts a background task
and answers 202 with progress; the client polls the same URL until it gets 200.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import numpy as np
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.ratelimit import limiter
from app.services.cache import stable_hash
from app.services.photometry import bin_spectrum, photometry_points
from app.services.releases import active_releases
from app.services.wavelength import nominal_channels, parse_group

log = logging.getLogger(__name__)
router = APIRouter()

_tasks: dict[str, dict[str, Any]] = {}


def _pm(pmra: float | None, pmdec: float | None, ref_epoch: float, pm_ra: float | None,
        pm_dec: float | None) -> dict[str, float] | None:
    if pmra is None and pmdec is None:
        return None
    d: dict[str, float] = {"pmra": pmra or 0.0, "pmdec": pmdec or 0.0, "ref_epoch": ref_epoch}
    if pm_ra is not None and pm_dec is not None:
        d["ra"], d["dec"] = pm_ra, pm_dec
    return d


def _task_key(ra: float, dec: float, aperture: float, releases: str | None, pm: dict[str, float] | None) -> str:
    rels = active_releases(releases.split(",") if releases else None)
    return stable_hash({"ra": round(ra, 5), "dec": round(dec, 5), "ap": aperture, "rel": [r.id for r in rels], "pm": pm})


def _is_poll(request: Request) -> bool:
    """Rate-limit exemption: the browser polls the same URL every 2 s while a measurement
    runs (and asks again for the finished result). Only requests that would *start* new
    work count against the limit."""
    try:
        q = request.query_params

        def opt(name: str) -> float | None:
            return float(q[name]) if q.get(name) not in (None, "") else None

        pm = _pm(opt("pmra"), opt("pmdec"), float(q.get("ref_epoch", 2000.0)), opt("pm_ra"), opt("pm_dec"))
        key = _task_key(float(q["ra"]), float(q["dec"]), float(q.get("aperture_arcsec", 12.0)),
                        q.get("releases"), pm)
    except Exception:
        return False
    return key in _tasks


async def _points(ra: float, dec: float, aperture: float, releases: str | None,
                  pm: dict[str, float] | None) -> tuple[int, dict[str, Any]]:
    rels = active_releases(releases.split(",") if releases else None)
    key = _task_key(ra, dec, aperture, releases, pm)
    st = _tasks.get(key)
    if st and st["status"] == "done":
        return 200, st["result"]
    if st and st["status"] == "running":
        return 202, {"status": "running", "progress": st["progress"], "stage": st["stage"]}

    state: dict[str, Any] = {"status": "running", "progress": 0.0, "stage": "finding exposures"}
    _tasks[key] = state

    def prog(done: int, total: int, *_: Any) -> None:
        state["progress"] = done / max(total, 1)
        state["stage"] = f"measuring {done}/{total} exposures"

    async def run() -> None:
        try:
            state["result"] = await photometry_points(ra, dec, aperture, rels, pm, on_progress=prog)
            state["status"] = "done"
        except Exception as exc:
            log.exception("photometry failed")
            state.update(status="failed", error=str(exc))

    task = asyncio.create_task(run())
    # if it is already cached this finishes almost immediately
    done, _ = await asyncio.wait({task}, timeout=8)
    if task in done and state["status"] == "done":
        return 200, state["result"]
    if state["status"] == "failed":
        _tasks.pop(key, None)
        return 503, {"detail": "Photometry failed: " + state.get("error", "unknown error")}
    state["task"] = task
    return 202, {"status": "running", "progress": state["progress"], "stage": state["stage"]}


@router.get("/spectrum")
@limiter.limit(lambda: get_settings().rate_limit_photometry, exempt_when=_is_poll)
async def spectrum(
    request: Request,
    ra: float = Query(..., ge=0, lt=360), dec: float = Query(..., ge=-90, le=90),
    aperture_arcsec: float = Query(12.0, gt=1, le=60), epochs: str = "all", releases: str | None = None,
    pmra: float | None = None, pmdec: float | None = None, ref_epoch: float = 2000.0,
    pm_ra: float | None = None, pm_dec: float | None = None,
) -> JSONResponse:
    code, body = await _points(ra, dec, aperture_arcsec, releases, _pm(pmra, pmdec, ref_epoch, pm_ra, pm_dec))
    if code != 200:
        return JSONResponse(body, status_code=code)
    pts = [p for p in body["points"] if p.get("lambda_um")]
    channels = nominal_channels()
    out: dict[str, Any] = {**{k: v for k, v in body.items() if k != "points"}, "points": pts,
                           "binned": bin_spectrum(pts, channels)}
    if epochs == "split":
        out["binned_by_epoch"] = {
            str(e["index"]): bin_spectrum([p for p in pts if p.get("epoch") == e["index"]], channels)
            for e in body["epochs"]
        }
    return JSONResponse(out)


@router.get("/lightcurve")
@limiter.limit(lambda: get_settings().rate_limit_photometry, exempt_when=_is_poll)
async def lightcurve(
    request: Request,
    ra: float = Query(..., ge=0, lt=360), dec: float = Query(..., ge=-90, le=90),
    band: str = "D1", aperture_arcsec: float = Query(12.0, gt=1, le=60), releases: str | None = None,
    pmra: float | None = None, pmdec: float | None = None, ref_epoch: float = 2000.0,
    pm_ra: float | None = None, pm_dec: float | None = None,
) -> JSONResponse:
    try:
        group = parse_group(band)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=422)
    code, body = await _points(ra, dec, aperture_arcsec, releases, _pm(pmra, pmdec, ref_epoch, pm_ra, pm_dec))
    if code != 200:
        return JSONResponse(body, status_code=code)
    pts = [p for p in body["points"] if p["detector"] in group.detectors]
    if group.lam_range:
        lo, hi = group.lam_range
        pts = [p for p in pts if p.get("lambda_um") and lo <= p["lambda_um"] <= hi]
    per_epoch = []
    for e in body["epochs"]:
        in_epoch = [p for p in pts if p.get("epoch") == e["index"] and p["err_uJy"] > 0]
        sel = [p for p in in_epoch if not p["flagged"]]
        only_flagged = not sel
        sel = sel or in_epoch  # bright (saturated) stars: use flagged points, but say so
        if not sel:
            continue
        w = np.array([1 / p["err_uJy"] ** 2 for p in sel])
        f = np.array([p["flux_uJy"] for p in sel])
        per_epoch.append({"epoch": e["index"], "t_mid": float(np.mean([p["t_mid"] for p in sel])),
                          "flux_uJy": float(np.sum(w * f) / np.sum(w)), "err_uJy": float(1 / np.sqrt(np.sum(w))),
                          "scatter_uJy": float(np.std(f)), "n": len(sel), "flagged": only_flagged})
    return JSONResponse({"ra": ra, "dec": dec, "band": group.label,
                         "points": [{k: p.get(k) for k in ("t_mid", "flux_uJy", "err_uJy", "lambda_um", "detector",
                                                         "flagged", "saturated", "epoch", "obs_id")} for p in pts],
                         "per_epoch": per_epoch, "epochs": body["epochs"], "pm_tracked": body.get("pm_tracked")})
