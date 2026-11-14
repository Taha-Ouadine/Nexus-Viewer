"""Forced aperture photometry on every exposure that covers a position.

Because each SPHEREx detector sits behind a linear variable filter, every exposure
sees the star at a slightly different wavelength. Measuring the star in all
exposures therefore gives a spectrum "for free" (one point per exposure), and
the same points ordered by time give light curves.

Flux conversion: flux[µJy] = Σ_aperture  I[MJy/sr] × 23.5045 [µJy/arcsec² per MJy/sr] × Ω_pix[arcsec²]
where Ω_pix comes from the release's solid-angle pixel map (SAPM), read by byte
range just like the images; if it is unavailable the WCS pixel area is used.
"""

from __future__ import annotations

import asyncio
import logging
import math
import warnings
from typing import Any

import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from astropy.wcs.utils import proj_plane_pixel_area

from app.core.config import get_settings
from app.services.cache import get_cache, stable_hash
from app.services.coadd import bad_mask_value
from app.services.epochs import cluster_times
from app.services.fitsio import Cutout, data_size, header_end, numpy_dtype
from app.services.irsa import Exposure, find_exposures, release_versions, thin_exposures
from app.services.releases import Release, active_releases
from app.services.resolver import propagate

log = logging.getLogger(__name__)

# Pixels whose values are unusable: replaced by the local sky inside the aperture.
REPLACE_BITS = (6, 9, 10, 11)                       # NONFUNC, MISSING_DATA, HOT, COLD
# A measurement is "flagged" (greyed out) when its aperture touches any of these:
# saturation / nonlinearity / bloom, dead pixels, persistence, ghosts and streaks.
# TRANSIENT, OUTLIER, CROSSTALK, HALO, SNOWBALL and SOURCE are reported but do not grey it out
# (bright stars set HALO/TRANSIENT on their own pixels in almost every exposure).
SEVERE_BITS = (1, 6, 9, 10, 11, 15, 17, 22, 23, 24, 25, 26)
MJYSR_TO_UJY_PER_ARCSEC2 = 1e12 / 4.254517029615221e10  # 1 sr = 4.2545e10 arcsec^2 -> 23.5045
PHOT_HALF_PX = 8


class SapmReader:
    """Reads small windows of the per-detector solid-angle pixel maps (cached)."""

    def __init__(self) -> None:
        self._layout: dict[str, tuple[int, int, int, int]] = {}  # url -> (data_off, bitpix, nx, ny)
        self._lock = asyncio.Lock()

    async def window(self, fetcher: Any, rel: Release, det: int, x0: int, y0: int, x1: int, y1: int) -> np.ndarray | None:
        if not rel.sapm_path_template:
            return None
        key = rel.sapm_path_template.format(k=det)
        url = get_settings().s3_https_base + key
        cache = get_cache()
        path = f"sapm/{rel.id}/D{det}/{x0}_{y0}_{x1}_{y1}.npy"
        raw = await asyncio.to_thread(cache.get_blob, "cutouts", path)
        if raw:
            return np.frombuffer(raw, dtype="<f4").reshape(y1 - y0, x1 - x0)
        try:
            if url not in self._layout:
                head, _ = await fetcher._range(url, 0, 6 * 2880 - 1)
                e0 = header_end(head, 0)
                e1 = header_end(head, e0) if e0 else None
                if e0 is None or e1 is None:
                    return None
                h = fits.Header.fromstring(head[e0:e1].decode("ascii", "replace"))
                if data_size(h) == 0:
                    return None
                self._layout[url] = (e1, int(h["BITPIX"]), int(h["NAXIS1"]), int(h["NAXIS2"]))
            off, bitpix, nx, _ny = self._layout[url]
            bpp = abs(bitpix) // 8
            band, _ = await fetcher._range(url, off + y0 * nx * bpp, off + y1 * nx * bpp - 1)
            arr = np.frombuffer(band, dtype=numpy_dtype(bitpix)).reshape(y1 - y0, nx)[:, x0:x1].astype("<f4")
        except Exception as exc:
            log.info("SAPM read failed (%s); using WCS pixel area", exc)
            return None
        await asyncio.to_thread(cache.put_blob, "cutouts", path, arr.tobytes())
        return arr


