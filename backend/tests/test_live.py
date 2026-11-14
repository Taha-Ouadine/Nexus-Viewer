"""Live tests against IRSA / CDS. Slow; not run by default.

    pytest -m live            # all live tests
    pytest -m live -k barnard # one target
"""

from __future__ import annotations

import asyncio
import json

import numpy as np
import pytest

from app.core.config import get_settings
from app.schemas.models import JobRequest, ProperMotion
from app.services.cache import get_cache, get_job_store
from app.services.irsa import find_exposures
from app.services.releases import active_releases
from app.services.render import decode_frame
from app.workers import job_runner

pytestmark = pytest.mark.live

TARGETS = {t["slug"]: t for t in json.loads((get_settings().data_dir / "targets.json").read_text())}
REQUIRED = ["barnards-star", "eps-indi-b", "wise-0855", "rw-aur", "r-dra"]


@pytest.mark.parametrize("slug", REQUIRED)
def test_observations_have_two_epochs(slug: str):
    from app.services.epochs import cluster_times

    t = TARGETS[slug]
    exps = find_exposures(t["view_ra"], t["view_dec"], active_releases())
    assert len(exps) > 50
    assert len(cluster_times([e.t_mid for e in exps], 30)) >= 2


async def _run(req: JobRequest) -> dict:
    job = await job_runner.submit(req)
    for _ in range(600):
        if job.status in ("done", "failed"):
            break
        await asyncio.sleep(1)
    assert job.status == "done", job.error
    return job.public()


def _centroid(img: np.ndarray, x0: float, y0: float, r: int = 3) -> tuple[float, float]:
    xi, yi = int(round(x0)), int(round(y0))
    sub = np.nan_to_num(img[yi - r:yi + r + 1, xi - r:xi + r + 1])
    sub = np.clip(sub - np.median(sub), 0, None)
    yy, xx = np.mgrid[yi - r:yi + r + 1, xi - r:xi + r + 1]
    return float((xx * sub).sum() / sub.sum()), float((yy * sub).sum() / sub.sum())


def _req(slug: str, band: str) -> JobRequest:
    t = TARGETS[slug]
    pm = None
    if t.get("pmra_masyr") is not None:
        pm = ProperMotion(pmra=t["pmra_masyr"], pmdec=t["pmdec_masyr"], ref_epoch=t["ref_epoch"],
                          ra=t["ra_deg"], dec=t["dec_deg"])
    return JobRequest(ra=t["view_ra"], dec=t["view_dec"], fov_arcsec=180, band=band, pm=pm)


def test_wise0855_d6_job_and_cache():
    res = asyncio.run(_run(_req("wise-0855", "D6")))
    assert len(res["frames"]) >= 2
    # second identical request is served from cache
    import time

    t0 = time.time()
    res2 = asyncio.run(_run(_req("wise-0855", "D6")))
    assert time.time() - t0 < 1.5 and res2["info"].get("cached")


def test_barnard_motion_matches_proper_motion():
    res = asyncio.run(_run(_req("barnards-star", "ALL")))
    frames = res["frames"]
    assert len(frames) >= 2
    first, last = frames[0], frames[-1]
    cache = get_cache()
    h = res["request_hash"]

    def img(m: dict) -> np.ndarray:
        raw = cache.get_blob(get_settings().cache_bucket, f"{h}/{m['idx']}.bin")
        return decode_frame(raw, m["width"], m["height"], m["n_channels"])[0]

    c1 = _centroid(img(first), first["target"]["x"], first["target"]["y"])
    c2 = _centroid(img(last), last["target"]["x"], last["target"]["y"])
    measured = np.hypot(c2[0] - c1[0], c2[1] - c1[1]) * 6.15  # arcsec
    dt_yr = (last["t_mid"] - first["t_mid"]) / 365.25
    expected = 10.39 * dt_yr
    assert expected * 0.5 < measured < expected * 1.5, (measured, expected)
    # it moves north: display row decreases
    assert c2[1] < c1[1]
    get_job_store()  # keep import used
