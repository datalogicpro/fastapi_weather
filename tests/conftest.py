from collections.abc import Callable, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from config import settings
from main import app
from rate_limit import limiter
from routes.weather import current_cache, forecast_cache, past_cache
from services.geocoding import coordinates_cache
from services.http_client import get_http_client
from tests.helpers import FakeAPI


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def reset_state() -> Iterator[None]:
    for cache in (coordinates_cache, current_cache, forecast_cache, past_cache):
        cache.clear()

    limiter.reset()

    yield

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    # Retries happen right away in tests, so the test run stays fast
    monkeypatch.setattr(settings, "retry_backoff", 0)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def fake_api() -> Callable[..., FakeAPI]:
    """Makes the app's routes use a FakeAPI instead of the real internet."""

    def install(*responses: httpx.Response | Exception) -> FakeAPI:
        api = FakeAPI(*responses)
        app.dependency_overrides[get_http_client] = lambda: api.client
        return api

    return install
