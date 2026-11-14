"""Regenerate supabase/seed.sql from app/data/releases.json and app/data/targets.json.

Usage: python scripts/make_seed_sql.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parent / "supabase" / "seed.sql"


def q(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "array[" + ",".join(q(x) for x in v) + "]::text[]"
    if isinstance(v, dict):
        return q(json.dumps(v)) + "::jsonb"
    return "'" + str(v).replace("'", "''") + "'"


def main() -> None:
    rel = json.loads((ROOT / "app/data/releases.json").read_text(encoding="utf-8"))
    tg = json.loads((ROOT / "app/data/targets.json").read_text(encoding="utf-8"))
    out = [
        f"-- Seed data generated from backend/app/data/releases.json and targets.json ({date.today()}).",
        "-- Regenerate with: python backend/scripts/make_seed_sql.py",
        "",
    ]
    cols = ["id", "label", "sia_collections", "tap_release_filter", "s3_prefix", "sapm_path_template", "doi",
            "priority", "is_active", "released_at", "notes"]
    for r in rel:
        out.append(f"insert into releases ({','.join(cols)}) values ({','.join(q(r.get(c)) for c in cols)}) "
                   "on conflict (id) do nothing;")
    out.append("")
    cols = ["slug", "name", "ra_deg", "dec_deg", "ref_epoch", "pmra_masyr", "pmdec_masyr", "parallax_mas", "view_ra",
            "view_dec", "category", "description", "what_to_see", "recommended_view", "is_featured", "sort_order"]
    for t in tg:
        out.append(f"insert into targets ({','.join(cols)}) values ({','.join(q(t.get(c)) for c in cols)}) "
                   "on conflict (slug) do nothing;")
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(rel)} releases, {len(tg)} targets)")


if __name__ == "__main__":
    main()
