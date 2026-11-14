"""Combining several aligned exposures into one image."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


def bad_mask_value(bits: Sequence[int]) -> int:
    m = 0
    for b in bits:
        m |= 1 << int(b)
    return m


@dataclass
class Coadd:
    image: np.ndarray      # float32
    variance: np.ndarray   # float32
    coverage: np.ndarray   # int16: number of exposures contributing per pixel
    flags: np.ndarray      # uint32: OR of flags of all contributing exposures


def coadd(
    images: Sequence[np.ndarray], variances: Sequence[np.ndarray], flags: Sequence[np.ndarray],
    bad_mask: int, level_background: bool = True, fill_flagged: bool = True,
) -> Coadd:
    """Inverse-variance weighted mean. Pixels with any `bad_mask` bit set (or no data)
    are ignored. If `level_background`, each exposure's median is subtracted first so
    different detectors/epochs share the same zero level. With `fill_flagged`, pixels that
    are flagged in EVERY exposure (typically saturated cores of bright stars) are filled
    with the plain mean of their flagged values instead of being left empty; their flags
    remain visible in the OR-ed flag mask."""
    if not images:
        raise ValueError("nothing to coadd")
    shape = images[0].shape
    num = np.zeros(shape)
    den = np.zeros(shape)
    cov = np.zeros(shape, np.int16)
    orf = np.zeros(shape, np.int64)
    eq_num = np.zeros(shape)
    any_num = np.zeros(shape)   # fallback: finite but flagged values (e.g. saturated star cores)
    any_cnt = np.zeros(shape, np.int16)
    for img, var, flg in zip(images, variances, flags):
        finite = np.isfinite(img)
        good = finite & ((flg & bad_mask) == 0)
        if not good.any():
            continue
        x = img
        if level_background:
            x = img - np.nanmedian(img[good])
        any_num += np.where(finite, np.nan_to_num(x), 0.0)
        any_cnt += finite.astype(np.int16)
        w = np.where(good & np.isfinite(var) & (var > 0), 1.0 / np.where(var > 0, var, 1.0), 0.0)
        num += np.where(w > 0, w * np.nan_to_num(x), 0.0)
        den += w
        eq_num += np.where(good, np.nan_to_num(x), 0.0)
        cov += good.astype(np.int16)
        orf |= np.where(np.isfinite(img), flg, 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(den > 0, num / den, np.where(cov > 0, eq_num / np.maximum(cov, 1), np.nan))
        if fill_flagged:
            mean = np.where(np.isnan(mean) & (any_cnt > 0), any_num / np.maximum(any_cnt, 1), mean)
        var_out = np.where(den > 0, 1.0 / den, np.nan)
    return Coadd(mean.astype(np.float32), var_out.astype(np.float32), cov, (orf & 0xFFFFFFFF).astype(np.uint32))


def fill_holes(a: np.ndarray, max_iter: int = 4, min_neighbours: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """Fill small enclosed NaN holes (typically saturated star cores that are NaN in
    every exposure) with the brightest neighbouring value, for DISPLAY only.
    Pixels at the straight edge of the covered area have < 5 valid neighbours and are
    left empty. Returns (filled image, boolean mask of filled pixels)."""
    out = a.astype(np.float32).copy()
    filled = np.zeros(a.shape, bool)
    h, w = a.shape
    for _ in range(max_iter):
        nan = ~np.isfinite(out)
        if not nan.any():
            break
        p = np.pad(out, 1, constant_values=np.nan)
        neigh = np.stack([p[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
                          for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx])
        ok = np.isfinite(neigh)
        cnt = ok.sum(axis=0)
        mx = np.where(ok, neigh, -np.inf).max(axis=0)
        fill = nan & (cnt >= min_neighbours)
        if not fill.any():
            break
        out[fill] = mx[fill]
        filled |= fill
    return out, filled


def difference(frames: list[np.ndarray], how: str) -> list[np.ndarray]:
    """'first': each minus the first; 'previous': each minus the one before
    (first frame minus itself = 0); 'mean': each minus the mean of all OTHER frames."""
    if how == "none" or not frames:
        return frames
    stack = np.stack(frames)
    if how == "first":
        return [f - stack[0] for f in frames]
    if how == "previous":
        return [frames[0] - frames[0]] + [frames[i] - frames[i - 1] for i in range(1, len(frames))]
    if how == "mean":
        out = []
        for i in range(len(frames)):
            others = np.delete(stack, i, axis=0)
            ref = np.nanmean(others, axis=0) if len(others) else np.zeros_like(frames[i])
            out.append(frames[i] - ref)
        return out
    raise ValueError(f"unknown diff mode {how}")


def robust_stats(a: np.ndarray) -> dict[str, float]:
    v = a[np.isfinite(a)]
    if v.size == 0:
        return {"p0_5": 0.0, "p99_5": 0.0, "median": 0.0, "mad": 0.0, "min": 0.0, "max": 0.0}
    p05, med, p995 = np.percentile(v, [0.5, 50, 99.5])
    return {
        "p0_5": float(p05), "p99_5": float(p995), "median": float(med),
        "mad": float(np.median(np.abs(v - med))), "min": float(v.min()), "max": float(v.max()),
    }


def flag_summary(flags: np.ndarray, names: dict[int, str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for bit, name in names.items():
        n = int(np.count_nonzero(flags & (1 << bit)))
        if n:
            out[name] = n
    return out