_sapm = SapmReader()


def measure(cut: Cutout, ra: float, dec: float, r_ap_px: float, sapm: np.ndarray | None,
            bad_mask: int) -> dict[str, Any] | None:
    """Aperture sum with a local background annulus (r_ap+1 .. r_ap+4 px)."""
    from photutils.aperture import CircularAnnulus, CircularAperture, aperture_photometry

    w = cut.celestial_wcs()
    x, y = (float(v) for v in w.world_to_pixel_values(ra, dec))
    ny, nx = cut.image.shape
    r_out = r_ap_px + 4
    if not (r_ap_px <= x < nx - r_ap_px and r_ap_px <= y < ny - r_ap_px):
        return None
    img = cut.image.astype(np.float64)
    var = cut.variance.astype(np.float64)
    flags = cut.flags
    bad = ((flags & bad_mask_value(REPLACE_BITS)) != 0) | ~np.isfinite(img)

    if sapm is not None and sapm.shape == img.shape and np.isfinite(sapm).all():
        omega = sapm.astype(np.float64)
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            omega = np.full(img.shape, proj_plane_pixel_area(w) * 3600.0 ** 2)
    conv = MJYSR_TO_UJY_PER_ARCSEC2 * omega          # µJy per (MJy/sr) per pixel
    flux_img = img * conv
    var_img = var * conv ** 2

    ann = CircularAnnulus((x, y), r_in=r_ap_px + 1, r_out=r_out)
    ann_mask = ann.to_mask(method="center").to_image(img.shape)
    sky_vals = flux_img[(ann_mask > 0) & ~bad]
    if sky_vals.size < 5:
        return None
    _, sky_med, _ = sigma_clipped_stats(sky_vals, sigma=3.0)

    ap = CircularAperture((x, y), r=r_ap_px)
    ap_mask = ap.to_mask(method="exact").to_image(img.shape)
    in_ap = ap_mask > 0
    n_bad = int(np.count_nonzero(in_ap & bad))
    data = np.where(bad, sky_med, flux_img) - sky_med
    vdat = np.where(bad | ~np.isfinite(var_img), 0.0, var_img)
    phot = aperture_photometry(data, ap, error=np.sqrt(vdat))
    flux = float(phot["aperture_sum"][0])
    err = float(phot["aperture_sum_err"][0])
    flagged_bits = int(np.bitwise_or.reduce(flags[in_ap].ravel())) if in_ap.any() else 0
    names = [n for b, n in cut.flag_names.items() if flagged_bits & (1 << b)]
    wl = cut.wavelength_at(x, y)
    return {
        "flux_uJy": flux, "err_uJy": err,
        "lambda_um": wl[0] if wl else None, "bandwidth_um": wl[1] if wl else None,
        "flags": names, "n_bad_pixels": n_bad,
        "flagged": n_bad > 0 or bool(flagged_bits & bad_mask_value(SEVERE_BITS)),
        "saturated": bool(flagged_bits & ((1 << 1) | (1 << 15) | (1 << 26))),
        "x": x, "y": y,
    }


