# Handoff — Nexus Viewer (state at 2026-11-14 ~01:30 local)

Everything I started has been stopped: the FastAPI backend (:8000), the Next.js prod server (:3000), the `python -m http.server 8081` embed test server and my headless Edge debug instance (:9333). No git repo exists, there have been no commits and no deploys.

## 1. Phase status

| Phase | Status | Verified how |
|---|---|---|
| 0 Data probe | **Done** | `backend/scripts/phase0_probe.py` ran end to end for all 5 targets → `docs/phase0_findings.md`, `phase0_raw.json`, `phase0_probe_output.txt` |
| 1 Skeleton/infra | **Done (infra untested)** | Backend `/api/health` OK directly and through the Next rewrite (`curl localhost:3000/api/health`). Dockerfile, compose, CI and Supabase SQL are written but **never run** (no Docker/CLI). Supabase backend code is untested (no keys). |
| 2 Core pipeline | **Done** | `pytest -m live`: **7/7 passed** (observations ≥2 epochs for 5 targets; WISE 0855 D6 job ≥2 frames + cached repeat <1.5 s; Barnard centroid shift within 50% of PM, moving north). Cold Barnard ALL 128 s, RW Aur ALL 55 s, WISE D6 21 s. |
| 3 Viewer | **Done** | `tsc --noEmit` OK, `eslint` 0 errors (2 warnings in copied galaxy-scene), `vitest` 11/11, `npm run build` OK (9 routes). All pages 200. Puppeteer screenshots of viewer/explore/embed show frames playing. Cross-origin iframe test (docs/embed-test/index.html via :8081) rendered frames. CSP: `/embed` frame-ancestors *, others 'self'. |
| 4 Discovery tools | **Mostly done** | Diff (client-side), RGB/presets, WL channels, Gaia/CatWISE overlays (API tested: Gaia contains Barnard with PM; CatWISE contains WISE 0855), flag overlay, Aladin, GIF/PNG/FITS exports exist. Eps Indi B difference shows a motion dipole (docs/img/eps-indi-b_D6_diff.png); WISE 0855 is red in RGB. **The GIF/PNG/FITS endpoints were only exercised by prewarm (GIF); PNG/FITS not explicitly tested.** Flag overlay and Aladin were not visually checked (CDS tiles were down). |
| 5 Spectra/light curves | **Partial** | Endpoints work (202→200 polling). WISE 0855 spectrum OK but blended (see below). Barnard and R Dra spectra are all flagged (saturated). Cold spectrum 53–87 s (goal <20 s **not met**). Click-to-measure in the browser **not** verified with puppeteer (the `--click-target` option in shoot.mjs is untried). |
| 6 Explorer/education | **Done (auth/discoveries skipped by decision)** | /user-types, /explore, /learn, /about render. |
| 7 Hardening/deploy | **Partial** | Release sync script works (`--dry-run` against live IRSA). Prewarm script works (7/8 targets). Rate limiting is wired (slowapi) but untested. No deploy, no Lighthouse, no mobile check. |

Backend checks last run: `ruff check app scripts tests` clean; `mypy app` clean (lenient config: some error codes disabled in pyproject); `pytest` **43 passed**. Frontend: tsc/eslint/vitest/build all passed on the build **before** the last two small edits (see open issues).

## 2. Open issues / unverified

1. **Photometry fix (last change, live-tested once):** `services/photometry.py` now replaces only REPLACE_BITS (6, 9, 10, 11) with sky, marks `flagged` only for SEVERE_BITS (1, 6, 9, 10, 11, 15, 17, 22–26), and adds `saturated`. `irsa.thin_exposures` thins per detector (it replaced the stride thinning, which aliased detectors so R Dra lost all D4 points). `routes/photometry.py` lightcurve per_epoch falls back to flagged points with `flagged: true`. Cache key bumped to v4, job hash to v7. Rerun results:
   - R Dra D1: 141 pts, epoch avgs 0.67–4.2 M µJy (huge scatter, saturated) → "varies", not quantitative. R Dra D4: 140 pts, nonsense values (703 to 165k µJy). **Saturated photometry is unreliable.**
   - RW Aur D2: 167k → 317k → 344k µJy (epoch 0 has n=1).
   - Barnard spectrum: 358/358 flagged (saturated). R Dra spectrum: 597/600 flagged.
   - WISE 0855 spectrum: 221/258 unflagged; medians D1→D6 ≈ 1017, 882, 610, 283, 438, 589 µJy. The short-λ part is a **G=16.3 Gaia star 6.8″ away** (5756956644387831296), not a bug.
