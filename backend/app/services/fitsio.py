"""Parsing of SPHEREx Level-2 multi-extension FITS (MEF) data.

Two input forms are supported and produce the same `Cutout` object:
  * the bytes returned by the IRSA IBE cutout service (a small MEF), and
  * pieces read by HTTP byte ranges from the full 65 MB Level-2 file (see `cutouts.py`).

Extension names are matched case-insensitively and tolerate a numeric suffix
(e.g. `IMAGE1`), as documented by IRSA.
"""

from __future__ import annotations

import io
import logging
import re
import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning

log = logging.getLogger(__name__)

# astropy prints an INFO about SIP + the WAVE-TAB WCS on every wavelength lookup; silence it.
try:
    from astropy import log as _alog
    _alog.setLevel("WARNING")
except Exception:  # pragma: no cover
    pass

FITS_BLOCK = 2880

# Fallback flag-bit names (used when the FLAGS header has no MSKN* keywords).
DEFAULT_FLAG_NAMES: dict[int, str] = {
    0: "TRANSIENT", 1: "OVERFLOW", 2: "SUR_ERROR", 6: "NONFUNC", 7: "DICHROIC",
    9: "MISSING_DATA", 10: "HOT", 11: "COLD", 12: "FULLSAMPLE", 14: "PHANMISS",
    15: "NONLINEAR", 17: "PERSIST", 19: "OUTLIER", 20: "CROSSTALK", 21: "SOURCE",
    22: "GHOST", 23: "GHOST_FPA", 24: "GHOST_EXT", 25: "STREAK", 26: "BLOOM",
    27: "SNOWBALL", 28: "HALO",
}


@dataclass
class Cutout:
    """A small piece of one SPHEREx exposure around a sky position."""

    image: np.ndarray            # float32, MJy/sr
    flags: np.ndarray            # int64 bitmask (stored as int64 to keep uint32 semantics)
    variance: np.ndarray         # float32, (MJy/sr)^2
    zodi: np.ndarray | None      # float32, MJy/sr (model, NOT subtracted from image)
    header: fits.Header          # IMAGE header with CRPIX shifted to this cutout
    wave_hdu_bytes: bytes | None = None  # serialized WCS-WAVE table (for per-pixel wavelength)
    flag_names: dict[int, str] = field(default_factory=lambda: dict(DEFAULT_FLAG_NAMES))
    x0: int = 0                  # origin of the cutout in full-detector pixels (0-based)
    y0: int = 0

    # ---------- WCS helpers ----------
    def celestial_wcs(self) -> WCS:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FITSFixedWarning)
            return WCS(self.header).celestial

    def wavelength_at(self, x: float, y: float) -> tuple[float, float] | None:
        """Central wavelength and bandwidth (µm) at cutout pixel (x, y), 0-based."""
        if self.wave_hdu_bytes is None:
            return None
        try:
            with fits.open(io.BytesIO(self.wave_hdu_bytes)) as wh:
                hdul = fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(header=self.header.copy()), wh[1].copy()])
                hdul[2].header["EXTNAME"] = "WCS-WAVE"
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    w = WCS(self.header, fobj=hdul, key="W")
                    w.sip = None
                    wl, bw = w.wcs_pix2world([[x, y]], 0)[0]
            return float(wl), float(bw)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("wavelength lookup failed: %s", exc)
            return None

    # ---------- (de)serialization for the cache ----------
    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        arrays: dict[str, Any] = {
            "image": self.image.astype(np.float32),
            "flags": self.flags.astype(np.int64),
            "variance": self.variance.astype(np.float32),
            "header": np.frombuffer(self.header.tostring().encode("ascii"), dtype=np.uint8),
            "origin": np.array([self.x0, self.y0], dtype=np.int64),
            "flag_bits": np.array(list(self.flag_names.keys()), dtype=np.int64),
            "flag_names": np.array(list(self.flag_names.values())),
        }
        if self.zodi is not None:
            arrays["zodi"] = self.zodi.astype(np.float32)
        if self.wave_hdu_bytes is not None:
            arrays["wave"] = np.frombuffer(self.wave_hdu_bytes, dtype=np.uint8)
        np.savez_compressed(buf, **arrays)
        return buf.getvalue()

    @classmethod
    def from_bytes(cls, data: bytes) -> "Cutout":
        with np.load(io.BytesIO(data), allow_pickle=False) as z:
            header = fits.Header.fromstring(z["header"].tobytes().decode("ascii"))
            names = {int(b): str(n) for b, n in zip(z["flag_bits"], z["flag_names"])}
            return cls(
                image=z["image"], flags=z["flags"], variance=z["variance"],
                zodi=z["zodi"] if "zodi" in z.files else None,
                header=header,
                wave_hdu_bytes=z["wave"].tobytes() if "wave" in z.files else None,
                flag_names=names, x0=int(z["origin"][0]), y0=int(z["origin"][1]),
            )

    def crop(self, x0: int, y0: int, x1: int, y1: int) -> "Cutout":
        """Return a sub-cutout using cutout-local pixel bounds [x0, x1) x [y0, y1)."""
        hdr = self.header.copy()
        shift_crpix(hdr, x0, y0)
        sl = (slice(y0, y1), slice(x0, x1))
        return Cutout(
            image=self.image[sl], flags=self.flags[sl], variance=self.variance[sl],
            zodi=None if self.zodi is None else self.zodi[sl], header=hdr,
            wave_hdu_bytes=self.wave_hdu_bytes, flag_names=dict(self.flag_names),
            x0=self.x0 + x0, y0=self.y0 + y0,
        )


