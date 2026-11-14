"""API tests that need no network (cache/static endpoints)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_releases():
    r = client.get("/api/releases")
    assert r.status_code == 200
    ids = {x["id"] for x in r.json()}
    assert {"dr1", "qr3"} <= ids


def test_targets_has_the_five_required():
    r = client.get("/api/targets")
    assert r.status_code == 200
    slugs = {t["slug"] for t in r.json()}
    assert {"barnards-star", "eps-indi-b", "wise-0855", "rw-aur", "r-dra"} <= slugs
    t = client.get("/api/targets/wise-0855").json()
    assert t["pmra_masyr"] < -8000
    assert abs(t["view_ra"] - 133.7598) < 0.001  # propagated to J2026


def test_unknown_target_404():
    assert client.get("/api/targets/nope").status_code == 404


def test_bands():
    r = client.get("/api/bands").json()
    assert len(r["channels"]) == 102 and len(r["detectors"]) == 6


def test_job_validation():
    assert client.post("/api/jobs", json={"ra": 10, "dec": 10, "band": "D9"}).status_code == 422
    assert client.post("/api/jobs", json={"ra": 400, "dec": 10}).status_code == 422
    assert client.post("/api/jobs", json={"ra": 10, "dec": 10, "fov_arcsec": 99999}).status_code == 422


def test_unknown_job_and_frame():
    assert client.get("/api/jobs/does-not-exist").status_code == 404
    assert client.get("/api/frames/abc-1.bin").status_code == 404


def test_photometry_polls_are_not_rate_limited(monkeypatch):
    """The browser polls /spectrum every 2 s while a measurement runs; those polls must
    not count against the per-IP limit (a cold spectrum takes > 40 s = > 20 polls)."""
    from app.api.routes import photometry as ph

    key = ph._task_key(10.0, 20.0, 12.0, None, None)
    monkeypatch.setitem(ph._tasks, key, {"status": "running", "progress": 0.5, "stage": "measuring"})
    codes = {client.get("/api/spectrum", params={"ra": 10.0, "dec": 20.0}).status_code for _ in range(30)}
    assert codes == {202}