2. **Frontend edits after the last build** (source changed, not rebuilt or tsc-checked): landing `relative z-10` sections + GalaxyBackground wrapper classes; LightCurveChart saturated note + `flagged?` in types.ts. Run `npx tsc --noEmit && npm run build`.
3. **NEP deep field prewarm failed** with "invalid blob path". Fixed afterwards in `LocalCache._blob_path` (it now validates path parts instead of using `Path.resolve()`, which misbehaved on Windows under concurrency) but **not re-run**. Its SIA query returns thousands of rows and is slow; `submit()` no longer blocks on it (provisional `pending-…` hash, replaced when known), which is also not re-tested in the browser.
4. Rebuilds from cached cutouts are CPU-bound (~45 ms/exposure: reproject + WCS + wavelength); R Dra D1 (584 exp) took ~200 s even warm.
5. The Aladin panel loads the module, but sky tiles come from CDS, which was down (grey panel).
6. Puppeteer `launch()` of Edge fails; use `connect()` (see §4).
7. `frames` SQL table is never written; Supabase storage cleanup is not implemented.
8. Jobs live in memory: run uvicorn with 1 worker.

## 3. Start commands

```bash
# backend (Git Bash)
cd /e/Users/tahao/Desktop/NASA/nexus-viewer/backend
.venv/Scripts/python.exe -u -m uvicorn app.main:app --port 8000
# frontend
export PATH="/e/Program Files/nodejs:$PATH"
cd /e/Users/tahao/Desktop/NASA/nexus-viewer/frontend
npm run build && npm run start -- -p 3000      # or npm run dev
# tests
cd backend && .venv/Scripts/python.exe -m pytest -q          # 43 pass
.venv/Scripts/python.exe -m pytest -m live -q -p no:cacheprovider   # 7 pass (slow)
```
The venv is Python 3.12 (`py -3.12`); never use the default 3.15. Backend launched from Git Bash with `&` does not show up as a task, so stop it via `netstat -ano | grep ":8000 .*LISTENING"` → `taskkill //PID <pid> //F`. Do **not** `taskkill //IM msedge.exe` (that kills the user's own browser; it was denied once).

## 4. Screenshots (how)

Bash cannot launch Edge (it exits silently). From **PowerShell**:
```powershell
Start-Process "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" -ArgumentList "--headless=new","--no-first-run","--disable-extensions","--user-data-dir=<scratchpad>\pptrprof2","--remote-debugging-port=9333","--window-size=1600,1300","about:blank"
```
Then run Node scripts in `<scratchpad>\pptr` (puppeteer-core@23 installed there), using `puppeteer.connect({browserURL:"http://127.0.0.1:9333"})`:
- `PPTR_WS=http://127.0.0.1:9333 node shoot.mjs "<url>" <out.png> [--timeout=S] [--width= --height=] [--click-target --wait-chart=S --tab=lightcurve]`: waits for `div[role=img] canvas`, prints the frame label and console errors.
- `node simple.mjs <url> <out.png> [w h]`, `node iframe.mjs <out.png>` (needs :8081 serving docs/embed-test).

Scratchpad = `C:\Users\tahao\AppData\Local\Temp\claude\3ea1d5142425df8c\7381e736-1ffe-4a2a-a412-8a222b4606d8\scratchpad` (it also has `runjob.sh` = POST a job and poll; `phot.py` = poll spectrum/lightcurve; `viz.py`). Kill Edge afterwards by its PID only.

## 5. Hard-won knowledge

- **Fetching pixels** (`services/cutouts.py`): IBE cutouts always include the 3.8 MB EPSF table (13–17 s each). Instead, FITS headers are read from S3 (`https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/<cloud_access key>`), then pixels come from IRSA with **multipart byte ranges, ≤100 ranges per request** (more → IRSA returns the whole 65 MB file; the client streams and refuses non-206). S3 ignores multi-range. The **FLAGS ext is RICE_1 tile-compressed (1 row/tile)** in full files and is decoded with astropy `_codecs.Rice1` (pass a uint8 ndarray, not bytes). Output is bit-identical to IBE cutouts. Layout cache = `cutouts/<sha1(uri)>/layout_v2.json`, windows = `w2_x0_y0_x1_y1.npz` (any containing window is reused by cropping).
- **Concurrency**: IRSA/Gaia/CDS ≤ 8 (`MAX_PARALLEL_CUTOUTS`), S3 16 (`MAX_PARALLEL_S3`), exposures in flight = 24 (keeps frames finishing in time order); at most 2 jobs at once. Async primitives are recreated per event loop (`_ensure_loop`).
- **SIA**: called directly with httpx (timeout 240 s, `use_names_over_ids=True`), because pyvo/astroquery have no timeout and hung. TAP: the plane/artifact join gives 502; obscore takes minutes, so it is a fallback only. Exposure lists are cached 24 h.
- **DR1 vs QR3 don't overlap** (QR3 = newer data). `*_deep` collections matter (78% of R Dra).
- **Positions**: catalogue J2000 positions are up to 272″ off by 2026 → `view_ra/view_dec` = position propagated to J2026.0. Real motion: Barnard 0.84 px per 6 months (the plan said 1.7).
- **Name resolution**: SIMBAD TAP at CDS was down → Sesame XML `-oxp` (follows redirect) with the Harvard mirror as fallback. "eps Ind Ba" does not resolve; "Luhman 16" works, its long WISE name times out.
- **Epochs**: gap clustering + cut clusters longer than max(60, 2×window) days into window bins (deep fields).
- **Display coadd**: fully flagged pixels are filled with flagged values; enclosed NaN holes (saturated cores) are filled with the max of their neighbours (`coadd.fill_holes`, display only).
- **Frame binaries**: row 0 = north (flipped from FITS). Frame grid is TAN, east-left.
- **Failed downloads**: if >10% fail, results are **not cached** (one earlier failed run had poisoned the cache).
- **Aladin**: `aladin.cds.unistra.fr/AladinLite/api/v3/*` gave 404, so the pinned npm build is used: `https://cdn.jsdelivr.net/npm/aladin-lite@3.6.5/dist/aladin.js`, an ES module (`default` export, `await A.init`), imported at runtime via `new Function("u","return import(u)")`.

## 6. Caches / outputs

- `backend/.cache/` (~ several hundred MB): `blobs/cutouts`, `blobs/frames/<hash>/`, `records/{observation_cache,frame_sets,photometry_cache,overlay_cache,resolved_names}`. Delete it to reset. Frame sets for the 5 targets (recommended views, hash v7 not yet rebuilt; the existing ones are v6, so the next request rebuilds from cached cutouts), plus WISE D1 and RGB.
- `frontend/public/targets/*.gif`: barnards-star, eps-indi-b, wise-0855, rw-aur, **r-dra (present)**, luhman-16, ecliptic-field (399 frames, large). **nep-deep-field missing.**
- `docs/img/`: strips + screenshots.

## 7. Prioritised TODO for the testing agent

1. Rebuild the frontend (`tsc`, `eslint`, `build`) to include the last two edits; screenshot the landing page.
2. Restart the backend; re-run `scripts/prewarm_cache.py` (the hash bump means rebuilds) and confirm nep-deep-field now succeeds.
3. Browser test click-to-measure (spectrum + light curve tabs) with `shoot.mjs --click-target`, for WISE 0855 and RW Aur.
4. Test PNG and FITS export endpoints, the flag overlay, Gaia/CatWISE toggles, track mode, and the exposures/stack modes in the UI.
5. Re-run `pytest` + `pytest -m live` after the photometry/thinning changes.
6. Decide how to present saturated targets (maybe use the longest-λ or PSF-wing photometry); update PROJECT_EXPLAINED §10 if numbers change.
7. Rate-limit (429) and IRSA-down (503) behaviour; mobile layout.
