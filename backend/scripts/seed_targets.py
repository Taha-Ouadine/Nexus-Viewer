"""Resolve the featured targets with CDS Sesame and write app/data/targets.json
(and, with --supabase, upsert them into the Supabase `targets` table).

The position shown by default ("view_ra/view_dec") is the catalog position moved
to J2026.0 with the proper motion, because fast stars have moved up to ~4.5
arcminutes since J2000 (Phase 0 finding).

Usage: python scripts/seed_targets.py [--supabase]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services.resolver import MJD_J2000, _sesame_xml, propagate  # noqa: E402

VIEW_EPOCH = 2026.0

TARGETS = [
    {"slug": "barnards-star", "name": "Barnard's Star", "query": "Barnard's star", "category": "high-pm-star",
     "description": "A small red dwarf only 6 light-years away. It has the largest proper motion of any star: about 10.4 arcseconds per year, so it visibly shifts between SPHEREx sky surveys.",
     "what_to_see": "The bright star at the centre creeps upward (north): about 0.85 pixel every six months, roughly 2 pixels between the first and last survey. Zoom in and blink, and watch it move relative to the red crosshair's first position.",
     "recommended_view": {"band": "ALL", "fov": 180, "zoom": 6, "diff": "none"}},
    {"slug": "eps-indi-b", "name": "Epsilon Indi B (Ba/Bb)", "query": "eps Ind B", "category": "brown-dwarf",
     "description": "A pair of brown dwarfs orbiting each other, 12 light-years away, moving 4.7 arcseconds per year across the sky.",
     "what_to_see": "Subtle: the motion is about 0.4 pixel per six months (1.5 pixels over the 17 months of data). Try difference mode (each frame minus the first) and the D5/D6 bands where brown dwarfs are brightest.",
     "recommended_view": {"band": "D6", "fov": 180, "zoom": 8, "diff": "first"}},
    {"slug": "wise-0855", "name": "WISE 0855-0714", "query": "WISE J085510.83-071442.5", "category": "brown-dwarf",
     "description": "The coldest brown dwarf known (about -25 C), 7.4 light-years away. It is almost invisible in visible and near-infrared light and glows only at 4-5 micrometres.",
     "what_to_see": "Switch between D1 and D6: the object is absent at short wavelengths and obvious in D6. It drifts left (west) by about 0.7 pixel every six months.",
     "recommended_view": {"band": "D6", "fov": 180, "zoom": 6, "diff": "none"}},
    {"slug": "rw-aur", "name": "RW Aurigae", "query": "RW Aur", "category": "variable",
     "description": "A very young (T Tauri) star still surrounded by the disk it formed from. Its brightness changes irregularly as clumps of dust pass in front of it.",
     "what_to_see": "Compare the brightness of the central star between epochs, then click it to plot its light curve and spectrum.",
     "recommended_view": {"band": "D2", "fov": 180, "zoom": 4, "diff": "none"}},
    {"slug": "r-dra", "name": "R Draconis", "query": "R Dra", "category": "variable",
     "description": "A Mira-type pulsating red giant with a period of about 245 days. Its brightness changes by a large factor over a cycle.",
     "what_to_see": "Blink the D1 frames: the star changes brightness strongly between epochs. Click it to see the light curve and how the spectrum changes.",
     "recommended_view": {"band": "D1", "fov": 180, "zoom": 4, "diff": "none"}},
    # --- bonus targets ---
    {"slug": "luhman-16", "name": "Luhman 16 AB", "query": "Luhman 16", "category": "brown-dwarf",
     "description": "The closest brown dwarfs to the Sun (6.5 light-years), a bright binary moving 2.8 arcseconds per year.",
     "what_to_see": "A bright red source in the Brown dwarf hunter colour view; it drifts slowly between epochs.",
     "recommended_view": {"band": "RGB:D2,D4,D5+D6", "fov": 180, "zoom": 6, "diff": "none"}, "bonus": True},
    {"slug": "nep-deep-field", "name": "North Ecliptic Pole deep field", "ra": 270.0, "dec": 66.56,
     "category": "deep-field",
     "description": "SPHEREx looks at the ecliptic poles on almost every orbit, so this patch has hundreds of exposures and the finest time sampling.",
     "what_to_see": "Use 'All exposures' mode or a short window (1-7 days) to see the sky change on short timescales.",
     "recommended_view": {"band": "ALL", "fov": 300, "zoom": 3, "diff": "none", "window": 3}, "bonus": True},
    {"slug": "ecliptic-field", "name": "Ecliptic plane field (asteroids)", "ra": 30.0, "dec": 12.23,
     "category": "asteroid-field",
     "description": "A random patch on the ecliptic, the plane where most asteroids orbit. Asteroids move so fast that they appear in single exposures only.",
     "what_to_see": "Use 'All exposures' mode with D1 or ALL and look for dots that appear in only one frame.",
     "recommended_view": {"band": "ALL", "fov": 300, "zoom": 3, "diff": "mean", "mode": "exposures"}, "bonus": True},
]


def build() -> list[dict]:
    out = []
    view_mjd = MJD_J2000 + (VIEW_EPOCH - 2000.0) * 365.25
    for i, t in enumerate(TARGETS):
        rec = {k: v for k, v in t.items() if k not in ("query",)}
        if "query" in t:
            res = _sesame_xml(t["query"])
            if res is None:
                raise SystemExit(f"could not resolve {t['query']}")
            rec.update(ra_deg=res["ra"], dec_deg=res["dec"], pmra_masyr=res["pmra"], pmdec_masyr=res["pmdec"],
                       parallax_mas=res["parallax"], ref_epoch=2000.0, simbad_name=res["name"],
                       resolver=res["source"])
        else:
            rec.update(ra_deg=t["ra"], dec_deg=t["dec"], pmra_masyr=None, pmdec_masyr=None, parallax_mas=None,
                       ref_epoch=2000.0)
            rec.pop("ra")
            rec.pop("dec")
        vra, vdec = propagate(rec["ra_deg"], rec["dec_deg"], rec["pmra_masyr"], rec["pmdec_masyr"], 2000.0, view_mjd)
        rec.update(view_ra=round(vra, 6), view_dec=round(vdec, 6), view_epoch=VIEW_EPOCH,
                   is_featured=not t.get("bonus", False), sort_order=i, thumbnail_path=None)
        rec.pop("bonus", None)
        out.append(rec)
        print(f"{rec['slug']:16s} J2000 ({rec['ra_deg']:.5f}, {rec['dec_deg']:.5f})  view J{VIEW_EPOCH} ({vra:.5f}, {vdec:.5f})")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--supabase", action="store_true", help="also upsert into Supabase")
    a = ap.parse_args()
    rows = build()
    path = get_settings().data_dir / "targets.json"
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"wrote {path}")
    if a.supabase:
        from app.services.cache import SupabaseCache, get_cache

        cache = get_cache()
        if not isinstance(cache, SupabaseCache):
            raise SystemExit("Supabase is not configured (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)")
        cols = {"slug", "name", "ra_deg", "dec_deg", "ref_epoch", "pmra_masyr", "pmdec_masyr", "parallax_mas",
                "category", "description", "recommended_view", "thumbnail_path", "is_featured", "sort_order",
                "what_to_see", "view_ra", "view_dec"}
        cache.client.table("targets").upsert([{k: v for k, v in r.items() if k in cols} for r in rows],
                                             on_conflict="slug").execute()
        print("upserted into Supabase")


if __name__ == "__main__":
    main()
