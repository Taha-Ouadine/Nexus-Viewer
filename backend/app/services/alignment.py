"""Putting every cutout on the same pixel grid (north up, east left)."""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass

import numpy as np
from astropy.wcs import WCS
from reproject import reproject_interp

from app.services.fitsio import Cutout


@dataclass
class Grid:
    ra: float
    dec: float
    npix: int
    scale_arcsec: float

    def wcs(self) -> WCS:
        w = WCS(naxis=2)
        w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        w.wcs.crval = [self.ra, self.dec]
        c = (self.npix + 1) / 2.0  # FITS 1-based centre pixel
        w.wcs.crpix = [c, c]
        w.wcs.cdelt = [-self.scale_arcsec / 3600.0, self.scale_arcsec / 3600.0]
        w.wcs.cunit = ["deg", "deg"]
        return w

    def as_dict(self) -> dict[str, object]:
        """Minimal TAN description for the browser. Pixel (col, row) in the frame binary
        has row 0 at the TOP (north); FITS y = npix - 1 - row."""
        c = (self.npix + 1) / 2.0
        return {
            "ctype": ["RA---TAN", "DEC--TAN"], "crval": [self.ra, self.dec],
            "crpix": [c, c], "cdelt": [-self.scale_arcsec / 3600.0, self.scale_arcsec / 3600.0],
            "npix": self.npix, "scale_arcsec": self.scale_arcsec, "row0": "north",
        }


def make_grid(ra: float, dec: float, fov_arcsec: float, scale_arcsec: float) -> Grid:
    n = int(math.ceil(fov_arcsec / scale_arcsec))
    if n % 2 == 0:
        n += 1  # odd so the target sits on the centre of a pixel
    return Grid(ra, dec, max(n, 5), scale_arcsec)


@dataclass
class Aligned:
    image: np.ndarray      # float64, NaN where no data
    variance: np.ndarray
    flags: np.ndarray      # int64
    coverage: float        # fraction of grid pixels with data
    lambda_um: float | None


def align(cut: Cutout, grid: Grid, subtract_zodi: bool = True) -> Aligned:
    shape = (grid.npix, grid.npix)
    w_out = grid.wcs()
    w_in = cut.celestial_wcs()
    img = cut.image.astype(np.float64)
    if subtract_zodi and cut.zodi is not None:
        img = img - cut.zodi
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        a, fp = reproject_interp((img, w_in), w_out, shape_out=shape, order="bilinear")
        v, _ = reproject_interp((cut.variance.astype(np.float64), w_in), w_out, shape_out=shape, order="bilinear")
        f, ffp = reproject_interp((cut.flags.astype(np.float64), w_in), w_out, shape_out=shape, order="nearest-neighbor")
    a[fp <= 0] = np.nan
    v[fp <= 0] = np.nan
    flags = np.where(np.isfinite(f) & (ffp > 0), f, 0).astype(np.int64)
    coverage = float(np.mean(fp > 0))
    # wavelength of this exposure at the grid centre
    lam = None
    try:
        x, y = w_in.world_to_pixel_values(grid.ra, grid.dec)
        wl = cut.wavelength_at(float(x), float(y))
        lam = wl[0] if wl else None
    except Exception:
        pass
    return Aligned(a, v, flags, coverage, lam)
