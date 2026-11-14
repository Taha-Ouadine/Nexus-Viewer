"""Turning float frames into bytes for the browser (raw float32) and into PNG / GIF / FITS."""

from __future__ import annotations

import io
from collections.abc import Sequence
from typing import Any

import numpy as np
from PIL import Image


def to_display_rows(a: np.ndarray) -> np.ndarray:
    """FITS arrays have row 0 at the bottom (south). The browser wants row 0 at the top."""
    return np.ascontiguousarray(a[::-1])


def frame_bytes(channels: Sequence[np.ndarray]) -> bytes:
    """Row-major little-endian float32, channel after channel, row 0 = north. NaN = no data."""
    return b"".join(to_display_rows(c).astype("<f4").tobytes() for c in channels)


def flags_bytes(flags: np.ndarray) -> bytes:
    return to_display_rows(flags).astype("<u4").tobytes()


def decode_frame(data: bytes, width: int, height: int, channels: int) -> list[np.ndarray]:
    arr = np.frombuffer(data, dtype="<f4").reshape(channels, height, width)
    return [arr[i] for i in range(channels)]


# ----------------------------------------------------------------- stretch
def zscale_limits(a: np.ndarray, contrast: float = 0.25) -> tuple[float, float]:
    """Simplified IRAF zscale (fit a line to sorted sample)."""
    v = np.sort(a[np.isfinite(a)].ravel())
    if v.size < 5:
        return 0.0, 1.0
    if v.size > 2000:
        v = v[np.linspace(0, v.size - 1, 2000).astype(int)]
    n = v.size
    med = v[n // 2]
    x = np.arange(n)
    slope, _ = np.polyfit(x, v, 1)
    lo = med - (slope / contrast) * (n // 2)
    hi = med + (slope / contrast) * (n - n // 2)
    return float(max(lo, v[0])), float(min(hi, v[-1]))


def resolve_limit(spec: str | float | None, values: np.ndarray, default_pct: float) -> float:
    """'p99.5' -> percentile; number -> itself; None -> default percentile."""
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0
    if spec is None or spec == "":
        return float(np.percentile(finite, default_pct))
    if isinstance(spec, str) and spec.lower().startswith("p"):
        return float(np.percentile(finite, float(spec[1:])))
    return float(spec)


def stretch(a: np.ndarray, lo: float, hi: float, kind: str = "asinh", invert: bool = False) -> np.ndarray:
    """Map to 0..1. Mirrors frontend/lib/stretch.ts."""
    span = hi - lo if hi > lo else 1.0
    x = np.clip((np.nan_to_num(a, nan=lo) - lo) / span, 0.0, 1.0)
    if kind == "asinh":
        x = np.arcsinh(10 * x) / np.arcsinh(10)
    elif kind == "log":
        x = np.log10(1 + 1000 * x) / np.log10(1001)
    elif kind == "sqrt":
        x = np.sqrt(x)
    if invert:
        x = 1.0 - x
    return x


def to_uint8_image(channels: Sequence[np.ndarray], lo: Sequence[float], hi: Sequence[float],
                   kind: str, invert: bool, scale: int = 1) -> Image.Image:
    """Grey (1 channel) or RGB (3 channels: given in B, G, R order like the band string).
    Input arrays are in display orientation (row 0 = north), as stored in frame .bin files."""
    if len(channels) == 1:
        g = (stretch(channels[0], lo[0], hi[0], kind, invert) * 255).astype(np.uint8)
        img = Image.fromarray(g, mode="L")
    else:
        b, g, r = (
            (stretch(c, lo[i], hi[i], kind, invert) * 255).astype(np.uint8) for i, c in enumerate(channels[:3])
        )
        img = Image.fromarray(np.dstack([r, g, b]), mode="RGB")
    if scale > 1:
        img = img.resize((img.width * scale, img.height * scale), Image.Resampling.NEAREST)
    return img


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def gif_bytes(images: Sequence[Image.Image], duration_ms: int) -> bytes:
    buf = io.BytesIO()
    frames = [im.convert("P", palette=Image.Palette.ADAPTIVE) if im.mode == "RGB" else im for im in images]
    frames[0].save(buf, format="GIF", save_all=True, append_images=list(frames[1:]),
                   duration=max(20, duration_ms), loop=0, disposal=2)
    return buf.getvalue()


def fits_cube_bytes(frames: Sequence[Sequence[np.ndarray]], metas: Sequence[dict[str, Any]],
                    grid: dict[str, Any], request: dict[str, Any]) -> bytes:
    """`frames` are in display orientation; they are flipped back to FITS orientation here."""
    from astropy.io import fits
    from astropy.table import Table

    hdus: list[Any] = [fits.PrimaryHDU()]
    hdus[0].header["ORIGIN"] = "Nexus Viewer"
    hdus[0].header["BAND"] = str(request.get("band"))
    hdus[0].header["COMMENT"] = "SPHEREx data: IRSA, DOI 10.26131/IRSA678 (DR1), 10.26131/IRSA662 (QR3)"
    for meta, chans in zip(metas, frames):
        for ci, c in enumerate(chans):
            h = fits.Header()
            h["CTYPE1"], h["CTYPE2"] = grid["ctype"]
            h["CRVAL1"], h["CRVAL2"] = grid["crval"]
            h["CRPIX1"], h["CRPIX2"] = grid["crpix"]
            h["CDELT1"], h["CDELT2"] = grid["cdelt"]
            h["BUNIT"] = "MJy/sr"
            h["EXTNAME"] = f"FRAME{meta['idx']}" + (f"_C{ci}" if len(chans) > 1 else "")
            h["MJD-AVG"] = meta.get("t_mid")
            h["NEXP"] = meta.get("n_exposures")
            if meta.get("lambda_um"):
                h["LAMBDA"] = (meta["lambda_um"], "mean wavelength at centre [um]")
            hdus.append(fits.ImageHDU(np.ascontiguousarray(np.asarray(c, dtype=np.float32)[::-1]), header=h))
    t = Table(rows=[(m["idx"], m.get("t_mid"), m.get("n_exposures"), m.get("lambda_um") or np.nan)
                    for m in metas], names=("idx", "t_mid_mjd", "n_exposures", "lambda_um"))
    hdus.append(fits.BinTableHDU(t, name="FRAMES"))
    buf = io.BytesIO()
    fits.HDUList(hdus).writeto(buf)
    return buf.getvalue()
