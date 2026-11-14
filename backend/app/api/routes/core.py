"""Health, name resolution, releases, targets, bands and observation listing."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.core.config import get_settings
from app.services.cache import get_cache
from app.services.epochs import summarize_epochs
from app.services.irsa import find_exposures, nominal_lambda, release_versions
from app.services.releases import active_releases, all_releases
from app.services.resolver import resolve_name
from app.services.wavelength import DETECTORS, PRESETS, nominal_channels

router = APIRouter()

_irsa_state: dict[str, Any] = {"t": 0.0, "up": None}


async def _irsa_up() -> bool:
    if time.time() - _irsa_state["t"] < 60 and _irsa_state["up"] is not None:
        return bool(_irsa_state["up"])
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(get_settings().irsa_sia_url, params={"FORMAT": "METADATA"})
        up = r.status_code < 500
    except Exception:
        up = False
    _irsa_state.update(t=time.time(), up=up)
    return up


@router.get("/health")
async def health() -> dict[str, Any]:
    up = await _irsa_up()
    return {
        "ok": True,
        "irsa": "up" if up else "down",
        "cache_backend": get_cache().name,
        "releases": [r.id for r in active_releases()],
    }


@router.get("/resolve")
async def resolve(name: str = Query(..., min_length=1, max_length=120)) -> dict[str, Any]:
    return await asyncio.to_thread(resolve_name, name)


@router.get("/releases")
async def releases() -> list[dict[str, Any]]:
    return [r.model_dump() for r in all_releases()]


def _load_targets() -> list[dict[str, Any]]:
    from app.services.cache import SupabaseCache

    cache = get_cache()
    if isinstance(cache, SupabaseCache):
        try:
            res = cache.client.table("targets").select("*").order("sort_order").execute()
            if res.data:
                return list(res.data)
        except Exception:
            pass
    path = get_settings().data_dir / "targets.json"
    return list(json.loads(path.read_text(encoding="utf-8")))


@router.get("/targets")
async def targets() -> list[dict[str, Any]]:
    return sorted(_load_targets(), key=lambda t: t.get("sort_order", 0))


@router.get("/targets/{slug}")
async def target(slug: str) -> dict[str, Any]:
    for t in _load_targets():
        if t["slug"] == slug:
            return t
    raise HTTPException(404, f"No featured target called '{slug}'.")


@router.get("/bands")
async def bands() -> dict[str, Any]:
    return {"channels": nominal_channels(), "presets": PRESETS,
            "detectors": [{"id": f"D{k}", "lambda_min": lo, "lambda_max": hi, "R": r}
                          for k, (lo, hi, r) in DETECTORS.items()]}


@router.get("/observations")
async def observations(
    ra: float = Query(..., ge=0, lt=360), dec: float = Query(..., ge=-90, le=90),
    releases: str | None = None, bands: str | None = None,
    epoch_gap_days: float = Query(30.0, gt=0, le=400),
) -> dict[str, Any]:
    rels = active_releases(releases.split(",") if releases else None)
    exps = await asyncio.to_thread(find_exposures, ra, dec, rels)
    if bands:
        dets = {int(b.strip().upper().lstrip("D")) for b in bands.split(",") if b.strip()}
        exps = [e for e in exps if e.detector in dets]
    epochs = summarize_epochs([e.t_mid for e in exps], [e.t_max for e in exps], [e.detector for e in exps],
                              epoch_gap_days)
    out: dict[str, Any] = {
        "ra": ra, "dec": dec, "releases": [r.id for r in rels],
        "release_versions": release_versions(exps),
        "exposures": [{"obs_id": e.key, "t_mid": e.t_mid, "detector": f"D{e.detector}", "release": e.release,
                       "lambda_range_um": [e.em_min_um, e.em_max_um], "lambda_nominal_um": nominal_lambda(e),
                       "version": e.version, "uri": e.uri} for e in exps],
        "epochs": epochs,
    }
    if not exps:
        out["reason"] = "SPHEREx has not observed this position yet in the selected releases."
    return out
