import logging
import time
import tomllib
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from logging_config import setup_logging
from monitoring import setup_sentry
from rate_limit import limiter
from routes.health import router as health_router
from routes.weather import router as weather_router
from services.errors import ExternalDataError
from services.http_client import create_http_client, upstream_details

# The version lives only in pyproject.toml
PYPROJECT = Path(__file__).parent / "pyproject.toml"
VERSION: str = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"][
    "version"
]

setup_logging()
setup_sentry(VERSION)

logger = logging.getLogger(__name__)

# Render calls /health every few seconds, so those requests aren't logged
UNLOGGED_PATHS = {"/health"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # One shared HTTP client for the whole app, closed on shutdown
    async with create_http_client() as client:
        app.state.http_client = client
        yield


app = FastAPI(
    title="Weather Lookup API",
    description="Current weather, 7-day forecasts, and past weather for US cities.",
    version=VERSION,
    contact={"name": "datalogicpro", "url": "https://github.com/datalogicpro"},
    license_info={"name": "MIT", "identifier": "MIT"},
    lifespan=lifespan,
)

app.state.limiter = limiter


@app.middleware("http")
async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    start = time.perf_counter()
    response = await call_next(request)

    if request.url.path not in UNLOGGED_PATHS:
        logger.info(
            "Request handled",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
            },
        )

    return response


# Added last so it runs first, giving every log line its request ID
app.add_middleware(CorrelationIdMiddleware)


@app.exception_handler(httpx.HTTPError)
@app.exception_handler(ExternalDataError)
def handle_external_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "External service failed: %s on %s",
        type(exc).__name__,
        request.url.path,
        extra=upstream_details(exc),
    )
    return JSONResponse(
        status_code=502, content={"detail": "External data service error"}
    )


@app.exception_handler(RateLimitExceeded)
def handle_rate_limit(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=429, content={"detail": "Too many requests, try again later"}
    )


app.include_router(health_router)
app.include_router(weather_router)
