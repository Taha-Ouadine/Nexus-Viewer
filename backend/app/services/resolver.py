"""Name -> coordinates (+ proper motion), and epoch propagation of positions."""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from app.core.config import get_settings
from app.core.errors import NotFoundError, UpstreamUnavailable
from app.services.cache import get_cache

log = logging.getLogger(__name__)

MJD_J2000 = 51544.5
DAYS_PER_YEAR = 365.25


def norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _fnum(el: Any) -> float | None:
    if el is None or el.text is None:
        return None
    try:
        v = float(el.text)
    except ValueError:
        return None
    return None if math.isnan(v) else v


def _sesame_xml(name: str) -> dict[str, Any] | None:
    """CDS Sesame (SIMBAD first, then NED/VizieR) in XML form: position (ICRS, J2000),
    proper motion and parallax in one call. CDS redirects to a mirror when busy."""
    import xml.etree.ElementTree as ET
    from urllib.parse import quote

    import httpx

    r = None
    bases = [get_settings().sesame_url, *get_settings().sesame_mirrors.split(",")]
    for base in (b for b in bases if b):
        try:
            r = httpx.get(base.rstrip("/") + "/-oxp/SNV?" + quote(name), timeout=20, follow_redirects=True,
                          headers={"User-Agent": "NexusViewer/0.1 (student project)"})
            r.raise_for_status()
            break
        except httpx.HTTPError as exc:
            log.info("Sesame %s failed (%s); trying next mirror", base, exc)
            r = None
    if r is None:
        raise UpstreamUnavailable("CDS Sesame", "all mirrors failed")
    root = ET.fromstring(r.text)
    for res in root.iter("Resolver"):
        ra, dec = _fnum(res.find("jradeg")), _fnum(res.find("jdedeg"))
        if ra is None or dec is None:
            continue
        pm = res.find("pm")
        plx = res.find("plx")
        oname = res.find("oname")
        otype = res.find("otype")
        return {
            "name": oname.text if oname is not None and oname.text else name,
            "ra": ra, "dec": dec,
            "pmra": _fnum(pm.find("pmRA")) if pm is not None else None,
            "pmdec": _fnum(pm.find("pmDE")) if pm is not None else None,
            "parallax": _fnum(plx.find("v")) if plx is not None else None,
            "ref_epoch": 2000.0, "otype": otype.text if otype is not None else None,
            "source": "Sesame/" + (res.get("name") or "CDS").split(",")[0].replace("S=", ""),
        }
    return None


def _sesame(name: str) -> dict[str, Any] | None:
    from astropy.coordinates import SkyCoord

    c = SkyCoord.from_name(name)
    return {"name": name, "ra": float(c.ra.deg), "dec": float(c.dec.deg), "pmra": None, "pmdec": None,
            "parallax": None, "ref_epoch": 2000.0, "otype": None, "source": "Sesame"}


def resolve_name(name: str) -> dict[str, Any]:
    key = norm_name(name)
    cache = get_cache()
    hit = cache.get_record("resolved_names", key)
    if hit:
        return hit
    errors: list[str] = []
    result: dict[str, Any] | None = None
    for fn in (_sesame_xml, _sesame):
        try:
            result = fn(name)
            if result:
                break
        except Exception as exc:
            errors.append(f"{fn.__name__}: {exc}")
    if result is None:
        if errors and all("not" not in e.lower() for e in errors):
            raise UpstreamUnavailable("CDS name resolver", "; ".join(errors))
        raise NotFoundError(f"Could not find an object called '{name}'.")
    result["query"] = name
    cache.put_record("resolved_names", key, result)
    return result


def propagate(ra: float, dec: float, pmra: float | None, pmdec: float | None,
              ref_epoch: float, mjd: float) -> tuple[float, float]:
    """Linear proper-motion propagation (mas/yr; pmra includes cos(dec)) from Julian-year
    `ref_epoch` to `mjd`. Accurate to far below a SPHEREx pixel for any star over decades;
    parallax (< 1 arcsec, i.e. < 0.2 px) is ignored."""
    if not pmra and not pmdec:
        return ra, dec
    t_ref_mjd = MJD_J2000 + (ref_epoch - 2000.0) * DAYS_PER_YEAR
    dt_yr = (mjd - t_ref_mjd) / DAYS_PER_YEAR
    ddec = (pmdec or 0.0) * dt_yr / 3.6e6
    cosd = max(math.cos(math.radians(dec)), 1e-6)
    dra = (pmra or 0.0) * dt_yr / 3.6e6 / cosd
    return (ra + dra) % 360.0, dec + ddec


def mjd_to_jyear(mjd: float) -> float:
    return 2000.0 + (mjd - MJD_J2000) / DAYS_PER_YEAR