def shift_crpix(hdr: fits.Header, dx: int, dy: int) -> None:
    """Shift the reference pixel of every WCS (primary, 'A', 'W', ...) after slicing.
    SIP polynomials are expressed relative to CRPIX, so a pure shift is exact."""
    for key in list(hdr.keys()):
        m = re.fullmatch(r"CRPIX([12])([A-Z]?)", key)
        if m:
            hdr[key] = float(hdr[key]) - (dx if m.group(1) == "1" else dy)


_EXT_RE = re.compile(r"^([A-Z\-]+?)(\d*)$")


def _ext_base(name: str) -> str:
    m = _EXT_RE.match(name.strip().upper())
    return m.group(1) if m else name.strip().upper()


def find_ext(hdul: fits.HDUList, base: str) -> Any | None:
    base = base.upper()
    for hdu in hdul:
        name = str(hdu.header.get("EXTNAME", "")).strip().upper()
        if name == base or _ext_base(name) == base:
            return hdu
    return None


def flag_names_from_header(hdr: fits.Header | None) -> dict[int, str]:
    names = dict(DEFAULT_FLAG_NAMES)
    if hdr is None:
        return names
    for key in hdr.keys():
        m = re.fullmatch(r"MSKN(\d{4})", key)
        if m:
            names[int(m.group(1))] = str(hdr[key]).strip()
    return names


def _apply_scaling(hdu_or_hdr: fits.Header, arr: np.ndarray) -> np.ndarray:
    bscale = hdu_or_hdr.get("BSCALE", 1)
    bzero = hdu_or_hdr.get("BZERO", 0)
    if bscale != 1 or bzero != 0:
        return arr.astype(np.float64) * bscale + bzero
    return arr


def wave_hdu_to_bytes(hdu: fits.BinTableHDU) -> bytes:
    buf = io.BytesIO()
    fits.HDUList([fits.PrimaryHDU(), fits.BinTableHDU(data=hdu.data, header=hdu.header)]).writeto(buf)
    return buf.getvalue()


def parse_cutout_fits(data: bytes) -> Cutout:
    """Parse the MEF returned by the IBE cutout service."""
    with fits.open(io.BytesIO(data), memmap=False) as hdul:
        img = find_ext(hdul, "IMAGE")
        if img is None:
            raise ValueError("cutout has no IMAGE extension")
        flg = find_ext(hdul, "FLAGS")
        var = find_ext(hdul, "VARIANCE")
        zod = find_ext(hdul, "ZODI")
        wav = find_ext(hdul, "WCS-WAVE")
        image = np.asarray(img.data, dtype=np.float32)
        flags = (
            np.asarray(flg.data).astype(np.int64) & 0xFFFFFFFF if flg is not None
            else np.zeros(image.shape, np.int64)
        )
        variance = (
            np.asarray(var.data, dtype=np.float32) if var is not None
            else np.full(image.shape, np.nan, np.float32)
        )
        zodi = np.asarray(zod.data, dtype=np.float32) if zod is not None else None
        # The 'A' WCS records the cutout origin in full-detector pixels.
        x0 = int(round(1 - float(img.header.get("CRPIX1A", 1.0))))
        y0 = int(round(1 - float(img.header.get("CRPIX2A", 1.0))))
        return Cutout(
            image=image, flags=flags, variance=variance, zodi=zodi,
            header=img.header.copy(),
            wave_hdu_bytes=wave_hdu_to_bytes(wav) if wav is not None else None,
            flag_names=flag_names_from_header(flg.header if flg is not None else None),
            x0=x0, y0=y0,
        )


# ---------------------------------------------------------------------------
# Low-level helpers used by the byte-range reader
# ---------------------------------------------------------------------------

def header_end(buf: bytes, start: int) -> int | None:
    """Return the byte offset just after the header that begins at `start`
    (i.e. the start of its data), or None if `buf` does not contain the END card."""
    pos = start
    while pos + FITS_BLOCK <= len(buf):
        block = buf[pos:pos + FITS_BLOCK]
        for i in range(0, FITS_BLOCK, 80):
            if block[i:i + 8] == b"END     ":
                return pos + FITS_BLOCK
        pos += FITS_BLOCK
    return None


def data_size(hdr: fits.Header) -> int:
    """Size in bytes of the data unit, padded to whole FITS blocks."""
    naxis = int(hdr.get("NAXIS", 0))
    if naxis == 0:
        return 0
    n = abs(int(hdr["BITPIX"])) // 8
    for i in range(1, naxis + 1):
        n *= int(hdr[f"NAXIS{i}"])
    n = int(hdr.get("GCOUNT", 1)) * (int(hdr.get("PCOUNT", 0)) + n)
    return ((n + FITS_BLOCK - 1) // FITS_BLOCK) * FITS_BLOCK


def numpy_dtype(bitpix: int) -> str:
    return {8: "u1", 16: ">i2", 32: ">i4", 64: ">i8", -32: ">f4", -64: ">f8"}[bitpix]