async def photometry_points(
    ra: float, dec: float, aperture_arcsec: float, releases: list[Release],
    pm: dict[str, float] | None, bands: list[int] | None = None, fetcher: Any = None,
    on_progress: Any = None,
) -> dict[str, Any]:
    from app.workers.job_runner import get_fetcher

    s = get_settings()
    fetcher = fetcher or get_fetcher()
    exposures = await asyncio.to_thread(find_exposures, ra, dec, releases)
    if bands:
        exposures = [e for e in exposures if e.detector in bands]
    n_found = len(exposures)
    exposures = thin_exposures(exposures, s.max_photometry_exposures)  # deep fields
    key = stable_hash({"v": 4, "ra": round(ra, 5), "dec": round(dec, 5), "ap": aperture_arcsec,
                       "rel": [r.id for r in releases], "ver": release_versions(exposures),
                       "pm": pm, "bands": bands})
    cache = get_cache()
    hit = await asyncio.to_thread(cache.get_record, "photometry_cache", key)
    if hit:
        return hit | {"cached": True}

    bad_mask = bad_mask_value(s.bad_flag_bits)
    r_ap = max(1.0, aperture_arcsec / s.pixel_scale_arcsec)
    half = max(PHOT_HALF_PX, int(math.ceil(r_ap + 6)))
    rel_by_id = {r.id: r for r in releases}

    def pos(e: Exposure) -> tuple[float, float]:
        if pm:
            return propagate(pm.get("ra", ra), pm.get("dec", dec), pm.get("pmra", 0.0), pm.get("pmdec", 0.0),
                             pm.get("ref_epoch", 2000.0), e.t_mid)
        return ra, dec

    positions = [pos(e) for e in exposures]
    errors: list[str] = []
    cuts = await fetcher.get_many(exposures, positions, half, on_progress, errors=errors)

    async def one(i: int) -> dict[str, Any] | None:
        c = cuts[i]
        if c is None:
            return None
        e = exposures[i]
        sap = await _sapm.window(fetcher, rel_by_id[e.release], e.detector, c.x0, c.y0,
                                 c.x0 + c.image.shape[1], c.y0 + c.image.shape[0])
        m = await asyncio.to_thread(measure, c, positions[i][0], positions[i][1], r_ap, sap, bad_mask)
        if m is None:
            return None
        return {**m, "t_mid": e.t_mid, "detector": e.detector, "obs_id": e.key, "release": e.release}

    pts = [p for p in await asyncio.gather(*(one(i) for i in range(len(exposures)))) if p is not None]
    pts.sort(key=lambda p: p["t_mid"])
    groups = cluster_times([p["t_mid"] for p in pts], s.epoch_gap_days)
    epochs = []
    for k, idx in enumerate(groups):
        for i in idx:
            pts[i]["epoch"] = k
        epochs.append({"index": k, "t_start": min(pts[i]["t_mid"] for i in idx),
                       "t_end": max(pts[i]["t_mid"] for i in idx), "n_points": len(idx)})
    result = {"ra": ra, "dec": dec, "aperture_arcsec": aperture_arcsec, "points": pts, "epochs": epochs,
              "n_exposures": len(exposures), "n_exposures_found": n_found, "pm_tracked": bool(pm)}
    result["n_fetch_errors"] = len(errors)
    if len(errors) <= 0.1 * max(len(exposures), 1):
        await asyncio.to_thread(cache.put_record, "photometry_cache", key, result, {"kind": "points"})
    return result


def bin_spectrum(points: list[dict[str, Any]], channels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Inverse-variance mean of unflagged points in each of the 102 nominal channels."""
    out = []
    for ch in channels:
        sel = [p for p in points if p.get("lambda_um") and not p["flagged"]
               and ch["lambda_min"] <= p["lambda_um"] < ch["lambda_max"] and p["err_uJy"] > 0]
        if not sel:
            continue
        w = np.array([1 / p["err_uJy"] ** 2 for p in sel])
        f = np.array([p["flux_uJy"] for p in sel])
        out.append({"channel": ch["channel"], "lambda_um": ch["lambda_center"],
                    "flux_uJy": float(np.sum(w * f) / np.sum(w)), "err_uJy": float(1 / np.sqrt(np.sum(w))),
                    "n": len(sel)})
    return out


def releases_for(ids: list[str] | None) -> list[Release]:
    return active_releases(ids)
