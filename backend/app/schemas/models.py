"""Request / response models. `frontend/lib/types.ts` mirrors these."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.services.wavelength import parse_band


class ProperMotion(BaseModel):
    pmra: float = Field(0.0, description="mas/yr, includes cos(dec)")
    pmdec: float = Field(0.0, description="mas/yr")
    ref_epoch: float = Field(2000.0, description="Julian year of the catalog position (ra, dec)")
    ra: float | None = Field(None, description="catalog RA at ref_epoch; defaults to the request ra")
    dec: float | None = Field(None, description="catalog Dec at ref_epoch; defaults to the request dec")


class JobRequest(BaseModel):
    ra: float = Field(..., ge=0, lt=360)
    dec: float = Field(..., ge=-90, le=90)
    fov_arcsec: float = Field(180.0, gt=0)
    band: str = "ALL"
    mode: Literal["epochs", "exposures", "stack"] = "epochs"
    diff: Literal["none", "first", "previous", "mean"] = "none"
    window_days: float = Field(30.0, gt=0, le=400)
    subtract_zodi: bool = True
    bad_flag_bits: list[int] | None = None
    track_pm: bool = False
    pm: ProperMotion | None = None
    releases: list[str] | None = None
    oversample: Literal[1, 2] = 1

    @field_validator("band")
    @classmethod
    def _valid_band(cls, v: str) -> str:
        parse_band(v)  # raises ValueError -> 422
        return v.strip()

    def normalized(self) -> dict[str, Any]:
        d = self.model_dump()
        d["ra"] = round(self.ra, 5)
        d["dec"] = round(self.dec, 5)
        d["fov_arcsec"] = round(self.fov_arcsec, 1)
        d["band"] = self.band.upper() if not self.band.upper().startswith("WL:") else self.band
        d["releases"] = sorted(r.lower() for r in self.releases) if self.releases else None
        d["bad_flag_bits"] = sorted(set(self.bad_flag_bits)) if self.bad_flag_bits is not None else None
        if self.pm is not None:
            d["pm"] = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in self.pm.model_dump().items()}
        return d


class JobCreated(BaseModel):
    job_id: str
    status: str
    request_hash: str


class FrameMeta(BaseModel):
    id: str
    idx: int
    t_start: float
    t_end: float
    t_mid: float
    date_mid: str
    n_exposures: int
    obs_ids: list[str]
    detectors: dict[str, int]
    releases: list[str]
    versions: list[str]
    lambda_um: float | None
    lambda_range: list[float] | None
    channels: list[dict[str, Any]]
    flag_summary: dict[str, int]
    stats: list[dict[str, float]]
    center: dict[str, float]
    target: dict[str, float] | None
    width: int
    height: int
    n_channels: int


class JobStatus(BaseModel):
    job_id: str
    request_hash: str
    status: str
    progress: float
    stage: str
    error: str | None = None
    frames: list[dict[str, Any]]
    info: dict[str, Any] = {}
