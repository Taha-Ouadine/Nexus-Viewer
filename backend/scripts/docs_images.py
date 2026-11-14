"""Render PNG strips (all frames side by side, crosshair at the target) from cached
frame sets, for PROJECT_EXPLAINED.md. Reads the local cache directly (no server needed).

Usage: python scripts/docs_images.py --out ../docs/img
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.services.cache import get_cache  # noqa: E402
from app.services.coadd import difference  # noqa: E402
from app.services.render import decode_frame, stretch  # noqa: E402


def records() -> list[dict]:
    root = get_settings().cache_dir / "records" / "frame_sets"
    out = []
    for p in root.glob("*.json"):
        d = json.loads(p.read_text())
        rec = d["payload"]
        if rec.get("frames"):
            rec["_hash"] = rec["frames"][0]["id"].rsplit("-", 1)[0]
            rec["_mtime"] = p.stat().st_mtime
            out.append(rec)
    return sorted(out, key=lambda r: r["_mtime"])


def find(ra: float, band: str, mode: str = "epochs") -> dict | None:
    hits = [r for r in records() if abs(r["request"]["ra"] - ra) < 1e-3 and r["request"]["band"] == band
            and r["request"]["mode"] == mode]
    return hits[-1] if hits else None


def strip(rec: dict, out: Path, zoom: int = 8, diff: str = "none", label: str = "") -> None:
    cache = get_cache()
    h = rec["_hash"]
    frames = rec["frames"]
    chans = [decode_frame(cache.get_blob("frames", f"{h}/{m['idx']}.bin"), m["width"], m["height"], m["n_channels"])
             for m in frames]
    n_ch = len(chans[0])
    if diff != "none":
        per = [difference([c[ci] for c in chans], diff) for ci in range(n_ch)]
        chans = [[per[ci][k] for ci in range(n_ch)] for k in range(len(chans))]
    lims = []
    for ci in range(n_ch):
        allv = np.concatenate([c[ci].ravel() for c in chans])
        allv = allv[np.isfinite(allv)]
        if diff != "none":
            m = np.percentile(np.abs(allv), 99.5)
            lims.append((-m, m))
        else:
            lims.append((np.percentile(allv, 0.5), np.percentile(allv, 99.5)))
    tiles = []
    for m, ch in zip(frames, chans):
        if n_ch == 1:
            g = (stretch(ch[0], *lims[0], "linear" if diff != "none" else "asinh") * 255).astype(np.uint8)
            im = Image.fromarray(g, "L").convert("RGB")
        else:
            b, gg, r = ((stretch(c, *lims[i], "asinh") * 255).astype(np.uint8) for i, c in enumerate(ch))
            im = Image.fromarray(np.dstack([r, gg, b]), "RGB")
        im = im.resize((im.width * zoom, im.height * zoom), Image.Resampling.NEAREST)
        d = ImageDraw.Draw(im)
        if m.get("target"):
            x, y = (m["target"]["x"] + 0.5) * zoom, (m["target"]["y"] + 0.5) * zoom
            g0, ln = 2.5 * zoom, 3 * zoom
            for a, b_ in (((x - g0 - ln, y), (x - g0, y)), ((x + g0, y), (x + g0 + ln, y)),
                          ((x, y - g0 - ln), (x, y - g0)), ((x, y + g0), (x, y + g0 + ln))):
                d.line([a, b_], fill=(213, 94, 0), width=2)
        d.rectangle([0, 0, im.width, 16], fill=(0, 0, 0))
        d.text((4, 2), f"{m['date_mid'][:10]}  n={m['n_exposures']}", fill=(255, 255, 0))
        tiles.append(im)
    W = sum(t.width for t in tiles) + 6 * (len(tiles) - 1)
    canvas = Image.new("RGB", (W, tiles[0].height + (20 if label else 0)), (20, 20, 30))
    x = 0
    for t in tiles:
        canvas.paste(t, (x, 20 if label else 0))
        x += t.width + 6
    if label:
        ImageDraw.Draw(canvas).text((4, 4), label, fill=(230, 230, 230))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    print("wrote", out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "docs" / "img"))
    a = ap.parse_args()
    out = Path(a.out)
    targets = {t["slug"]: t for t in json.loads((get_settings().data_dir / "targets.json").read_text())}
    plan = [
        ("barnards-star", "ALL", "none", "Barnard's Star, ALL bands (crosshair = Gaia position moved to each date)"),
        ("eps-indi-b", "D6", "none", "Epsilon Indi B, D6"),
        ("eps-indi-b", "D6", "first", "Epsilon Indi B, D6, difference (each frame minus the first)"),
        ("wise-0855", "D6", "none", "WISE 0855-0714, D6 (4.4-5.0 um)"),
        ("wise-0855", "D1", "none", "WISE 0855-0714, D1 (0.75-1.09 um): what you see at the crosshair is a G=16.3 background star 7 arcsec away"),
        ("wise-0855", "RGB:D2,D4,D5+D6", "none", "WISE 0855-0714, 'Brown dwarf hunter' false colour (B=D2, G=D4, R=D5+D6)"),
        ("rw-aur", "D2", "none", "RW Aurigae, D2"),
        ("r-dra", "D1", "none", "R Draconis, D1"),
    ]
    for slug, band, diff, label in plan:
        t = targets[slug]
        rec = find(t["view_ra"], band)
        if rec is None:
            print("no cached frame set for", slug, band)
            continue
        name = f"{slug}_{band.replace(':', '').replace(',', '_').replace('+', '')}{'_diff' if diff != 'none' else ''}.png"
        zoom = 8 if rec["frames"][0]["width"] < 40 else 4
        strip(rec, out / name, zoom=zoom, diff=diff, label=label)


if __name__ == "__main__":
    main()
