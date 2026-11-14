"""Build frames for every featured target (so the first visitor gets them instantly)
and save an animated GIF preview for the targets gallery.

Talks to a running backend over HTTP (default http://localhost:8000).

Usage:
  python scripts/prewarm_cache.py                       # all targets
  python scripts/prewarm_cache.py --only barnards-star  # one target
  python scripts/prewarm_cache.py --gif-dir ../frontend/public/targets
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def job_body(t: dict) -> dict:
    v = t["recommended_view"]
    body = {
        "ra": t["view_ra"], "dec": t["view_dec"], "fov_arcsec": v.get("fov", 180), "band": v.get("band", "ALL"),
        "mode": v.get("mode", "epochs"), "window_days": v.get("window", 30), "diff": "none",
    }
    if t.get("pmra_masyr") is not None:
        body["pm"] = {"pmra": t["pmra_masyr"], "pmdec": t["pmdec_masyr"], "ref_epoch": t["ref_epoch"],
                      "ra": t["ra_deg"], "dec": t["dec_deg"]}
    return body


def run(base: str, t: dict, gif_dir: Path | None, timeout_s: int) -> dict:
    c = httpx.Client(base_url=base, timeout=120)
    t0 = time.time()
    r = c.post("/api/jobs", json=job_body(t))
    r.raise_for_status()
    job_id = r.json()["job_id"]
    while True:
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            break
        if time.time() - t0 > timeout_s:
            return {"slug": t["slug"], "status": "timeout"}
        time.sleep(3)
    out = {"slug": t["slug"], "status": j["status"], "frames": len(j["frames"]), "seconds": round(time.time() - t0, 1),
           "cached": j["info"].get("cached", False), "hash": j["request_hash"], "error": j.get("error")}
    if gif_dir and j["status"] == "done" and j["frames"]:
        diff = t["recommended_view"].get("diff", "none")
        g = c.get(f"/api/framesets/{j['request_hash']}/animation.gif",
                  params={"stretch": "asinh", "speed_ms": 600, "size": 320, "diff": diff})
        if g.status_code == 200:
            gif_dir.mkdir(parents=True, exist_ok=True)
            (gif_dir / f"{t['slug']}.gif").write_bytes(g.content)
            out["gif"] = str(gif_dir / f"{t['slug']}.gif")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--only", default=None)
    ap.add_argument("--gif-dir", default=str(ROOT.parent / "frontend" / "public" / "targets"))
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()
    targets = json.loads((ROOT / "app" / "data" / "targets.json").read_text(encoding="utf-8"))
    results = []
    for t in targets:
        if a.only and t["slug"] != a.only:
            continue
        print(f"-> {t['slug']} ...", flush=True)
        try:
            res = run(a.base, t, Path(a.gif_dir) if a.gif_dir else None, a.timeout)
        except Exception as exc:
            res = {"slug": t["slug"], "status": "error", "error": str(exc)}
        print("  ", res, flush=True)
        results.append(res)
    bad = [r for r in results if r["status"] != "done"]
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
