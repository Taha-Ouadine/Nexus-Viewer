"""Fast unit tests (no network)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from astropy.io import fits

from app.schemas.models import JobRequest
from app.services.coadd import bad_mask_value, coadd, difference, flag_summary, robust_stats
from app.services.cutouts import _parse_multipart, snap_half, window_half_px
from app.services.epochs import cluster_times, summarize_epochs
from app.services.fitsio import data_size, header_end, shift_crpix
from app.services.irsa import Exposure, _vkey, dedupe, release_versions
from app.services.releases import Release
from app.services.render import decode_frame, frame_bytes, stretch, zscale_limits
from app.services.resolver import MJD_J2000, propagate
from app.services.wavelength import nominal_channels, parse_band, parse_group
from app.workers.job_runner import cap_exposures, plan_frames, request_hash

# ---------------------------------------------------------------- epochs


def test_cluster_by_gap():
    t = [0, 1, 2, 100, 101, 250]
    assert cluster_times(t, 30) == [[0, 1, 2], [3, 4], [5]]


def test_cluster_unsorted_input_returns_time_order():
    t = [101, 0, 100, 2]
    assert cluster_times(t, 30) == [[1, 3], [2, 0]]


def test_cluster_splits_continuous_coverage():
    # deep-field-like: one exposure every 2 days for 200 days -> cut into 30-day bins
    t = [float(i * 2) for i in range(100)]
    groups = cluster_times(t, 30)
    assert len(groups) == 7
    assert all(max(t[i] for i in g) - min(t[i] for i in g) < 30 for g in groups)
    assert sorted(i for g in groups for i in g) == list(range(100))


def test_summarize_epochs_counts_detectors():
    eps = summarize_epochs([0, 1, 200], [0.1, 1.1, 200.1], [1, 6, 6], 30)
    assert eps[0]["per_detector"] == {"D1": 1, "D6": 1}
    assert eps[1]["n_exposures"] == 1


# ---------------------------------------------------------------- coadd / flags


def test_bad_mask_value():
    assert bad_mask_value([0, 2, 21]) == 1 | 4 | (1 << 21)


def test_inverse_variance_coadd():
    a = np.full((3, 3), 1.0)
    b = np.full((3, 3), 3.0)
    va = np.full((3, 3), 1.0)
    vb = np.full((3, 3), 3.0)  # b has 3x the variance -> 1/4 of the weight
    f = np.zeros((3, 3), np.int64)
    co = coadd([a, b], [va, vb], [f, f], bad_mask=0, level_background=False)
    assert np.allclose(co.image, (1 * 1 + 3 * (1 / 3)) / (1 + 1 / 3))
    assert np.allclose(co.variance, 1 / (1 + 1 / 3))
    assert (co.coverage == 2).all()


def test_flag_masking_excludes_bad_pixels_and_ors_flags():
    a = np.full((2, 2), 1.0)
    b = np.full((2, 2), 100.0)
    v = np.ones((2, 2))
    fa = np.zeros((2, 2), np.int64)
    fb = np.zeros((2, 2), np.int64)
    fb[0, 0] = 1 << 22  # GHOST on one pixel of b
    co = coadd([a, b], [v, v], [fa, fb], bad_mask=1 << 22, level_background=False)
    assert co.image[0, 0] == pytest.approx(1.0)
    assert co.image[1, 1] == pytest.approx(50.5)
    assert co.flags[0, 0] == 1 << 22


def test_fully_flagged_pixels_are_filled_for_display():
    a = np.array([[5.0, 1.0], [1.0, 1.0]])
    v = np.ones((2, 2))
    f = np.zeros((2, 2), np.int64)
    f[0, 0] = 1 << 1  # OVERFLOW in every exposure
    co = coadd([a, a], [v, v], [f, f], bad_mask=1 << 1, level_background=False)
    assert co.image[0, 0] == pytest.approx(5.0)
    assert co.coverage[0, 0] == 0
    co2 = coadd([a, a], [v, v], [f, f], bad_mask=1 << 1, level_background=False, fill_flagged=False)
    assert np.isnan(co2.image[0, 0])


def test_background_levelling():
    a = np.full((4, 4), 10.0)
    a[1, 1] = 20
    co = coadd([a], [np.ones((4, 4))], [np.zeros((4, 4), np.int64)], bad_mask=0)
    assert co.image[0, 0] == pytest.approx(0.0)
    assert co.image[1, 1] == pytest.approx(10.0)


def test_difference_modes():
    f = [np.full((2, 2), x) for x in (1.0, 3.0, 6.0)]
    assert [d[0, 0] for d in difference(f, "first")] == [0, 2, 5]
    assert [d[0, 0] for d in difference(f, "previous")] == [0, 2, 3]
    assert [d[0, 0] for d in difference(f, "mean")] == [1 - 4.5, 3 - 3.5, 6 - 2]
    with pytest.raises(ValueError):
        difference(f, "bogus")


def test_flag_summary_and_stats():
    flags = np.array([[1 << 22, 0], [(1 << 22) | (1 << 17), 0]], dtype=np.uint32)
    s = flag_summary(flags, {22: "GHOST", 17: "PERSIST", 0: "TRANSIENT"})
    assert s == {"GHOST": 2, "PERSIST": 1}
    st = robust_stats(np.array([np.nan, 1, 2, 3]))
    assert st["median"] == 2 and st["min"] == 1


# ---------------------------------------------------------------- stretch / render


def test_stretch_monotonic_and_bounded():
    x = np.linspace(-1, 2, 50)
    for kind in ("linear", "asinh", "log", "sqrt"):
        y = stretch(x, 0, 1, kind)
        assert y.min() >= 0 and y.max() <= 1
        assert np.all(np.diff(y) >= -1e-12)
    assert stretch(np.array([0.0]), 0, 1, "linear", invert=True)[0] == 1.0


def test_zscale_limits_reasonable():
    rng = np.random.default_rng(1)
    a = rng.normal(100, 5, (50, 50))
    lo, hi = zscale_limits(a)
    assert 80 < lo < 100 < hi < 120


def test_frame_bytes_roundtrip_and_orientation():
    a = np.arange(6, dtype=np.float32).reshape(2, 3)  # FITS: row 0 = south
    data = frame_bytes([a])
    (back,) = decode_frame(data, 3, 2, 1)
    assert np.array_equal(back, a[::-1])  # browser: row 0 = north


# ---------------------------------------------------------------- bands


def test_parse_band_variants():
    assert parse_band("ALL")[0].detectors == (1, 2, 3, 4, 5, 6)
    assert parse_band("d6")[0].detectors == (6,)
    assert parse_band("D5+D6")[0].detectors == (5, 6)
    rgb = parse_band("RGB:D2,D4,D5+D6")
    assert [g.label for g in rgb] == ["D2", "D4", "D5+D6"]
    wl = parse_group("WL:1.5-1.7")
    assert wl.detectors == (2, 3) and wl.lam_range == (1.5, 1.7)
    with pytest.raises(ValueError):
        parse_band("RGB:D1,D2")
    with pytest.raises(ValueError):
        parse_band("WL:6-7")


def test_102_channels():
    ch = nominal_channels()
    assert len(ch) == 102
    assert ch[0]["lambda_min"] == pytest.approx(0.75)
    assert ch[-1]["lambda_max"] == pytest.approx(5.0)


def test_job_request_rejects_bad_band():
    with pytest.raises(ValueError):
        JobRequest(ra=10, dec=10, band="D9")


# ---------------------------------------------------------------- proper motion


def test_propagate_barnard():
    ra, dec = 269.4520769586187, 4.69336496657667
    ra2, dec2 = propagate(ra, dec, -801.551, 10362.394, 2000.0, MJD_J2000 + 26 * 365.25)
    ddec = (dec2 - dec) * 3600
    dra = (ra2 - ra) * 3600 * math.cos(math.radians(dec))
    assert ddec == pytest.approx(10.362394 * 26, rel=1e-6)
    assert dra == pytest.approx(-0.801551 * 26, rel=1e-3)


def test_propagate_no_pm():
    assert propagate(10, 20, None, None, 2000, 60000) == (10, 20)


# ---------------------------------------------------------------- request hashing / planning


def _exp(t: float, det: int, rel: str = "dr1", obs: str | None = None, ver: str = "l2b-v27-2026-200") -> Exposure:
    return Exposure(obs or f"o{t}", det, rel, f"spherex_{rel}", f"u{t}{det}{rel}", None, t, t + 0.01, 1, 2, ver)


def test_request_hash_normalisation():
    a = JobRequest(ra=10.000001, dec=-5, band="d6", releases=["QR3", "dr1"])
    b = JobRequest(ra=10.000004, dec=-5, band="D6", releases=["dr1", "qr3"])
    assert request_hash(a, {"dr1": "x"}, [1]) == request_hash(b, {"dr1": "x"}, [1])
    assert request_hash(a, {"dr1": "x"}, [1]) != request_hash(a, {"dr1": "y"}, [1])  # new data -> new hash


def test_dedupe_prefers_priority():
    rels = [Release(id="dr1", label="", sia_collections=[], priority=20),
            Release(id="qr3", label="", sia_collections=[], priority=10)]
    e1 = _exp(1, 2, "qr3", obs="A")
    e2 = _exp(1, 2, "dr1", obs="A")
    out = dedupe([e1, e2, _exp(5, 2, "qr3", obs="B")], rels)
    assert len(out) == 2 and out[0].release == "dr1"


def test_version_ordering():
    assert _vkey("l2b-v27-2026-245") > _vkey("l2b_retry-v27-2026-207")
    exps = [_exp(1, 1, ver="l2b-v27-2026-245"), _exp(2, 1, ver="l2b_retry-v27-2026-207")]
    assert release_versions(exps) == {"dr1": "l2b-v27-2026-245"}


def test_plan_frames_modes():
    exps = [_exp(t, d) for t in (0, 1, 200) for d in (1, 6)]
    groups = parse_band("ALL")
    assert len(plan_frames(exps, groups, "epochs", 30)) == 2
    assert len(plan_frames(exps, groups, "exposures", 30)) == 6
    assert len(plan_frames(exps, groups, "stack", 30)) == 1
    rgb = plan_frames(exps, parse_band("RGB:D1,D3,D6"), "epochs", 30)
    assert rgb[0].groups[1] == []  # no D3 exposures


def test_cap_exposures_keeps_ends():
    exps = [_exp(t, 1) for t in range(1000)]
    capped = cap_exposures(exps, 100)
    assert len(capped) == 100 and capped[0].t_min == 0 and capped[-1].t_min == 999


# ---------------------------------------------------------------- low-level FITS / HTTP helpers


def test_header_end_and_data_size():
    h = fits.Header()
    h["XTENSION"] = "IMAGE"
    h["BITPIX"] = -32
    h["NAXIS"] = 2
    h["NAXIS1"] = 10
    h["NAXIS2"] = 3
    raw = h.tostring().encode()
    assert header_end(raw, 0) == len(raw)
    assert header_end(raw[:-2880], 0) is None if len(raw) > 2880 else True
    assert data_size(h) == 2880


def test_shift_crpix_all_wcs_keys():
    h = fits.Header()
    h["CRPIX1"], h["CRPIX2"], h["CRPIX1W"], h["CRPIX2A"] = 10.0, 20.0, 1.0, 1.0
    shift_crpix(h, 3, 5)
    assert (h["CRPIX1"], h["CRPIX2"], h["CRPIX1W"], h["CRPIX2A"]) == (7, 15, -2, -4)


def test_parse_multipart():
    body = (b"--XYZ\r\nContent-Type: application/fits\r\nContent-Range: bytes 10-13/100\r\n\r\nabcd\r\n"
            b"--XYZ\r\nContent-Type: application/fits\r\nContent-Range: bytes 50-51/100\r\n\r\nef\r\n--XYZ--\r\n")
    parts = _parse_multipart(body, "multipart/byteranges; boundary=XYZ")
    assert parts == {10: b"abcd", 50: b"ef"}


def test_window_size():
    half = window_half_px(180)
    assert half * 2 * 6.15 >= 180 * 1.2 * math.sqrt(2)
    assert snap_half(27) == 32


def test_fill_holes_only_enclosed():
    from app.services.coadd import fill_holes

    a = np.ones((7, 7), np.float32)
    a[2:5, 2:5] = np.nan       # 3x3 hole in the middle (saturated core)
    a[:, 6] = np.nan           # uncovered edge column
    a[3, 3] = np.nan
    out, filled = fill_holes(a)
    assert np.isfinite(out[2:5, 2:5]).all() and filled[3, 3]
    assert np.isnan(out[:, 6]).all()  # edges stay empty


def test_thin_exposures_keeps_every_detector():
    from app.services.irsa import thin_exposures

    exps = [_exp(t, d) for t in range(400) for d in (1, 2, 3, 4, 5, 6)]
    out = thin_exposures(exps, 600)
    counts = {d: sum(e.detector == d for e in out) for d in range(1, 7)}
    assert all(95 <= c <= 105 for c in counts.values()), counts
