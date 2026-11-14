"""Wavelength helpers: detector ranges, the 102 nominal channels, band-group parsing."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

# Detector wavelength coverage (µm) and spectral resolving power R.
DETECTORS: dict[int, tuple[float, float, float]] = {
    1: (0.75, 1.09, 39), 2: (1.10, 1.62, 41), 3: (1.63, 2.41, 41),
    4: (2.42, 3.82, 35), 5: (3.83, 4.41, 112), 6: (4.42, 5.00, 128),
}
CHANNELS_PER_DETECTOR = 17


def nominal_channels() -> list[dict[str, float | int | str]]:
    """102 nominal channels: each detector range split into 17 log-spaced bins."""
    out: list[dict[str, float | int | str]] = []
    for det, (lo, hi, _r) in DETECTORS.items():
        edges = [lo * (hi / lo) ** (i / CHANNELS_PER_DETECTOR) for i in range(CHANNELS_PER_DETECTOR + 1)]
        for i in range(CHANNELS_PER_DETECTOR):
            out.append({
                "id": f"WL:{edges[i]:.3f}-{edges[i + 1]:.3f}", "detector": det,
                "channel": (det - 1) * CHANNELS_PER_DETECTOR + i + 1,
                "lambda_min": round(edges[i], 4), "lambda_max": round(edges[i + 1], 4),
                "lambda_center": round(math.sqrt(edges[i] * edges[i + 1]), 4),
            })
    return out


def detector_for_lambda(lam: float) -> int | None:
    for det, (lo, hi, _r) in DETECTORS.items():
        if lo <= lam <= hi:
            return det
    return None


@dataclass(frozen=True)
class BandGroup:
    """One group of exposures that gets coadded into one image channel."""
    label: str
    detectors: tuple[int, ...]            # detectors to consider
    lam_range: tuple[float, float] | None = None  # filter on wavelength at target pixel

    def accepts_detector(self, det: int) -> bool:
        return det in self.detectors


_WL_RE = re.compile(r"^WL:([0-9.]+)-([0-9.]+)$", re.I)


def parse_group(token: str) -> BandGroup:
    t = token.strip().upper()
    if t == "ALL":
        return BandGroup("ALL", tuple(DETECTORS))
    if re.fullmatch(r"D[1-6]", t):
        return BandGroup(t, (int(t[1]),))
    m = re.fullmatch(r"D([1-6])\+D?([1-6])", t)  # e.g. D5+D6
    if m:
        a, b = sorted((int(m.group(1)), int(m.group(2))))
        return BandGroup(t, tuple(range(a, b + 1)))
    m = _WL_RE.match(token.strip())
    if m:
        lo, hi = sorted((float(m.group(1)), float(m.group(2))))
        dets = tuple(d for d, (a, b, _r) in DETECTORS.items() if b >= lo and a <= hi)
        if not dets:
            raise ValueError(f"wavelength range {lo}-{hi} µm is outside SPHEREx coverage (0.75-5.0)")
        return BandGroup(f"WL:{lo:g}-{hi:g}", dets, (lo, hi))
    raise ValueError(f"unknown band '{token}'")


def parse_band(band: str) -> list[BandGroup]:
    """'ALL' | 'D1'..'D6' | 'D5+D6' | 'WL:a-b' | 'RGB:<b>,<g>,<r>' -> 1 or 3 groups."""
    b = band.strip()
    if b.upper().startswith("RGB:"):
        parts = [p for p in b[4:].split(",") if p.strip()]
        if len(parts) != 3:
            raise ValueError("RGB needs exactly three groups, e.g. RGB:D2,D4,D6")
        return [parse_group(p) for p in parts]
    return [parse_group(b)]


PRESETS = [
    {"id": "brown-dwarf", "label": "Brown dwarf hunter", "band": "RGB:D2,D4,D5+D6",
     "why": "Cold brown dwarfs are almost invisible below 2 µm but bright at 4-5 µm, so they look red; normal stars look white or blue."},
    {"id": "variable", "label": "Variable star", "band": "D1",
     "why": "Short wavelengths (0.75-1.1 µm) show the biggest brightness swings of pulsating stars like Miras."},
    {"id": "ices", "label": "Ices / molecules", "band": "RGB:D4,D5,D6",
     "why": "Water ice, CO2 and CO absorb between 2.5 and 5 µm; this colour mix highlights them."},
    {"id": "motion", "label": "Motion finder", "band": "ALL",
     "why": "Stacking every detector gives the cleanest picture, best for spotting things that move."},
]
