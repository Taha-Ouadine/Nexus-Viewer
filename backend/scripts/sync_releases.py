"""Discover SPHEREx collections at IRSA and update the release registry.

The registry is the Supabase `releases` table when Supabase is configured,
otherwise backend/app/data/releases.json.

  python scripts/sync_releases.py                 # report + register new collections (inactive)
  python scripts/sync_releases.py --auto          # register AND activate new releases
  python scripts/sync_releases.py --activate dr2  # switch one release on
  python scripts/sync_releases.py --deactivate qr3

New collections are grouped into releases by name: spherex_<id> and spherex_<id>_deep
form release <id>. `*_cube` collections (all-sky spectral cubes) are ignored because the
viewer works on Level-2 exposures. A changed release set or processing version changes
every cache key, so stale frames are never served.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.services.irsa import _votable  # noqa: E402

COLL_RE = re.compile(r"^spherex_([a-z]+\d+)(_deep)?$")


def list_collections() -> list[str]:
    """Irsa.list_collections(servicetype='SIA', filter='spherex') (fast, ~1 s in Phase 0);
    falls back to a TAP DISTINCT query on spherex.obscore (slow, but independent)."""
    try:
        from astroquery.ipac.irsa import Irsa

        t = Irsa.list_collections(servicetype="SIA", filter="spherex")
        return sorted(str(x) for x in t["collection"])
    except Exception as exc:
        print(f"astroquery listing failed ({exc}); trying TAP", file=sys.stderr)
        s = get_settings()
        adql = "SELECT DISTINCT obs_collection FROM spherex.obscore"
        r = httpx.post(s.irsa_tap_url.rstrip("/") + "/sync",
                       data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "votable", "QUERY": adql}, timeout=600)
        r.raise_for_status()
        return sorted(str(x) for x in _votable(r.content)["obs_collection"])


def load_registry() -> tuple[list[dict[str, Any]], Any]:
    from app.services.cache import SupabaseCache, get_cache

    cache = get_cache()
    if isinstance(cache, SupabaseCache):
        rows = cache.client.table("releases").select("*").execute().data or []
        return list(rows), cache.client
    path = get_settings().data_dir / "releases.json"
    return json.loads(path.read_text(encoding="utf-8")), None


def save_registry(rows: list[dict[str, Any]], client: Any) -> None:
    if client is not None:
        client.table("releases").upsert(rows).execute()
        return
    path = get_settings().data_dir / "releases.json"
    path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto", action="store_true", help="activate newly discovered releases")
    ap.add_argument("--activate", default=None)
    ap.add_argument("--deactivate", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    rows, client = load_registry()
    by_id = {r["id"]: r for r in rows}
    now = datetime.now(UTC).isoformat()

    if a.activate or a.deactivate:
        rid = a.activate or a.deactivate
        if rid not in by_id:
            sys.exit(f"unknown release '{rid}'. Known: {', '.join(by_id)}")
        by_id[rid]["is_active"] = bool(a.activate)
        print(f"{rid}: is_active = {by_id[rid]['is_active']}")
    else:
        colls = list_collections()
        print("IRSA SPHEREx collections:", ", ".join(colls))
        found: dict[str, list[str]] = {}
        for c in colls:
            m = COLL_RE.match(c)
            if m:
                found.setdefault(m.group(1), []).append(c)
        top = max((r.get("priority", 0) for r in rows), default=0)
        for rid, cs in sorted(found.items()):
            if rid in by_id:
                known = set(by_id[rid]["sia_collections"])
                if set(cs) - known:
                    by_id[rid]["sia_collections"] = sorted(known | set(cs))
                    print(f"{rid}: added collections {sorted(set(cs) - known)}")
                by_id[rid]["last_synced_at"] = now
                continue
            kind = "Data Release" if rid.startswith("dr") else "Quick Release" if rid.startswith("qr") else "Release"
            num = re.sub(r"\D", "", rid)
            new = {
                "id": rid, "label": f"{kind} {num}", "sia_collections": sorted(cs), "tap_release_filter": f"spherex_{rid}",
                "s3_prefix": f"{rid}/",
                # same calibration layout as the existing releases; check with `aws s3 ls --no-sign-request`
                "sapm_path_template": f"{rid}/solid_angle_pixel_map/cal-sapm-v3-2026-191/{{k}}/solid_angle_pixel_map_D{{k}}_spx_cal-sapm-v3-2026-191.fits",
                "doi": None, "priority": top + 10, "is_active": bool(a.auto), "released_at": now[:10],
                "last_synced_at": now, "notes": "Discovered by sync_releases.py — please review.",
            }
            by_id[rid] = new
            top += 10
            print(f"NEW release {rid} ({', '.join(cs)}) -> is_active={new['is_active']}")
        for rid, r in by_id.items():
            if rid not in found and r.get("is_active"):
                print(f"warning: active release {rid} no longer listed at IRSA (retired?)")

    out = sorted(by_id.values(), key=lambda r: -r.get("priority", 0))
    if a.dry_run:
        print(json.dumps(out, indent=2))
    else:
        save_registry(out, client)
        print("registry saved")


if __name__ == "__main__":
    main()
