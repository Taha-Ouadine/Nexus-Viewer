from fastapi import Request
from fastapi.responses import JSONResponse


class UpstreamUnavailable(Exception):
    """An external archive (IRSA, Gaia, CDS) could not be reached."""

    def __init__(self, service: str, detail: str = "") -> None:
        super().__init__(f"{service} unavailable: {detail}")
        self.service = service
        self.detail = detail


class NotFoundError(Exception):
    pass


async def upstream_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, UpstreamUnavailable)
    return JSONResponse(
        status_code=503,
        content={
            "detail": f"The {exc.service} service is not responding right now. "
            "Please try again in a minute.",
            "service": exc.service,
        },
    )


async def not_found_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})
