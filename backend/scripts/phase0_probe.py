"""Phase 0 data probe: checks the SPHEREx archive against the build plan's assumptions.

For each of the 5 test targets it:
  * resolves the name (CDS Sesame) and propagates the position to the observation epoch,
  * queries SIA (DR1 + QR3, wide + deep collections) and, once, TAP as a cross-check,
  * prints exposure counts per detector/collection, time span and a proposed epoch clustering,
  * downloads 1 cutout from the IBE cutout service and prints the FITS structure, BUNIT,
    pixel scale and the wavelength at the target pixel (WCS key 'W'),
  * times 10 parallel cutouts with the IBE cutout service and with the byte-range reader.

Usage:  python scripts/phase0_probe.py [--skip-tap] [--json out.json]
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import io
import json
import sys
import tempfile
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
from astropy.io import fits  # noqa: E402
from astropy.time import Time  # noqa: E402
from astropy.wcs.utils import proj_plane_pixel_scales  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.services.cache import LocalCache  # noqa: E402
from app.services.cutouts import CutoutFetcher, window_half_px  # noqa: E402
from app.services.epochs import summarize_epochs  # noqa: E402
from app.services.fitsio import parse_cutout_fits  # noqa: E402
from app.services.irsa import _query_sia, _query_tap, _rows_to_exposures, dedupe  # noqa: E402
from app.services.releases import active_releases  # noqa: E402
from app.services.resolver import _sesame_xml, mjd_to_jyear, propagate  # noqa: E402

warnings.filterwarnings("ignore")

TARGETS = [
    ("Barnard's Star", "Barnard's star"),
    ("Epsilon Indi B", "eps Ind B"),
    ("WISE 0855-0714", "WISE J085510.83-071442.5"),
    ("RW Aurigae", "RW Aur"),
    ("R Draconis", "R Dra"),
]


def iso(mjd: float) -> str:
    return str(Time(mjd, format="mjd").iso)[:10]


async def time_parallel(exps, positions, half, strategy: str) -> dict:
    s = get_settings().model_copy()
    s.fetch_strategy = strategy
    f = CutoutFetcher(s, LocalCache(Path(tempfile.mkdtemp(prefix="p0_"))))
    t0 = time.time()
    res = await f.get_many(exps, positions, half)
    dt = time.time() - t0
    await f.aclose()
    return {"strategy": strategy, "n": len(exps), "ok": sum(r is not None for r in res),
            "seconds": round(dt, 1), "MB": round(f.bytes_downloaded / 1e6, 2)}


def probe_target(label: str, name: str, do_tap: bool) -> dict:
    out: dict = {"target": label}
    print(f"\n=== {label} ===")
    res = _sesame_xml(name)
    assert res, f"could not resolve {name}"
    out["resolved"] = res
    print(f"Sesame: {res['name']}  ra={res['ra']:.6f} dec={res['dec']:.6f} (J2000)  "
          f"pm=({res['pmra']}, {res['pmdec']}) mas/yr  plx={res['parallax']}")

    releases = active_releases()
    collections_ = sorted({c for r in releases for c in r.sia_collections})
    t0 = time.time()
    table = _query_sia(res["ra"], res["dec"], collections_)
    out["sia_seconds"] = round(time.time() - t0, 1)
    out["sia_rows"] = len(table)
    by_coll = collections.Counter(str(c) for c in table["obs_collection"])
    print(f"SIA {collections_}: {len(table)} rows in {out['sia_seconds']} s; per collection {dict(by_coll)}")
    out["per_collection"] = dict(by_coll)

    exps_all = _rows_to_exposures(table, releases)
    exps = dedupe(exps_all, releases)
    out["n_after_dedupe"] = len(exps)
    out["duplicates_across_releases"] = len(exps_all) - len(exps)
    per_det = collections.Counter(f"D{e.detector}" for e in exps)
    out["per_detector"] = dict(sorted(per_det.items()))
    print(f"after dedupe (obs_id+detector): {len(exps)} (dropped {out['duplicates_across_releases']}); per detector {dict(sorted(per_det.items()))}")
    tmin = min(e.t_min for e in exps)
    tmax = max(e.t_max for e in exps)
    out["time_span"] = [iso(tmin), iso(tmax)]
    print(f"time span: {iso(tmin)} .. {iso(tmax)}  ({(tmax - tmin):.0f} days)")
    versions = collections.Counter(e.version for e in exps)
    out["versions"] = dict(versions.most_common(5))
    eps = summarize_epochs([e.t_min for e in exps], [e.t_max for e in exps], [e.detector for e in exps], 30.0)
    out["epochs_30d"] = [{**ep, "t_start": iso(ep["t_start"]), "t_end": iso(ep["t_end"])} for ep in eps]
    for ep in out["epochs_30d"]:
        print(f"  epoch {ep['index']}: {ep['t_start']} -> {ep['t_end']}  n={ep['n_exposures']}  {ep['per_detector']}")
    times = np.sort([e.t_min for e in exps])
    gaps = np.diff(times)
    out["gaps_over_5d"] = [round(float(g), 1) for g in gaps[gaps > 5]]
    print(f"  gaps > 5 d between consecutive exposures: {out['gaps_over_5d']}")

    t_mean = float(np.mean([e.t_mid for e in exps]))
    ra_e, dec_e = propagate(res["ra"], res["dec"], res["pmra"], res["pmdec"], 2000.0, t_mean)
    shift = np.hypot((ra_e - res["ra"]) * np.cos(np.radians(dec_e)), dec_e - res["dec"]) * 3600
    out["position_at_mean_epoch"] = {"jyear": round(mjd_to_jyear(t_mean), 3), "ra": ra_e, "dec": dec_e,
                                     "offset_from_J2000_arcsec": round(float(shift), 1)}
    print(f"position at mean epoch J{mjd_to_jyear(t_mean):.2f}: ({ra_e:.5f}, {dec_e:.5f}), {shift:.1f}\" from J2000")
    if res["pmra"] is not None:
        pm_tot = float(np.hypot(res["pmra"], res["pmdec"])) / 1000
        out["motion_px_per_6mo"] = round(pm_tot * 0.5 / 6.15, 2)
        print(f"total PM {pm_tot:.2f}\"/yr -> {pm_tot * 0.5 / 6.15:.2f} px per 6 months")

    if do_tap:
        t0 = time.time()
        try:
            tt = _query_tap(res["ra"], res["dec"], collections_, timeout=120)
            out["tap"] = {"rows": len(tt), "seconds": round(time.time() - t0, 1)}
        except Exception as exc:
            out["tap"] = {"error": str(exc)[:200], "seconds": round(time.time() - t0, 1)}
        print(f"TAP cross-check: {out['tap']}")

    # --- one cutout from the IBE service ---
    import httpx

    e = next(x for x in exps if x.detector == (6 if "WISE" in label else 2))
    t0 = time.time()
    r = httpx.get(e.uri, params={"center": f"{ra_e},{dec_e}d", "size": "0.05", "gzip": "1"}, timeout=180)
    dt = time.time() - t0
    with fits.open(io.BytesIO(r.content)) as hdul:
        buf = io.StringIO()
        hdul.info(output=buf)
        info = buf.getvalue()
        names = [h.name for h in hdul]
        bunit = hdul["IMAGE"].header.get("BUNIT")
    cut = parse_cutout_fits(r.content)
    w = cut.celestial_wcs()
    scales = proj_plane_pixel_scales(w) * 3600
    px, py = w.world_to_pixel_values(ra_e, dec_e)
    lam = cut.wavelength_at(float(px), float(py))
    out["cutout"] = {"uri": e.uri, "seconds": round(dt, 1), "bytes": len(r.content), "extnames": names,
                     "bunit": bunit, "pixel_scale_arcsec": [round(float(s), 3) for s in scales],
                     "lambda_um_at_target": lam, "flag_names_from_header": len(cut.flag_names)}
    print(f"cutout ({e.key}, size 0.05 deg): {len(r.content)/1e6:.2f} MB in {dt:.1f} s")
    print(info.strip())
    print(f"EXTNAMEs {names}; BUNIT={bunit!r}; pixel scale {scales.round(3)} arcsec; "
          f"lambda at target = {lam}")

    # --- 10 parallel cutouts: IBE service vs byte-range reader ---
    sample = exps[:: max(1, len(exps) // 10)][:10]
    pos = [(ra_e, dec_e)] * len(sample)
    half = window_half_px(180.0)
    out["parallel_ibe"] = asyncio.run(time_parallel(sample, pos, half, "cutout"))
    out["parallel_range"] = asyncio.run(time_parallel(sample, pos, half, "range"))
    print(f"10 parallel cutouts (FOV 180\"): IBE {out['parallel_ibe']}  | range reader {out['parallel_range']}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-tap", action="store_true")
    ap.add_argument("--json", default=None)
    ap.add_argument("--only", default=None, help="substring of a target label")
    a = ap.parse_args()
    results = []
    for i, (label, name) in enumerate(TARGETS):
        if a.only and a.only.lower() not in label.lower():
            continue
        try:
            results.append(probe_target(label, name, do_tap=(not a.skip_tap and i == 0)))
        except Exception as exc:
            print(f"!! {label} failed: {exc}")
            results.append({"target": label, "error": str(exc)})
    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=2, default=str))
        print(f"\nwrote {a.json}")


if __name__ == "__main__":
    main()
