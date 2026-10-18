import logging
from collections.abc import Mapping

import httpx
from fastapi import Request
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from config import settings
from services.errors import ExternalDataError

logger = logging.getLogger(__name__)

# Status codes that usually mean a short outage, worth trying again
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


def create_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=settings.request_timeout,
        headers={"User-Agent": settings.user_agent},
        follow_redirects=True,
    )


def get_http_client(request: Request) -> httpx.AsyncClient:
    client: httpx.AsyncClient = request.app.state.http_client
    return client


def is_temporary_error(error: BaseException) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in RETRY_STATUS_CODES

    return isinstance(error, httpx.TransportError)


def log_retry(retry_state: RetryCallState) -> None:
    # Only the error type is logged, because httpx error messages contain URLs
    error = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        "Retrying outside API call",
        extra={"attempt": retry_state.attempt_number, "error": type(error).__name__},
    )


async def fetch(
    client: httpx.AsyncClient,
    url: str,
    params: Mapping[str, str | int] | None = None,
) -> httpx.Response:
    """GETs a URL, trying again with exponential backoff on temporary errors."""
    retrying = AsyncRetrying(
        stop=stop_after_attempt(settings.retry_attempts),
        wait=wait_exponential_jitter(
            multiplier=settings.retry_backoff, max=5, jitter=settings.retry_backoff
        ),
        retry=retry_if_exception(is_temporary_error),
        before_sleep=log_retry,
        reraise=True,
    )

    async for attempt in retrying:
        with attempt:
            response = await client.get(url, params=params)
            response.raise_for_status()

    return response


def upstream_details(error: Exception) -> dict[str, str | int]:
    """Which outside service failed, and its status code, for the logs.

    Only the host name is used, never the full URL, because Mapbox URLs contain
    the token.
    """
    if isinstance(error, ExternalDataError):
        return {"upstream_service": str(error)}

    details: dict[str, str | int] = {}

    if isinstance(error, httpx.HTTPStatusError):
        details["upstream_status"] = error.response.status_code

    if isinstance(error, httpx.HTTPError):
        try:
            details["upstream_service"] = error.request.url.host
        except RuntimeError:
            # httpx raises this when the error was created without a request
            pass

    return details
