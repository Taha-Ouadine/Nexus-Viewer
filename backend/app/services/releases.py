"""Release registry. Processing code never names a release: it asks this module
which releases are active and builds its queries from the rows it gets back.

Source of truth:
  * Supabase `releases` table when Supabase is configured, otherwise
  * `app/data/releases.json` (edited by `scripts/sync_releases.py`).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel

from app.core.config import get_settings

log = logging.getLogger(__name__)


class Release(BaseModel):
    id: str
    label: str
    sia_collections: list[str]
    tap_release_filter: str | None = None
    s3_prefix: str | None = None
    sapm_path_template: str | None = None
    doi: str | None = None
    priority: int = 0
    is_active: bool = True
    released_at: str | None = None
    last_synced_at: str | None = None
    notes: str | None = None


def _load_json() -> list[Release]:
    path = get_settings().data_dir / "releases.json"
    return [Release(**r) for r in json.loads(path.read_text(encoding="utf-8"))]


def _load_supabase() -> list[Release] | None:
    from app.services.cache import SupabaseCache, get_cache

    cache = get_cache()
    if not isinstance(cache, SupabaseCache):
        return None
    try:
        res = cache.client.table("releases").select("*").execute()
        rows: list[dict[str, Any]] = res.data or []
        return [Release(**{k: v for k, v in r.items() if k in Release.model_fields}) for r in rows] or None
    except Exception as exc:
        log.warning("could not read releases from Supabase (%s); using releases.json", exc)
        return None


def all_releases() -> list[Release]:
    rows = _load_supabase() or _load_json()
    return sorted(rows, key=lambda r: -r.priority)


def active_releases(ids: list[str] | None = None) -> list[Release]:
    rels = [r for r in all_releases() if r.is_active]
    if ids:
        wanted = {i.lower() for i in ids}
        rels = [r for r in rels if r.id.lower() in wanted]
    return rels


def release_for_collection(collection: str, releases: list[Release]) -> Release | None:
    for r in releases:
        if collection in r.sia_collections:
            return r
    return None
