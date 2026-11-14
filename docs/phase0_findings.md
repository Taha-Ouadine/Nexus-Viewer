# Phase 0 — Data probe findings (2026-11-13)

Script: `backend/scripts/phase0_probe.py` (run with `backend/.venv/Scripts/python -u scripts/phase0_probe.py --json ../docs/phase0_raw.json`).
Full console output: [`phase0_probe_output.txt`](phase0_probe_output.txt); machine-readable: [`phase0_raw.json`](phase0_raw.json).
The script ran end to end for all 5 targets (acceptance criterion met).

## Summary table (live archive, DR1 + QR3, wide + deep collections)

| Target | Exposures (after dedupe) | Per detector D1..D6 | Time span | Epochs (30-day gap) | Motion per 6 months | Offset of J2000 position by 2026 |
|---|---|---|---|---|---|---|
| Barnard's Star | 363 (DR1 240 + QR3 123) | 60/62/60/60/62/59 | 2025-08-15 → 2026-09-22 | 3 (120/120/123 exp.) | **0.84 px** (10.39″/yr) | **272″** |
| Epsilon Indi B | 465 (DR1 345 + QR3 120) | 48/93/99/45/84/96 | 2025-04-24 → 2026-10-02 | 4 | 0.38 px (4.68″/yr) | 122″ |
| WISE 0855−0714 | 261 (DR1 only) | 38/48/45/37/48/45 | 2025-05-05 → 2026-05-14 | 3 (30/131/100 exp.) | **0.66 px** (8.15″/yr) | 212″ |
| RW Aurigae | 335 (DR1 226 + QR3 109) | 56/55/56/56/56/56 | 2025-09-01 → 2026-09-16 | 3 | ~0 | 0.6″ |
| R Draconis | **2493** (DR1 413 + DR1-deep 1225 + QR3 126 + QR3-deep 729) | 584/89/574/584/89/573 | 2025-04-24 → 2026-09-27 | **2** with plain gap clustering (continuous coverage) | ~0 | 0.6″ |

## Plan assumptions: confirmed

- **SIA collections**: `spherex_dr1`, `spherex_dr1_cube`, `spherex_dr1_deep`, `spherex_qr3`, `spherex_qr3_deep` (listed live by `Irsa.list_collections(servicetype='SIA', filter='spherex')`).
- **Bandpass names**: `SPHEREx-D1` … `SPHEREx-D6`.
- **Cutout service**: `?center={ra},{dec}d&size={deg}` works and returns `PRIMARY, IMAGE, FLAGS, VARIANCE, ZODI, EPSF, WCS-WAVE`. `BUNIT = 'MJy / sr'`. No numeric EXTNAME suffix was seen and no `CUTOUT_INFO` table was present, but the parser tolerates both.
- **Celestial WCS**: `RA---TAN-SIP` (3rd-order SIP).
- **Pixel scale**: SIA reports `s_pixel_scale = 6.15`; the local WCS gives 6.13–6.17″/px depending on the position on the detector.
- **Per-pixel wavelength**: `WCS(hdr, fobj=hdul, key='W')` with `w.sip = None` works (e.g. 4.9156 µm at WISE 0855 in D6; 1.10 µm at Barnard's Star in D2). The WCS-WAVE lookup table is 9×9 or 11×11. astropy prints an INFO about SIP on every call, which the code silences.
- **Flag bits**: the FLAGS header carries `MSKNnnnn`, `MSKMnnnn`, `MSKDnnnn` keywords whose names match the plan's table. They are read at runtime.
- **Solid-angle pixel maps** exist at `{dr1|qr3}/solid_angle_pixel_map/cal-sapm-v3-2026-191/{k}/solid_angle_pixel_map_D{k}_spx_cal-sapm-v3-2026-191.fits` (S3 and IBE). They hold one 2040×2040 float32 IMAGE extension with `BUNIT = 'arcsec2'` (not steradians). The path is stored in `releases.json` → `sapm_path_template`.
- **S3 bucket** `nasa-irsa-spherex` (public, us-east-1) has the `dr1/`, `qr2/` and `qr3/` prefixes. The SIA `cloud_access` column gives the exact S3 key of every file.
- **Epochs**: with a 30-day gap, Barnard's Star, WISE 0855 and RW Aur split cleanly into 3 survey passes. Within a pass, gaps are 5–27 days; between passes, 100–180 days.

## Plan assumptions that turned out wrong, and what the code does instead

1. **DR1 and QR3 are not duplicates of each other.** DR1 holds 2025-04 → 2026-05; QR3 holds the *newer* exposures (2026-08 → 2026-10). Zero exposures appeared in both releases for any target. → Both releases are active by default and complement each other. Deduplication (key = `obs_id` + detector, highest `priority` wins) is still implemented in case future releases overlap.
2. **The release column** is `obs_collection` in SIA/ObsCore (`observation.collection` in the CAOM TAP tables), not a field of `spherex.plane`. The registry maps collections → release (`releases.json` → `sia_collections`). The `*_deep` collections must be included: for R Dra they hold 78% of all exposures.
3. **TAP is not usable for interactive queries.** The plan's `spherex.artifact JOIN spherex.plane` query returned *502 Proxy Error*. A query on `spherex.obscore` hung for over 3 minutes, and a later attempt timed out at 120 s. SIA answered in 3–5 s (25 s for R Dra's 2493 rows). → SIA v2 is the primary path, called **directly over HTTP with a hard timeout**. One `astroquery`/`pyvo` SIA call hung indefinitely, and those libraries have no timeout. TAP remains as the fallback.
4. **The cutout service is slow and heavy.** Every cutout includes the full `EPSF` table (441 rows × 1089 doubles ≈ 3.8 MB) whatever the cutout size, so each cutout is about 4 MB and takes 13–17 s. Ten parallel cutouts (8 workers) took 33–46 s and 40 MB, i.e. a 360-exposure target would take ~13 minutes. The service has no option to skip extensions.
   → New default **"range reader"** (`services/cutouts.py`). Both S3 and IRSA honour HTTP `Range` (206). The code reads the FITS headers once per file (cached), then fetches only the rows of IMAGE/FLAGS/VARIANCE/ZODI it needs plus the 6 kB WCS-WAVE table from the end of the file. Result: **10 exposures in 4–6 s and 15 MB** (vs 33–46 s and 40 MB), with pixel values and wavelengths identical to the cutout service (verified on the same exposure: same origin pixel (1615, 293), same λ = 4.9156 µm, same median). S3 is tried first; IRSA IBE and then the cutout service are fallbacks (`FETCH_STRATEGY`, `RANGE_SOURCE` env vars).
