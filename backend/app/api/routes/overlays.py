from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.services.overlays import gaia_sources, wise_sources

router = APIRouter()


@router.get("/overlays/gaia")
async def gaia(ra: float = Query(..., ge=0, lt=360), dec: float = Query(..., ge=-90, le=90),
               fov_arcsec: float = Query(180, gt=0, le=1800), epoch_mjd: float | None = None) -> dict[str, Any]:
    return await asyncio.to_thread(gaia_sources, ra, dec, fov_arcsec, epoch_mjd)


@router.get("/overlays/wise")
async def wise(ra: float = Query(..., ge=0, lt=360), dec: float = Query(..., ge=-90, le=90),
               fov_arcsec: float = Query(180, gt=0, le=1800), catalog: str = "catwise_2020",
               epoch_mjd: float | None = None) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(wise_sources, ra, dec, fov_arcsec, catalog, epoch_mjd)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
