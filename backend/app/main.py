"""FastAPI application entry point: `uvicorn app.main:app`."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from astropy.utils.data import conf as astropy_conf
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.routes import core, jobs, overlays, photometry
from app.core.config import get_settings
from app.core.errors import NotFoundError, UpstreamUnavailable, not_found_handler, upstream_handler
from app.core.logging import setup_logging
from app.core.ratelimit import limiter
from app.services.cache import get_cache

settings = get_settings()
setup_logging(settings.log_level)
log = logging.getLogger("app")
astropy_conf.remote_timeout = settings.cutout_timeout_s


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    cache = get_cache()
    log.info("Nexus Viewer API starting (cache=%s, fetch=%s via %s)", cache.name,
             settings.fetch_strategy, settings.range_source)
    yield
    from app.workers.job_runner import _fetcher

    if _fetcher is not None:
        await _fetcher.aclose()


app = FastAPI(title="Nexus Viewer API", version="0.1.0", lifespan=lifespan,
              description="SPHEREx time-domain sky viewer backend (NASA Space Apps 2026).")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_exception_handler(UpstreamUnavailable, upstream_handler)
app.add_exception_handler(NotFoundError, not_found_handler)
app.add_middleware(GZipMiddleware, minimum_size=2048)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["*"], allow_headers=["*"],
    expose_headers=["X-Width", "X-Height", "X-Channels"],
)

for r in (core.router, jobs.router, photometry.router, overlays.router):
    app.include_router(r, prefix="/api")
