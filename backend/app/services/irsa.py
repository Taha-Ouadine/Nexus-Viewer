"""Finding SPHEREx exposures that cover a sky position.

Primary path: IRSA SIA v2 (fast: ~4 s for a full DR1+QR3 search).
Fallback:     IRSA TAP on `spherex.obscore` (no ingestion lag, but slow; Phase 0 saw
              multi-minute queries and 502 proxy errors on the plane/artifact join).
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.core.errors import UpstreamUnavailable
from app.services.cache import get_cache, stable_hash
from app.services.releases import Release, release_for_collection

log = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"_spx_(l2b[^/]*?)\.fits", re.I)


@dataclass
class Exposure:
    obs_id: str
    detector: int
    release: str
    collection: str
    uri: str
    s3_key: str | None
    t_min: float          # MJD
    t_max: float          # MJD
    em_min_um: float
    em_max_um: float
    version: str | None   # processing version, e.g. l2b-v27-2026-228

    @property
    def t_mid(self) -> float:
        return 0.5 * (self.t_min + self.t_max)

    @property
    def key(self) -> str:
        return f"{self.obs_id}D{self.detector}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["t_mid"] = self.t_mid
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Exposure":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__})


def _detector(bandpass: str) -> int:
    m = re.search(r"D(\d)", str(bandpass))
    return int(m.group(1)) if m else 0


def _s3_key(cloud_access: Any) -> str | None:
    try:
        return str(json.loads(str(cloud_access))["aws"]["key"])
    except Exception:
        return None


def _rows_to_exposures(table: Any, releases: list[Release]) -> list[Exposure]:
    out: list[Exposure] = []
    for row in table:
        coll = str(row["obs_collection"])
        rel = release_for_collection(coll, releases)
        if rel is None:
            continue
        if str(row["dataproduct_type"]) != "image" or int(row["calib_level"]) != 2:
            continue
        uri = str(row["access_url"])
        m = _VERSION_RE.search(uri)
        out.append(Exposure(
            obs_id=str(row["obs_id"]), detector=_detector(row["energy_bandpassname"]),
            release=rel.id, collection=coll, uri=uri,
            s3_key=_s3_key(row["cloud_access"]) if "cloud_access" in row.colnames else None,
            t_min=float(row["t_min"]), t_max=float(row["t_max"]),
            em_min_um=float(row["em_min"]) * 1e6, em_max_um=float(row["em_max"]) * 1e6,
            version=m.group(1) if m else None,
        ))
    return out


def dedupe(exposures: list[Exposure], releases: list[Release]) -> list[Exposure]:
    """Same exposure (obs_id + detector) in several releases -> keep the highest-priority release."""
    prio = {r.id: r.priority for r in releases}
    best: dict[str, Exposure] = {}
    for e in exposures:
        cur = best.get(e.key)
        if cur is None or prio.get(e.release, 0) > prio.get(cur.release, 0):
            best[e.key] = e
    return sorted(best.values(), key=lambda e: (e.t_min, e.detector))


def _votable(content: bytes) -> Any:
    import io
    import warnings

    from astropy.io.votable import parse_single_table

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return parse_single_table(io.BytesIO(content)).to_table(use_names_over_ids=True)


def _query_sia(ra: float, dec: float, collections: list[str], timeout: float = 240.0) -> Any:
    """IRSA SIA v2 query (the same service `Irsa.query_sia` uses), called directly so
    that a hard timeout applies (pyvo/astroquery have none and Phase 0 saw hangs)."""
    import httpx

    params: list[tuple[str, str]] = [("POS", f"CIRCLE {ra} {dec} 0.0003"), ("RESPONSEFORMAT", "votable")]
    params += [("COLLECTION", c) for c in collections]
    r = httpx.get(get_settings().irsa_sia_url, params=params, timeout=timeout, follow_redirects=True,
                  headers={"User-Agent": "NexusViewer/0.1 (student project)"})
    r.raise_for_status()
    return _votable(r.content)


def _query_tap(ra: float, dec: float, collections: list[str], timeout: float = 300.0) -> Any:
    import httpx

    colls = ",".join(f"'{c}'" for c in collections)
    adql = (
        "SELECT obs_id, obs_collection, energy_bandpassname, access_url, cloud_access, "
        "t_min, t_max, em_min, em_max, dataproduct_type, calib_level FROM spherex.obscore "
        f"WHERE 1=CONTAINS(POINT('ICRS',{ra},{dec}), s_region) AND obs_collection IN ({colls})"
    )
    r = httpx.post(get_settings().irsa_tap_url.rstrip("/") + "/sync",
                   data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "votable", "QUERY": adql},
                   timeout=timeout, follow_redirects=True)
    r.raise_for_status()
    return _votable(r.content)


def _obs_key(ra: float, dec: float, releases: list[Release]) -> str:
    collections = sorted({c for r in releases for c in r.sia_collections})
    return stable_hash({"ra": round(ra, 5), "dec": round(dec, 5), "collections": collections})


def cached_exposures(ra: float, dec: float, releases: list[Release]) -> list[Exposure] | None:
    """Exposure list from the cache only (no network); None if not cached / expired.
    Data is ingested weekly; a 24 h lifetime keeps lists fresh without hammering IRSA."""
    hit = get_cache().get_record("observation_cache", _obs_key(ra, dec, releases), max_age_s=24 * 3600)
    return [Exposure.from_dict(d) for d in hit["exposures"]] if hit is not None else None


def find_exposures(ra: float, dec: float, releases: list[Release], use_cache: bool = True) -> list[Exposure]:
    """All Level-2 exposures (every detector) whose footprint contains (ra, dec)."""
    collections = sorted({c for r in releases for c in r.sia_collections})
    key = _obs_key(ra, dec, releases)
    cache = get_cache()
    if use_cache:
        hit = cached_exposures(ra, dec, releases)
        if hit is not None:
            return hit

    last_exc: Exception | None = None
    table = None
    for attempt in range(3):
        try:
            t0 = time.time()
            table = _query_sia(ra, dec, collections)
            log.info("SIA %d rows in %.1fs at (%.4f, %.4f)", len(table), time.time() - t0, ra, dec)
            break
        except Exception as exc:
            last_exc = exc
            log.warning("SIA attempt %d failed: %s", attempt + 1, exc)
            time.sleep(2 ** attempt)
    if table is None:
        try:
            table = _query_tap(ra, dec, collections)
        except Exception as exc:
            raise UpstreamUnavailable("IRSA", f"SIA: {last_exc}; TAP: {exc}") from exc

    exposures = dedupe(_rows_to_exposures(table, releases), releases)
    cache.put_record(
        "observation_cache", key, {"exposures": [e.to_dict() for e in exposures]},
        columns={"ra_deg": ra, "dec_deg": dec, "releases": [r.id for r in releases]},
    )
    return exposures


def _vkey(v: str) -> tuple[int, ...]:
    """'l2b-v27-2026-228' / 'l2b_retry-v27-2026-230' -> (27, 2026, 228) for ordering."""
    return tuple(int(x) for x in re.findall(r"\d+", v))


def release_versions(exposures: list[Exposure]) -> dict[str, str]:
    """Latest processing version seen per release (feeds cache keys)."""
    out: dict[str, str] = {}
    for e in exposures:
        if e.version and _vkey(e.version) > _vkey(out.get(e.release, "")):
            out[e.release] = e.version
    return out


def thin_exposures(exposures: list[Exposure], cap: int) -> list[Exposure]:
    """Keep at most `cap` exposures, evenly spread in time WITHIN each detector, so every
    detector keeps its share (a plain stride over a (time, detector)-sorted list aliases
    detectors: Phase-5 testing on R Dra lost all D4 points that way)."""
    if len(exposures) <= cap:
        return exposures
    by_det: dict[int, list[Exposure]] = {}
    for e in sorted(exposures, key=lambda e: e.t_mid):
        by_det.setdefault(e.detector, []).append(e)
    out: list[Exposure] = []
    for lst in by_det.values():
        k = max(1, round(cap * len(lst) / len(exposures)))
        idx = np.linspace(0, len(lst) - 1, min(k, len(lst))).round().astype(int)
        out.extend(lst[i] for i in sorted(set(idx.tolist())))
    return sorted(out, key=lambda e: (e.t_min, e.detector))


def nominal_lambda(e: Exposure) -> float:
    return float(np.mean([e.em_min_um, e.em_max_um]))
