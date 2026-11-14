"""Application settings. Every value can be overridden with an environment variable
(or a `backend/.env` file). Nothing in the processing code hardcodes URLs or release names."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Default "bad" pixel mask: every documented FLAGS bit except
# 2 (SUR_ERROR), 12 (FULLSAMPLE, informational) and 21 (SOURCE, informational).
DEFAULT_BAD_FLAG_BITS = [0, 1, 6, 7, 9, 10, 11, 14, 15, 17, 19, 20, 22, 23, 24, 25, 26, 27, 28]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # --- Supabase (optional; when both are set the Supabase cache backend is used) ---
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    cache_bucket: str = "frames"
    cutout_bucket: str = "cutouts"

    # --- HTTP / CORS ---
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- IRSA endpoints ---
    irsa_tap_url: str = "https://irsa.ipac.caltech.edu/TAP"
    irsa_sia_url: str = "https://irsa.ipac.caltech.edu/SIA"
    irsa_ibe_base: str = "https://irsa.ipac.caltech.edu/ibe/data/spherex/"
    s3_https_base: str = "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/"
    sesame_url: str = "https://cds.unistra.fr/cgi-bin/nph-sesame"
    sesame_mirrors: str = "https://vizier.cfa.harvard.edu/viz-bin/nph-sesame"
    gaia_tap_url: str = "https://gea.esac.esa.int/tap-server/tap"

    # How pixels are fetched:
    #  "range"  - HTTP byte-range reads of only the needed rows (fast, small; default)
    #  "cutout" - IRSA IBE cutout service (always ships the ~4 MB PSF table per exposure)
    fetch_strategy: str = "range"
    # Where range reads go first: "s3" (AWS open-data bucket) or "irsa" (IBE). The other is a fallback.
    range_source: str = "s3"
    # Read narrow windows from IRSA with multi-range requests (only the needed columns).
    use_multirange: bool = True

    # --- Limits ---
    max_fov_arcsec: float = 1800.0
    default_fov_arcsec: float = 180.0
    max_parallel_cutouts: int = 8      # IRSA, Gaia, CDS: be polite
    max_parallel_s3: int = 16          # AWS open-data bucket (header reads)
    cutout_timeout_s: float = 120.0
    max_exposures_per_job: int = 600
    max_photometry_exposures: int = 600
    epoch_gap_days: float = 30.0
    bad_flag_bits: list[int] = Field(default_factory=lambda: list(DEFAULT_BAD_FLAG_BITS))
    pixel_scale_arcsec: float = 6.15

    # --- Cache ---
    cache_dir: Path = BACKEND_ROOT / ".cache"
    cache_ttl_days: int = 30

    # --- Rate limiting (per client IP) ---
    rate_limit_jobs: str = "30/minute"
    rate_limit_photometry: str = "20/minute"

    # --- Data files ---
    data_dir: Path = BACKEND_ROOT / "app" / "data"

    log_level: str = "INFO"

    @field_validator("bad_flag_bits", mode="before")
    @classmethod
    def _parse_bits(cls, v: object) -> object:
        if isinstance(v, str):
            return [int(x) for x in v.replace(" ", "").split(",") if x]
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
