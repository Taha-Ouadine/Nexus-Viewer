# Nexus Viewer

SPHEREx time-domain sky viewer for the NASA Space Apps Challenge 2026 (*Planet X and SPHEREx*).
**For what it does and how it works, read [PROJECT_EXPLAINED.md](PROJECT_EXPLAINED.md).**
Phase 0 data findings: [docs/phase0_findings.md](docs/phase0_findings.md). Current status / open issues: [docs/HANDOFF.md](docs/HANDOFF.md).

```
frontend/   Next.js 15 + React 18 + TypeScript + Tailwind v4 + shadcn/ui
backend/    Python 3.12 FastAPI (astropy, reproject, photutils)
supabase/   SQL migration + seed (optional; everything runs without Supabase)
docs/       Phase 0 probe results, screenshots
```

## Prerequisites (Windows, as used during development)

- Python **3.12** (`py -3.12`). Do not use 3.15: astropy/reproject/photutils wheels are not available for it.
- Node.js 22+ (developed with v26.13.1). If `node` is not found in Git Bash:
  `export PATH="/e/Program Files/nodejs:$PATH"`
- Internet access to `irsa.ipac.caltech.edu`, `nasa-irsa-spherex.s3.us-east-1.amazonaws.com`, `cds.unistra.fr`, `gea.esac.esa.int`, `cdn.jsdelivr.net`.

## Backend

```bash
cd backend
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt     # (Linux/macOS: .venv/bin/python)
cp .env.example .env                                              # optional; all settings have defaults
.venv/Scripts/python -m uvicorn app.main:app --port 8000          # http://localhost:8000/docs
```

Useful scripts (run from `backend/`):

| Command | What it does |
|---|---|
| `.venv/Scripts/python -m pytest` | unit + fixture + API tests (no network; 43 tests) |
| `.venv/Scripts/python -m pytest -m live` | live tests against IRSA for the 5 targets (a few minutes) |
| `.venv/Scripts/ruff check app scripts tests` · `.venv/Scripts/python -m mypy app` | lint / type check |
| `.venv/Scripts/python scripts/phase0_probe.py` | the Phase 0 archive probe |
| `.venv/Scripts/python scripts/seed_targets.py [--supabase]` | re-resolve featured targets → `app/data/targets.json` |
| `.venv/Scripts/python scripts/prewarm_cache.py` | build frames for all featured targets + GIF previews (backend must be running) |
| `.venv/Scripts/python scripts/sync_releases.py [--auto \| --activate ID]` | discover / activate SPHEREx releases |

## Frontend

```bash
cd frontend
npm install
cp .env.example .env.local        # optional; BACKEND_URL defaults to http://localhost:8000
npm run dev                       # http://localhost:3000
npm run build && npm start        # production build
npx tsc --noEmit · npx eslint . · npx vitest run
```

The browser only talks to Next.js; `/api/*` is forwarded to the backend by a rewrite in `next.config.mjs`.

## Quick links (backend + frontend running)

- Barnard's Star: http://localhost:3000/viewer?target=barnards-star&zoom=6
- WISE 0855: http://localhost:3000/viewer?target=wise-0855&band=D6&zoom=6
- Explorer mode: http://localhost:3000/explore?target=r-dra&band=D1

## Docker / deployment

`docker compose up --build` (backend + frontend). Docker, the Supabase CLI and the Vercel CLI were
**not** available while this was built, so these files are untested. See PROJECT_EXPLAINED.md §8.