5. **The plan's motion estimates were 2× too high.** Barnard's Star moves 10.4″/yr = 5.2″ per 6 months = **0.84 px** (not 1.7 px). WISE 0855 moves 0.66 px per 6 months (not 1.3). Over the full ~13–17-month baseline, Barnard's Star moves ≈2.2 px and WISE 0855 ≈1.3 px. So zoom ≥ 4 and difference mode are important.
6. **The catalog coordinates in the plan are not where the stars are now.** Barnard's Star's J2000 position is **272″ away** from where SPHEREx sees it (outside a 180″ field). The WISE 0855 coordinate given in the plan (133.79513, −7.24515) is an older WISE-era position; SIMBAD's J2000 position is (133.81891, −7.24705), and SPHEREx sees it at about (133.7598, −7.2422). → Every target stores its J2000 position and proper motion, and the viewer centres on the position **propagated to J2026.0** (`view_ra`/`view_dec` in `targets.json`). The red crosshair shows the propagated position for each frame's date.
7. **Deep fields have no gaps.** R Dra (7° from the North Ecliptic Pole) is observed almost continuously, so gap clustering gives one 394-day "epoch". → `cluster_times` now also cuts any cluster longer than max(60 d, 2 × window) into window-sized bins. The job and photometry code also subsample evenly to at most 600 exposures.
8. **Processing versions vary per file inside a release** (`l2b-v27-2026-228` … `-268`, plus one `l2b_retry-…`). → The cache key uses the newest version seen per release at that position.
9. **SIMBAD's TAP service at CDS was down** during the build (404 / "Page unavailable"), so `astroquery.simbad` failed. → Name resolution uses **CDS Sesame** XML (`-oxp`), which returns position, proper motion and parallax in one call. CDS redirects to a mirror when busy, and the Harvard Sesame mirror is a configured fallback.
10. **WISE 0855 has no QR3 coverage yet** (DR1 only, 3 epochs).
11. *(Found while building the range reader.)* In the **full Level-2 files the FLAGS extension is a tile-compressed image** (`ZIMAGE=T`, `RICE_1`, one tile per row), not a plain int32 image as it appears in cutouts. A naive byte-range read returns garbage flags. → `cutouts.py` reads the row descriptors and the compressed heap and decodes them with astropy's RICE codec. Verified bit-for-bit against the cutout service for IMAGE, FLAGS, VARIANCE and ZODI.
12. *(Found while building the range reader.)* **IRSA accepts HTTP multi-range requests** (`multipart/byteranges`), so we can fetch just the needed columns of each row in one request (~0.4 MB per exposure, mostly headers). IRSA answers with the **whole 65 MB file when more than 100 ranges** are requested, so requests are capped at 100 ranges and the client refuses any non-206 answer. S3 ignores multi-range requests (it returns the whole file), so S3 is used only for header reads.
13. **Gaia neighbour of WISE 0855.** In 2025–26, WISE 0855 passes 6.8″ (about 1 pixel) from a G = 16.3 background star (Gaia DR3 5756956644387831296). Short-wavelength images and photometry at its position are dominated by that star (see PROJECT_EXPLAINED §10).

## Timing reference (this machine, residential connection)

| Operation | Time |
|---|---|
| SIA query, 1 position, 4 collections | 3–5 s (25 s for 2500 rows) |
| IBE cutout, 1 exposure | 13–17 s, ~4 MB |
| Range read, 1 exposure, cold (headers + 4 row bands) | 2.6 s (S3) / 4.5 s (IRSA) |
| Range read, same exposure, cached | 0.013 s |
| 10 exposures in parallel: cutout service vs range reader | 33–46 s vs 4–6 s |
| Full job WISE 0855, D6, 180″ (45 exposures → 3 frames) | 20.6 s cold, 0.003 s cached |
