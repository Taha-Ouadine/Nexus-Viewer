"""Catalog overlays: Gaia DR3 (ESA archive) and CatWISE2020 / AllWISE (IRSA).

Positions are returned at the catalog epoch together with proper motions, so the
browser can move each source to the date of every frame (`lib/coords.ts`)."""

from __future__ import annotations

import io
import logging
import math
import warnings
from typing import Any

import httpx
import numpy as np

from app.core.config import get_settings
from app.core.errors import UpstreamUnavailable
from app.services.cache import get_cache, stable_hash
from app.services.resolver import propagate

log = logging.getLogger(__name__)

GAIA_EPOCH = 2016.0
CATWISE_EPOCH = 2015.4    # CatWISE2020 positions are at MJD 57170
ALLWISE_EPOCH = 2010.5


def _tap(url: str, adql: str, timeout: float = 60.0) -> Any:
    from astropy.io.votable import parse_single_table

    last: Exception | None = None
    for _ in range(3):
        try:
            r = httpx.post(url.rstrip("/") + "/sync",
                           data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "votable", "QUERY": adql},
                           timeout=timeout, follow_redirects=True)
            r.raise_for_status()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                return parse_single_table(io.BytesIO(r.content)).to_table(use_names_over_ids=True)
        except Exception as exc:
            last = exc
    raise UpstreamUnavailable("catalog", str(last))


def _radius_deg(fov_arcsec: float, margin_arcsec: float) -> float:
    return (fov_arcsec / 2 * math.sqrt(2) + margin_arcsec) / 3600.0


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if (np.ma.is_masked(v) or math.isnan(x)) else x


def gaia_sources(ra: float, dec: float, fov_arcsec: float, epoch_mjd: float | None = None,
                 max_rows: int = 2000) -> dict[str, Any]:
    # 150" margin so that fast movers (Barnard's Star: ~104" between 2016 and 2026) are included
    r = _radius_deg(fov_arcsec, 150.0)
    key = stable_hash({"cat": "gaia", "ra": round(ra, 4), "dec": round(dec, 4), "r": round(r, 4)})
    cache = get_cache()
    hit = cache.get_record("overlay_cache", key)
    if hit is None:
        adql = (f"SELECT TOP {max_rows} source_id, ra, dec, pmra, pmdec, parallax, phot_g_mean_mag "
                f"FROM gaiadr3.gaia_source WHERE 1=CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra}, {dec}, {r})) "
                "ORDER BY phot_g_mean_mag ASC")
        t = _tap(get_settings().gaia_tap_url, adql)
        rows = [{"source_id": str(x["source_id"]), "ra": float(x["ra"]), "dec": float(x["dec"]),
                 "pmra": _f(x["pmra"]), "pmdec": _f(x["pmdec"]), "parallax": _f(x["parallax"]),
                 "gmag": _f(x["phot_g_mean_mag"])} for x in t]
        hit = {"catalog": "gaia_dr3", "ref_epoch": GAIA_EPOCH, "sources": rows}
        cache.put_record("overlay_cache", key, hit, {"catalog": "gaia_dr3"})
    return _with_epoch(hit, epoch_mjd)


def wise_sources(ra: float, dec: float, fov_arcsec: float, catalog: str = "catwise_2020",
                 epoch_mjd: float | None = None, max_rows: int = 2000) -> dict[str, Any]:
    if catalog not in ("catwise_2020", "allwise_p3as_psd"):
        raise ValueError("catalog must be catwise_2020 or allwise_p3as_psd")
    r = _radius_deg(fov_arcsec, 150.0)
    key = stable_hash({"cat": catalog, "ra": round(ra, 4), "dec": round(dec, 4), "r": round(r, 4)})
    cache = get_cache()
    hit = cache.get_record("overlay_cache", key)
    if hit is None:
        cols = ("source_name, ra, dec, pmra, pmdec, w1mpro, w2mpro" if catalog == "catwise_2020"
                else "designation as source_name, ra, dec, w1mpro, w2mpro")
        adql = (f"SELECT TOP {max_rows} {cols} FROM {catalog} WHERE "
                f"1=CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra}, {dec}, {r})) ORDER BY w2mpro ASC")
        t = _tap(get_settings().irsa_tap_url, adql)
        rows = []
        for x in t:
            pmra = _f(x["pmra"]) if "pmra" in t.colnames else None
            pmdec = _f(x["pmdec"]) if "pmdec" in t.colnames else None
            rows.append({"source_id": str(x["source_name"]).strip(), "ra": float(x["ra"]), "dec": float(x["dec"]),
                         # CatWISE proper motions are in arcsec/yr -> mas/yr
                         "pmra": pmra * 1000 if pmra is not None else None,
                         "pmdec": pmdec * 1000 if pmdec is not None else None,
                         "w1": _f(x["w1mpro"]), "w2": _f(x["w2mpro"])})
        hit = {"catalog": catalog, "ref_epoch": CATWISE_EPOCH if catalog == "catwise_2020" else ALLWISE_EPOCH,
               "sources": rows}
        cache.put_record("overlay_cache", key, hit, {"catalog": catalog})
    return _with_epoch(hit, epoch_mjd)


def _with_epoch(payload: dict[str, Any], epoch_mjd: float | None) -> dict[str, Any]:
    if epoch_mjd is None:
        return payload
    out = []
    for s in payload["sources"]:
        ra_e, dec_e = propagate(s["ra"], s["dec"], s.get("pmra"), s.get("pmdec"), payload["ref_epoch"], epoch_mjd)
        out.append({**s, "ra_at_epoch": ra_e, "dec_at_epoch": dec_e})
    return {**payload, "epoch_mjd": epoch_mjd, "sources": out}
