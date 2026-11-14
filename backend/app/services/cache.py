"""Cache and job storage.

`CacheBackend` stores two kinds of things:
  * blobs   - binary files (cutouts, frame arrays, PNG/GIF/FITS exports), grouped in buckets
  * records - small JSON documents (observation lists, frame-set metadata, photometry,
              resolved names, catalog overlays), grouped in tables

`JobStore` tracks frame-building jobs.

Two implementations exist:
  * Local (default): files under `backend/.cache/` and jobs in memory.
  * Supabase: Storage buckets + Postgres tables; switched on automatically when
    SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are set.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app.core.config import Settings, get_settings

log = logging.getLogger(__name__)


def stable_hash(obj: Any, n: int = 40) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:n]


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()


class CacheBackend(Protocol):
    name: str

    def get_blob(self, bucket: str, path: str) -> bytes | None: ...
    def put_blob(self, bucket: str, path: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...
    def list_blobs(self, bucket: str, prefix: str) -> list[str]: ...
    def get_record(self, table: str, key: str, max_age_s: float | None = None) -> dict[str, Any] | None: ...
    def put_record(self, table: str, key: str, payload: dict[str, Any], columns: dict[str, Any] | None = None) -> None: ...


# ---------------------------------------------------------------------------
# Local filesystem implementation
# ---------------------------------------------------------------------------

class LocalCache:
    name = "local"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        (self.root / "blobs").mkdir(parents=True, exist_ok=True)
        (self.root / "records").mkdir(parents=True, exist_ok=True)

    def _blob_path(self, bucket: str, path: str) -> Path:
        # Validate the components instead of Path.resolve(), which proved unreliable on
        # Windows while other threads create the same folders.
        parts = [bucket, *path.replace("\\", "/").split("/")]
        if any(x in ("", ".", "..") or ":" in x for x in parts):
            raise ValueError(f"invalid blob path: {bucket}/{path}")
        return self.root.joinpath("blobs", *parts)

    def get_blob(self, bucket: str, path: str) -> bytes | None:
        p = self._blob_path(bucket, path)
        return p.read_bytes() if p.is_file() else None

    def put_blob(self, bucket: str, path: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        p = self._blob_path(bucket, path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + f".{uuid.uuid4().hex[:6]}.tmp")
        tmp.write_bytes(data)
        tmp.replace(p)

    def list_blobs(self, bucket: str, prefix: str) -> list[str]:
        p = self._blob_path(bucket, prefix)
        folder = p if p.is_dir() else p.parent
        if not folder.is_dir():
            return []
        base = self.root / "blobs" / bucket
        name_prefix = "" if p.is_dir() else p.name
        return sorted(
            str(f.relative_to(base)).replace("\\", "/")
            for f in folder.iterdir()
            if f.is_file() and f.name.startswith(name_prefix) and not f.name.endswith(".tmp")
        )

    def _record_path(self, table: str, key: str) -> Path:
        return self.root / "records" / table / f"{sha1(key)}.json"

    def get_record(self, table: str, key: str, max_age_s: float | None = None) -> dict[str, Any] | None:
        p = self._record_path(table, key)
        if not p.is_file():
            return None
        if max_age_s is not None and time.time() - p.stat().st_mtime > max_age_s:
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))["payload"]
        except Exception:
            return None

    def put_record(self, table: str, key: str, payload: dict[str, Any], columns: dict[str, Any] | None = None) -> None:
        p = self._record_path(table, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{uuid.uuid4().hex[:6]}.tmp")
        tmp.write_text(json.dumps({"key": key, "payload": payload, **(columns or {})}, default=str), encoding="utf-8")
        tmp.replace(p)


# ---------------------------------------------------------------------------
# Supabase implementation (Storage + Postgres)
# ---------------------------------------------------------------------------

# Primary-key column of each cache table (see supabase/migrations/0001_init.sql)
_KEY_COLUMN = {"frame_sets": "request_hash", "resolved_names": "name_norm"}


class SupabaseCache:
    name = "supabase"

    def __init__(self, settings: Settings) -> None:
        from supabase import create_client  # imported lazily: optional dependency at runtime

        assert settings.supabase_url and settings.supabase_service_role_key
        self.client = create_client(settings.supabase_url, settings.supabase_service_role_key)
        self.local = LocalCache(settings.cache_dir)  # hot local copy to avoid re-downloading

    def get_blob(self, bucket: str, path: str) -> bytes | None:
        data = self.local.get_blob(bucket, path)
        if data is not None:
            return data
        try:
            data = self.client.storage.from_(bucket).download(path)
        except Exception:
            return None
        if data:
            self.local.put_blob(bucket, path, data)
        return data

    def put_blob(self, bucket: str, path: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.local.put_blob(bucket, path, data, content_type)
        try:
            self.client.storage.from_(bucket).upload(
                path, data, {"content-type": content_type, "upsert": "true"}
            )
        except Exception as exc:
            log.warning("supabase upload %s/%s failed: %s", bucket, path, exc)

    def list_blobs(self, bucket: str, prefix: str) -> list[str]:
        local = self.local.list_blobs(bucket, prefix)
        if local:
            return local
        folder, _, name_prefix = prefix.rpartition("/")
        try:
            items = self.client.storage.from_(bucket).list(folder)
        except Exception:
            return []
        return sorted(
            f"{folder}/{it['name']}" if folder else it["name"]
            for it in items if it.get("name", "").startswith(name_prefix)
        )

    def get_record(self, table: str, key: str, max_age_s: float | None = None) -> dict[str, Any] | None:
        col = _KEY_COLUMN.get(table, "key")
        try:
            res = self.client.table(table).select("payload,created_at").eq(col, key).limit(1).execute()
        except Exception as exc:
            log.warning("supabase select %s failed: %s", table, exc)
            return None
        if not res.data:
            return None
        row = res.data[0]
        if max_age_s is not None and row.get("created_at"):
            created = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
            if (datetime.now(UTC) - created).total_seconds() > max_age_s:
                return None
        payload = row.get("payload")
        return payload if isinstance(payload, dict) else None

    def put_record(self, table: str, key: str, payload: dict[str, Any], columns: dict[str, Any] | None = None) -> None:
        col = _KEY_COLUMN.get(table, "key")
        row = {col: key, "payload": payload, "created_at": datetime.now(UTC).isoformat(), **(columns or {})}
        try:
            self.client.table(table).upsert(json.loads(json.dumps(row, default=str))).execute()
        except Exception as exc:
            log.warning("supabase upsert %s failed: %s", table, exc)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@dataclass
class Job:
    id: str
    request_hash: str
    status: str = "queued"          # queued | running | done | failed
    progress: float = 0.0
    stage: str = "queued"
    error: str | None = None
    frames: list[dict[str, Any]] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d["job_id"] = d.pop("id")
        return d


class InMemoryJobStore:
    """Jobs live in this process. The frontend polls GET /api/jobs/{id}."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, request_hash: str) -> Job:
        job = Job(id=str(uuid.uuid4()), request_hash=request_hash)
        with self._lock:
            self._jobs[job.id] = job
            # keep memory bounded
            if len(self._jobs) > 500:
                for jid in sorted(self._jobs, key=lambda k: self._jobs[k].updated_at)[:100]:
                    self._jobs.pop(jid, None)
        self._persist(job)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def find_active(self, request_hash: str) -> Job | None:
        for j in self._jobs.values():
            if j.request_hash == request_hash and j.status in ("queued", "running"):
                return j
        return None

    def update(self, job: Job, **fields: Any) -> None:
        with self._lock:
            for k, v in fields.items():
                setattr(job, k, v)
            job.updated_at = time.time()
        self._persist(job)

    def _persist(self, job: Job) -> None:  # overridden by the Supabase store
        pass


