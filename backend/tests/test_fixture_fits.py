"""Tests against a small real SPHEREx cutout (WISE 0855, detector D6, DR1).

tests/fixtures/wise0855_D6_cutout.fits was produced by the IRSA cutout service and
stripped of its 3.8 MB EPSF table to keep the repository small."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.services.alignment import align, make_grid
from app.services.cache import LocalCache
from app.services.fitsio import Cutout, parse_cutout_fits
from app.services.photometry import measure

FIX = Path(__file__).parent / "fixtures" / "wise0855_D6_cutout.fits"
RA, DEC = 133.75976, -7.24219  # WISE 0855 at ~J2026


@pytest.fixture(scope="module")
def cut() -> Cutout:
    return parse_cutout_fits(FIX.read_bytes())


def test_parse_extensions(cut: Cutout):
    assert cut.image.dtype == np.float32
    assert cut.image.shape == cut.flags.shape == cut.variance.shape
    assert cut.zodi is not None and cut.wave_hdu_bytes is not None
    assert cut.header["BUNIT"].replace(" ", "") == "MJy/sr"
    assert cut.flag_names[21] == "SOURCE" and cut.flag_names[22] == "GHOST"
    assert cut.x0 > 0 and cut.y0 > 0  # origin recovered from the 'A' WCS


def test_pixel_scale(cut: Cutout):
    from astropy.wcs.utils import proj_plane_pixel_scales

    s = proj_plane_pixel_scales(cut.celestial_wcs()) * 3600
    assert np.allclose(s, 6.15, atol=0.05)


def test_wavelength_in_d6_range(cut: Cutout):
    x, y = cut.celestial_wcs().world_to_pixel_values(RA, DEC)
    lam, bw = cut.wavelength_at(float(x), float(y))
    assert 4.42 <= lam <= 5.01
    assert 0.01 < bw < 0.1


def test_serialization_roundtrip(cut: Cutout, tmp_path: Path):
    c2 = Cutout.from_bytes(cut.to_bytes())
    assert np.array_equal(np.nan_to_num(c2.image), np.nan_to_num(cut.image))
    assert np.array_equal(c2.flags, cut.flags)
    assert c2.wavelength_at(3, 3) == cut.wavelength_at(3, 3)
    cache = LocalCache(tmp_path)
    cache.put_blob("cutouts", "a/b.npz", cut.to_bytes())
    assert cache.list_blobs("cutouts", "a/b") == ["a/b.npz"]


def test_crop_keeps_wcs(cut: Cutout):
    sub = cut.crop(2, 3, 8, 9)
    w1, w2 = cut.celestial_wcs(), sub.celestial_wcs()
    assert np.allclose(w1.pixel_to_world_values(5, 6), w2.pixel_to_world_values(3, 3))


def test_alignment_north_up(cut: Cutout):
    grid = make_grid(RA, DEC, 60, 6.15)
    a = align(cut, grid)
    assert a.image.shape == (grid.npix, grid.npix)
    assert a.coverage > 0.5
    assert a.lambda_um is not None and 4.4 < a.lambda_um < 5.1
    # the brown dwarf is the brightest thing near the centre of this D6 cutout
    c = grid.npix // 2
    core = np.nanmax(a.image[c - 1:c + 2, c - 1:c + 2])
    assert core > np.nanmedian(a.image) + 5 * np.nanstd(a.image[np.isfinite(a.image)]) * 0.2


def test_photometry_positive_for_wise0855(cut: Cutout):
    m = measure(cut, RA, DEC, r_ap_px=1.5, sapm=None, bad_mask=0)
    assert m is not None
    assert m["flux_uJy"] > 0
    assert m["err_uJy"] > 0
