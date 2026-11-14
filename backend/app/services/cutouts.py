"""Downloading small pieces of SPHEREx exposures, politely and with retries.

Phase 0 finding: the IRSA IBE cutout service always returns the 21x21-PSF table
(~3.8 MB) with every cutout, whatever the cutout size, and served ~1 MB/s in
aggregate with 8 workers. So the default strategy here is different:

  "range" strategy (default)
    1. Read the FITS headers of the full Level-2 file with HTTP Range requests
       (S3 open-data bucket first, IRSA IBE as fallback). Header layout is cached
       per file, so this happens once per exposure.
    2. Read only the rows of IMAGE / FLAGS / VARIANCE / ZODI that contain the
       requested window (~0.1-2 MB instead of ~4 MB), plus the tiny WCS-WAVE table.

  "cutout" strategy
    The IBE cutout service (`?center=ra,dec&size=deg`). Kept as an option.

Every request goes through a semaphore (MAX_PARALLEL_CUTOUTS, default 8) and is
retried with exponential backoff.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import warnings
from dataclasses import dataclass
from typing import Any

import httpx
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from app.core.config import Settings, get_settings
from app.services.cache import CacheBackend, get_cache, sha1
from app.services.fitsio import (
    Cutout,
    data_size,
    flag_names_from_header,
    header_end,
    numpy_dtype,
    parse_cutout_fits,
    shift_crpix,
    wave_hdu_to_bytes,
)
from app.services.irsa import Exposure

log = logging.getLogger(__name__)

NEEDED_EXTS = ("IMAGE", "FLAGS", "VARIANCE", "ZODI")
HEADER_CHUNK = 12 * 2880       # 34 kB: larger than a typical SPHEREx extension header (more is fetched if needed)
TAIL_CHUNK = 12 * 2880         # last 34 kB of the file hold the WCS-WAVE table
MAX_RANGES_PER_REQUEST = 100   # IRSA answers 200 (whole file) above 100 ranges (measured)


def _parse_multipart(body: bytes, content_type: str) -> dict[int, bytes]:
    """Split a multipart/byteranges body into {range_start: bytes}."""
    import re as _re

    m = _re.search(r'boundary="?([^";]+)"?', content_type)
    if not m:
        raise FetchError("multipart response without boundary")
    sep = b"--" + m.group(1).encode()
    out: dict[int, bytes] = {}
    for part in body.split(sep):
        if not part or part.startswith(b"--"):
            continue
        head, _, data = part.partition(b"\r\n\r\n")
        cr = _re.search(rb"[Cc]ontent-[Rr]ange:\s*bytes\s+(\d+)-(\d+)/", head)
        if not cr:
            continue
        a, b = int(cr.group(1)), int(cr.group(2))
        out[a] = data[: b - a + 1]
    return out


class FetchError(Exception):
    pass


@dataclass
class Layout:
    """Where each extension lives inside a full Level-2 file."""
    size: int
    header: str                     # IMAGE header (full detector)
    exts: dict[str, dict[str, int]] # name -> {off, bitpix, nx, ny}
    flag_header: str | None
    wave: bytes | None              # serialized WCS-WAVE HDU

    def to_json(self) -> bytes:
        return json.dumps({
            "size": self.size, "header": self.header, "exts": self.exts,
            "flag_header": self.flag_header,
            "wave": self.wave.hex() if self.wave else None,
        }).encode()

    @classmethod
    def from_json(cls, raw: bytes) -> "Layout":
        d = json.loads(raw)
        return cls(size=d["size"], header=d["header"], exts=d["exts"],
                   flag_header=d.get("flag_header"),
                   wave=bytes.fromhex(d["wave"]) if d.get("wave") else None)


def window_half_px(fov_arcsec: float, scale: float = 6.15, margin: float = 1.2) -> int:
    """Half-size (pixels) of a detector-aligned window that contains a north-up square
    of side fov*margin at any rotation."""
    return int(math.ceil(fov_arcsec * margin / 2 * math.sqrt(2) / scale)) + 2


def snap_half(half: int) -> int:
    """Round window sizes up to a multiple of 8 so different requests can share cached cutouts."""
    return int(math.ceil(half / 8.0) * 8)


class CutoutFetcher:
    def __init__(self, settings: Settings | None = None, cache: CacheBackend | None = None) -> None:
        self.s = settings or get_settings()
        self.cache = cache or get_cache()
        # concurrent HTTP requests per host: IRSA (and others) get MAX_PARALLEL_CUTOUTS (8);
        # the AWS open-data bucket can take more (MAX_PARALLEL_S3, default 16)
        self.sem = asyncio.Semaphore(self.s.max_parallel_cutouts)
        self.sem_s3 = asyncio.Semaphore(self.s.max_parallel_s3)
        self.active = asyncio.Semaphore(self.s.max_parallel_s3 + self.s.max_parallel_cutouts)  # exposures in flight
        self._multirange_ok = self.s.use_multirange
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.s.cutout_timeout_s, connect=30),
            limits=httpx.Limits(max_connections=self.s.max_parallel_cutouts + self.s.max_parallel_s3),
            headers={"User-Agent": "NexusViewer/0.1 (NASA Space Apps 2026 student project)"},
            follow_redirects=True,
        )
        self.bytes_downloaded = 0

    async def aclose(self) -> None:
        await self.client.aclose()

    # ------------------------------------------------------------------ HTTP
    async def _get(self, url: str, headers: dict[str, str] | None = None,
                   params: dict[str, str] | None = None, attempts: int = 4,
                   partial: bool = False) -> httpx.Response:
        """GET with retries/backoff. With `partial=True` (a Range request) the body is only
        read if the server answers 206; a 200 (server ignored Range) would mean downloading
        the whole 65 MB file, so it is refused instead."""
        delay = 1.0
        last: Exception | None = None
        for i in range(attempts):
            try:
                async with (self.sem_s3 if "amazonaws.com" in url else self.sem):
                    req = self.client.build_request("GET", url, headers=headers, params=params)
                    r = await self.client.send(req, stream=True)
                    try:
                        if partial and r.status_code == 200:
                            raise FetchError(f"server ignored Range header: {url.split('/')[2]}")
                        if r.status_code in (200, 206):
                            await r.aread()
                            self.bytes_downloaded += len(r.content)
                            return r
                    finally:
                        await r.aclose()
                if r.status_code in (404, 403, 416):
                    raise FetchError(f"HTTP {r.status_code} for {url}")
                last = FetchError(f"HTTP {r.status_code}")
            except FetchError:
                raise
            except (httpx.HTTPError, OSError) as exc:
                last = exc
            if i < attempts - 1:
                await asyncio.sleep(delay)
                delay *= 2
        raise FetchError(f"giving up on {url}: {last}")

    async def _range(self, url: str, start: int, end_incl: int) -> tuple[bytes, int]:
        r = await self._get(url, headers={"Range": f"bytes={start}-{end_incl}"}, partial=True)
        total = -1
        cr = r.headers.get("content-range", "")
        if "/" in cr:
            try:
                total = int(cr.rsplit("/", 1)[1])
            except ValueError:
                pass
        return r.content, total

    async def _suffix(self, url: str, n: int) -> bytes:
        r = await self._get(url, headers={"Range": f"bytes=-{n}"}, partial=True)
        return r.content

    async def _multirange(self, url: str, ranges: list[tuple[int, int]]) -> list[bytes]:
        """Several byte ranges in one request (multipart/byteranges). IRSA's Apache server
        supports this (S3 does not). IRSA accepts at most 100 ranges per request."""
        out: list[bytes] = []
        for k in range(0, len(ranges), MAX_RANGES_PER_REQUEST):
            chunk = ranges[k:k + MAX_RANGES_PER_REQUEST]
            spec = ",".join(f"{a}-{b}" for a, b in chunk)
            r = await self._get(url, headers={"Range": f"bytes={spec}"}, partial=True)
            ctype = r.headers.get("content-type", "")
            if len(chunk) == 1 and "multipart" not in ctype:
                out.append(r.content)
                continue
            parts = _parse_multipart(r.content, ctype)
            for a, b in chunk:
                piece = parts.get(a)
                if piece is None or len(piece) < b - a + 1:
                    raise FetchError("multipart response is missing a range")
                out.append(piece[: b - a + 1])
        return out

    def _sources(self, exp: Exposure) -> list[str]:
        s3 = self.s.s3_https_base + exp.s3_key if exp.s3_key else None
        irsa = exp.uri
        order = [s3, irsa] if self.s.range_source == "s3" else [irsa, s3]
        return [u for u in order if u]

    # --------------------------------------------------------------- layout
    async def _read_layout(self, url: str) -> Layout:
        # gather (not two awaits) so a failure of one request never leaves the other's
        # exception unretrieved ("Task exception was never retrieved" log spam).
        (head, total), tail = await asyncio.gather(
            self._range(url, 0, HEADER_CHUNK - 1), self._suffix(url, TAIL_CHUNK))

        pos = header_end(head, 0)  # end of primary header (primary has no data)
        if pos is None:
            raise FetchError("primary header not found")
        exts: dict[str, dict[str, int]] = {}
        image_header: str | None = None
        flag_header: str | None = None
        buf, buf_start = head, 0
        while not all(e in exts for e in NEEDED_EXTS):
            rel = pos - buf_start
            end = header_end(buf, rel) if 0 <= rel < len(buf) else None
            chunk = HEADER_CHUNK
            while end is None:
                buf, _ = await self._range(url, pos, pos + chunk - 1)
                buf_start, rel = pos, 0
                end = header_end(buf, 0)
                if end is None:
                    if len(buf) < chunk or chunk >= 16 * HEADER_CHUNK:
                        raise FetchError("extension header not found")
                    chunk *= 4
            hdr = fits.Header.fromstring(buf[rel:end].decode("ascii", "replace"))
            name = str(hdr.get("EXTNAME", "")).strip().upper().rstrip("0123456789")
            data_off = buf_start + end
            if name in NEEDED_EXTS:
                if hdr.get("ZIMAGE"):
                    # tile-compressed image (Phase 0: FLAGS is RICE_1, one tile per row)
                    zp = {str(hdr.get(f"ZNAME{i}", "")).strip().upper(): hdr.get(f"ZVAL{i}") for i in range(1, 6)}
                    exts[name] = {"off": data_off, "bitpix": int(hdr["ZBITPIX"]),
                                  "nx": int(hdr["ZNAXIS1"]), "ny": int(hdr["ZNAXIS2"]),
                                  "zcmp": str(hdr["ZCMPTYPE"]).strip().upper(),
                                  "ztile1": int(hdr.get("ZTILE1", hdr["ZNAXIS1"])), "ztile2": int(hdr.get("ZTILE2", 1)),
                                  "table_bytes": int(hdr["NAXIS1"]) * int(hdr["NAXIS2"]),
                                  "theap": int(hdr.get("THEAP", int(hdr["NAXIS1"]) * int(hdr["NAXIS2"]))),
                                  "row_bytes": int(hdr["NAXIS1"]), "tform": str(hdr["TFORM1"]).strip().upper(),
                                  "blocksize": int(zp.get("BLOCKSIZE") or 32), "bytepix": int(zp.get("BYTEPIX") or 4)}
                else:
                    exts[name] = {"off": data_off, "bitpix": int(hdr["BITPIX"]),
                                  "nx": int(hdr["NAXIS1"]), "ny": int(hdr["NAXIS2"])}
                if name == "IMAGE":
                    image_header = hdr.tostring()
                elif name == "FLAGS":
                    flag_header = hdr.tostring()
            elif hdr.get("XTENSION") is None:
                raise FetchError("lost track of FITS structure")
            pos = data_off + data_size(hdr)
            if total > 0 and pos >= total:
                break
        if image_header is None or "IMAGE" not in exts:
            raise FetchError("IMAGE extension not found")

        wave = self._parse_wave_from_tail(tail)
        return Layout(size=total, header=image_header, exts=exts, flag_header=flag_header, wave=wave)

    @staticmethod
    def _parse_wave_from_tail(tail: bytes) -> bytes | None:
        # Header blocks start on 2880-byte boundaries counted from the END of the file
        # only if the file length is a multiple of 2880 (FITS guarantees this).
        start_mod = len(tail) % 2880
        for off in range(start_mod, len(tail), 2880):
            if tail[off:off + 9] != b"XTENSION=":
                continue
            end = header_end(tail, off)
            if end is None:
                continue
            hdr = fits.Header.fromstring(tail[off:end].decode("ascii", "replace"))
            if str(hdr.get("EXTNAME", "")).strip().upper().startswith("WCS-WAVE"):
                size = data_size(hdr)
                raw = tail[off:end + size]
                try:
                    hdu = fits.BinTableHDU.fromstring(raw)
                    return wave_hdu_to_bytes(hdu)
                except Exception as exc:
                    log.debug("WCS-WAVE parse failed: %s", exc)
                    return None
        return None

    async def _layout(self, exp: Exposure, url: str) -> Layout:
        path = f"{sha1(exp.uri)}/layout_v2.json"
        raw = await asyncio.to_thread(self.cache.get_blob, "cutouts", path)
        if raw:
            return Layout.from_json(raw)
        layout = await self._read_layout(url)
        await asyncio.to_thread(self.cache.put_blob, "cutouts", path, layout.to_json(), "application/json")
        return layout

    # ------------------------------------------------------------ cutouts
    async def get_cutout(self, exp: Exposure, ra: float, dec: float, half_px: int) -> Cutout | None:
        """Return a Cutout centred near (ra, dec) of half-size `half_px`, or None if the
        position is off this detector. Uses and fills the cache."""
        if self.s.fetch_strategy == "cutout":
            return await self._get_ibe_cutout(exp, ra, dec, half_px)
        try:
            return await self._get_range_cutout(exp, ra, dec, half_px)
        except FetchError as exc:
            log.info("range read failed for %s (%s); using the IBE cutout service", exp.key, exc)
        try:
            return await self._get_ibe_cutout(exp, ra, dec, half_px)
        except Exception as exc:
            raise FetchError(f"{exp.key}: all fetch methods failed ({exc})") from exc

    async def _get_range_cutout(self, exp: Exposure, ra: float, dec: float, half_px: int) -> Cutout | None:
        layout = None
        for url in self._sources(exp):
            try:
                layout = await self._layout(exp, url)
                break
            except FetchError as exc:
                log.info("layout read failed on %s (%s)", url.split("/")[2], exc)
        if layout is None:
            raise FetchError("could not read FITS layout")
        img = layout.exts["IMAGE"]
        nx, ny = img["nx"], img["ny"]
        header = fits.Header.fromstring(layout.header)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            w = WCS(header).celestial
            px, py = w.world_to_pixel_values(ra, dec)
        if not (np.isfinite(px) and np.isfinite(py)):
            return None
        cx, cy = int(round(float(px))), int(round(float(py)))
        if cx < -half_px or cy < -half_px or cx >= nx + half_px or cy >= ny + half_px:
            return None
        x0, x1 = max(cx - half_px, 0), min(cx + half_px + 1, nx)
        y0, y1 = max(cy - half_px, 0), min(cy + half_px + 1, ny)
        if x1 - x0 < 3 or y1 - y0 < 3:
            return None

        # cache: any stored window for this exposure that contains the requested one
        prefix = f"{sha1(exp.uri)}/w2_"
        names = await asyncio.to_thread(self.cache.list_blobs, "cutouts", prefix)
        for name in names:
            try:
                wx0, wy0, wx1, wy1 = (int(v) for v in name.rsplit("w2_", 1)[1].split(".")[0].split("_"))
            except ValueError:
                continue
            if wx0 <= x0 and wy0 <= y0 and wx1 >= x1 and wy1 >= y1:
                raw = await asyncio.to_thread(self.cache.get_blob, "cutouts", name)
                if raw:
                    c = Cutout.from_bytes(raw)
                    return c.crop(x0 - wx0, y0 - wy0, x1 - wx0, y1 - wy0)

        image, flags, var, zodi = await self._read_window(exp, layout, x0, y0, x1, y1)
        assert image is not None
        hdr = header.copy()
        shift_crpix(hdr, x0, y0)
        flag_hdr = fits.Header.fromstring(layout.flag_header) if layout.flag_header else None
        cut = Cutout(
            image=image.astype(np.float32),
            flags=(flags.astype(np.int64) & 0xFFFFFFFF) if flags is not None else np.zeros(image.shape, np.int64),
            variance=var.astype(np.float32) if var is not None else np.full(image.shape, np.nan, np.float32),
            zodi=zodi.astype(np.float32) if zodi is not None else None,
            header=hdr, wave_hdu_bytes=layout.wave,
            flag_names=flag_names_from_header(flag_hdr), x0=x0, y0=y0,
        )
        await asyncio.to_thread(
            self.cache.put_blob, "cutouts", f"{prefix}{x0}_{y0}_{x1}_{y1}.npz", cut.to_bytes()
        )
        return cut

    async def _read_window(self, exp: Exposure, layout: Layout, x0: int, y0: int, x1: int,
                           y1: int) -> list[np.ndarray | None]:
        comp = {n: e for n, e in layout.exts.items() if "zcmp" in e}
        names = [n for n in NEEDED_EXTS if n in layout.exts and n not in comp]
        width = x1 - x0

        async def compressed(name: str) -> np.ndarray:
            return await self._read_compressed_rows(exp, layout.exts[name], x0, y0, x1, y1)

        comp_task = {n: asyncio.create_task(compressed(n)) for n in comp}
        nx_full = layout.exts["IMAGE"]["nx"]
        # Narrow windows: ask IRSA for just the needed piece of every row (multi-range).
        if width * 3 < nx_full and self._multirange_ok:
            try:
                ranges: list[tuple[int, int]] = []
                for n in names:
                    e = layout.exts[n]
                    bpp = abs(e["bitpix"]) // 8
                    for row in range(y0, y1):
                        a = e["off"] + (row * e["nx"] + x0) * bpp
                        ranges.append((a, a + width * bpp - 1))
                pieces = await self._multirange(exp.uri, ranges)
                out: dict[str, np.ndarray] = {}
                rows = y1 - y0
                for k, n in enumerate(names):
                    e = layout.exts[n]
                    raw = b"".join(pieces[k * rows:(k + 1) * rows])
                    out[n] = np.frombuffer(raw, dtype=numpy_dtype(e["bitpix"])).reshape(rows, width)
                for n, t in comp_task.items():
                    out[n] = await t
                return [out.get(n) for n in NEEDED_EXTS]
            except FetchError as exc:
                log.info("multi-range read failed (%s); falling back to full-row reads", exc)

        async def full_rows(name: str) -> np.ndarray | None:
            e = layout.exts.get(name)
            if e is None:
                return None
            if name in comp_task:
                return await comp_task[name]
            bpp = abs(e["bitpix"]) // 8
            start = e["off"] + y0 * e["nx"] * bpp
            end = e["off"] + y1 * e["nx"] * bpp - 1
            last: Exception | None = None
            for url in self._sources(exp):
                try:
                    raw, _ = await self._range(url, start, end)
                    arr = np.frombuffer(raw, dtype=numpy_dtype(e["bitpix"])).reshape(y1 - y0, e["nx"])
                    return arr[:, x0:x1]
                except FetchError as exc:
                    last = exc
            raise FetchError(f"row read failed: {last}")

        return list(await asyncio.gather(*(full_rows(n) for n in NEEDED_EXTS)))

    async def _read_compressed_rows(self, exp: Exposure, e: dict[str, Any], x0: int, y0: int, x1: int,
                                    y1: int) -> np.ndarray:
        """Rows y0..y1 of a tile-compressed image whose tiles are single rows."""
        if e.get("ztile2", 1) != 1 or e.get("ztile1") != e["nx"]:
            raise FetchError("unsupported tile shape")
        if e["zcmp"] not in ("RICE_1", "GZIP_1", "GZIP_2"):
            raise FetchError(f"unsupported compression {e['zcmp']}")
        from astropy.io.fits.hdu.compressed._codecs import Gzip1, Gzip2, Rice1

        wide = e["tform"].startswith("1Q")  # 64-bit descriptors
        rb = e["row_bytes"]
        last: Exception | None = None
        for url in self._sources(exp):
            try:
                desc_raw, _ = await self._range(url, e["off"] + y0 * rb, e["off"] + y1 * rb - 1)
                d = np.frombuffer(desc_raw, dtype=">i8" if wide else ">i4").reshape(y1 - y0, 2)
                counts, offs = d[:, 0].astype(np.int64), d[:, 1].astype(np.int64)
                heap0 = e["off"] + e["theap"]
                lo, hi = int(offs.min()), int((offs + counts).max())
                heap, _ = await self._range(url, heap0 + lo, heap0 + hi - 1)
                bp = abs(e["bitpix"]) // 8
                rows = []
                for c, o in zip(counts, offs):
                    buf = np.frombuffer(heap[o - lo:o - lo + c], dtype=np.uint8)
                    if e["zcmp"] == "RICE_1":
                        codec: Any = Rice1(blocksize=e["blocksize"], bytepix=e["bytepix"], tilesize=e["nx"])
                        arr = np.frombuffer(codec.decode(buf), dtype=f"<i{e['bytepix']}")
                    else:
                        codec = Gzip1() if e["zcmp"] == "GZIP_1" else Gzip2(itemsize=bp)
                        arr = np.frombuffer(codec.decode(buf), dtype=numpy_dtype(e["bitpix"]))
                    rows.append(np.asarray(arr[: e["nx"]]).astype(np.int64)[x0:x1])
                return np.vstack(rows)
            except FetchError as exc:
                last = exc
        raise FetchError(f"compressed read failed: {last}")

    async def _get_ibe_cutout(self, exp: Exposure, ra: float, dec: float, half_px: int) -> Cutout | None:
        size_deg = (2 * half_px + 1) * self.s.pixel_scale_arcsec / 3600.0
        path = f"{sha1(exp.uri)}/ibe_{ra:.6f}_{dec:.6f}_{size_deg:.5f}.npz"
        raw = await asyncio.to_thread(self.cache.get_blob, "cutouts", path)
        if raw:
            return Cutout.from_bytes(raw)
        r = await self._get(exp.uri, params={"center": f"{ra},{dec}d", "size": f"{size_deg}", "gzip": "1"})
        try:
            cut = await asyncio.to_thread(parse_cutout_fits, r.content)
        except Exception as exc:
            raise FetchError(f"bad cutout FITS: {exc}") from exc
        await asyncio.to_thread(self.cache.put_blob, "cutouts", path, cut.to_bytes())
        return cut

    async def get_many(
        self, exposures: list[Exposure], positions: list[tuple[float, float]], half_px: int,
        on_progress: Any = None, errors: list[str] | None = None,
    ) -> list[Cutout | None]:
        """Fetch cutouts for many exposures concurrently. `positions[i]` is the centre for
        exposure i. Failures are logged and returned as None."""
        done = 0
        results: list[Cutout | None] = [None] * len(exposures)

        async def one(i: int) -> None:
            nonlocal done
            ra, dec = positions[i]
            try:
                async with self.active:  # finish exposures roughly in order -> frames appear progressively
                    results[i] = await self.get_cutout(exposures[i], ra, dec, half_px)
            except Exception as exc:
                log.warning("cutout %s failed: %s", exposures[i].key, exc)
                if errors is not None:
                    errors.append(f"{exposures[i].key}: {exc}")
            done += 1
            if on_progress:
                on_progress(done, len(exposures), i, results[i])

        await asyncio.gather(*(one(i) for i in range(len(exposures))))
        return results
