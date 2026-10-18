from collections.abc import Callable

import httpx
import pytest

from config import settings
from services.errors import ExternalDataError
from services.http_client import create_http_client, fetch, upstream_details
from tests.helpers import FakeAPI, ok, status

pytestmark = pytest.mark.anyio

URL = "https://api.example.com/data"


def test_http_client_settings() -> None:
    http_client = create_http_client()

    assert http_client.timeout.read == settings.request_timeout
    assert http_client.headers["User-Agent"] == settings.user_agent
    assert http_client.follow_redirects is True


async def test_fetch_success() -> None:
    api = FakeAPI(ok({"answer": 1}))

    response = await fetch(api.client, URL, {"q": "Honolulu"})

    assert response.json() == {"answer": 1}
    assert api.requests[0].url.params["q"] == "Honolulu"


@pytest.mark.parametrize(
    "make_failure",
    [
        lambda: status(429),
        lambda: status(500),
        lambda: status(503),
        lambda: httpx.ConnectError("no network"),
        lambda: httpx.ReadTimeout("slow"),
    ],
)
async def test_fetch_retries_temporary_errors(
    make_failure: Callable[[], httpx.Response | Exception],
) -> None:
    api = FakeAPI(make_failure(), ok({"answer": 1}))

    response = await fetch(api.client, URL)

    assert response.status_code == 200
    assert len(api.requests) == 2


async def test_fetch_gives_up_after_retry_attempts() -> None:
    api = FakeAPI(*[status(503) for _ in range(settings.retry_attempts)])

    with pytest.raises(httpx.HTTPStatusError):
        await fetch(api.client, URL)

    assert len(api.requests) == settings.retry_attempts


@pytest.mark.parametrize("code", [400, 401, 403, 404])
async def test_fetch_does_not_retry_client_errors(code: int) -> None:
    api = FakeAPI(status(code))

    with pytest.raises(httpx.HTTPStatusError):
        await fetch(api.client, URL)

    assert len(api.requests) == 1


async def test_retries_are_logged_without_urls(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = FakeAPI(status(503), ok({}))

    await fetch(api.client, URL, {"key": "secret-key"})

    record = next(r for r in caplog.records if r.message == "Retrying outside API call")
    assert record.__dict__["attempt"] == 1
    assert record.__dict__["error"] == "HTTPStatusError"
    assert "secret-key" not in caplog.text


def test_upstream_details_status_error() -> None:
    request = httpx.Request("GET", "https://api.mapbox.com/search?access_token=secret")
    response = httpx.Response(401, request=request)
    error = httpx.HTTPStatusError("unauthorized", request=request, response=response)

    details = upstream_details(error)

    assert details == {"upstream_service": "api.mapbox.com", "upstream_status": 401}
    assert "secret" not in str(details)


def test_upstream_details_without_request() -> None:
    assert upstream_details(httpx.ConnectError("no network")) == {}


def test_upstream_details_bad_data() -> None:
    error = ExternalDataError("Mapbox response")

    assert upstream_details(error) == {"upstream_service": "Mapbox response"}