class SupabaseJobStore(InMemoryJobStore):
    """Same as in-memory, but mirrors status/progress into the `jobs` table so a
    browser with the anon key can follow progress through Supabase Realtime."""

    def __init__(self, client: Any) -> None:
        super().__init__()
        self.client = client

    def _persist(self, job: Job) -> None:
        try:
            self.client.table("jobs").upsert({
                "id": job.id, "request_hash": job.request_hash, "status": job.status,
                "progress": job.progress, "stage": job.stage, "error": job.error,
                "updated_at": datetime.now(UTC).isoformat(),
            }).execute()
        except Exception as exc:
            log.debug("supabase job upsert failed: %s", exc)


_cache: CacheBackend | None = None
_jobs: InMemoryJobStore | None = None


def get_cache() -> CacheBackend:
    global _cache
    if _cache is None:
        s = get_settings()
        if s.supabase_enabled:
            try:
                _cache = SupabaseCache(s)
                log.info("Cache backend: Supabase (%s)", s.supabase_url)
            except Exception as exc:
                log.error("Supabase init failed (%s); falling back to local cache", exc)
                _cache = LocalCache(s.cache_dir)
        else:
            _cache = LocalCache(s.cache_dir)
            log.info("Cache backend: local filesystem (%s)", s.cache_dir)
    return _cache


def get_job_store() -> InMemoryJobStore:
    global _jobs
    if _jobs is None:
        cache = get_cache()
        _jobs = SupabaseJobStore(cache.client) if isinstance(cache, SupabaseCache) else InMemoryJobStore()
    return _jobs
