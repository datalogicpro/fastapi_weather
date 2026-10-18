from collections.abc import Callable
from datetime import date
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from config import settings
from schemas.weather import PastWeather
from tests.helpers import (
    CURRENT_METRIC,
    CURRENT_US,
    FORECAST_PERIOD,
    OBSERVATION,
    PERIOD,
    FakeAPI,
    forecast_responses,
    mapbox_response,
    observation_responses,
    ok,
    status,
)

FakeAPIFactory = Callable[..., FakeAPI]

CITY = {"city": "Honolulu", "state": "HI"}

PAST_PARAMS = {
    **CITY,
    "start_date": "2020-07-04",
    "end_date": "2020-07-05",
}


def test_current_weather(client: TestClient, fake_api: FakeAPIFactory) -> None:
    fake_api(mapbox_response(), *observation_responses(OBSERVATION))

    response = client.get("/v1/weather/current", params={**CITY, "units": "metric"})

    assert response.status_code == 200
    assert response.json() == CURRENT_METRIC


def test_default_units_are_us(client: TestClient, fake_api: FakeAPIFactory) -> None:
    fake_api(mapbox_response(), *observation_responses(OBSERVATION))

    response = client.get("/v1/weather/current", params=CITY)

    assert response.status_code == 200
    assert response.json() == CURRENT_US


def test_forecast(client: TestClient, fake_api: FakeAPIFactory) -> None:
    fake_api(mapbox_response(), *forecast_responses([PERIOD]))

    response = client.get("/v1/weather/forecast", params=CITY)

    assert response.status_code == 200
    assert response.json() == {"units": "us", "periods": [FORECAST_PERIOD]}


def test_repeat_requests_use_cache(
    client: TestClient, fake_api: FakeAPIFactory
) -> None:
    api = fake_api(mapbox_response(), *observation_responses(OBSERVATION))

    first = client.get("/v1/weather/current", params=CITY)
    second = client.get(
        "/v1/weather/current", params={"city": "honolulu", "state": "HI"}
    )

    assert first.json() == second.json()
    assert len(api.requests) == 4


def test_repeat_forecast_requests_use_cache(
    client: TestClient, fake_api: FakeAPIFactory
) -> None:
    api = fake_api(mapbox_response(), *forecast_responses([PERIOD]))

    first = client.get("/v1/weather/forecast", params=CITY)
    second = client.get(
        "/v1/weather/forecast", params={"city": "honolulu", "state": "HI"}
    )

    assert first.json() == second.json()
    assert len(api.requests) == 3


def test_repeat_past_weather_requests_use_cache(
    client: TestClient, fake_api: FakeAPIFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_api(mapbox_response())
    calls: list[tuple[Any, ...]] = []

    async def fake_past_weather(*args: Any) -> PastWeather:
        calls.append(args)
        return PastWeather(station="Airport", distance=6, units="us", records=[])

    monkeypatch.setattr("routes.weather.get_past_weather", fake_past_weather)

    first = client.get("/v1/weather/past", params=PAST_PARAMS)
    second = client.get("/v1/weather/past", params=PAST_PARAMS)

    assert first.json() == second.json()
    assert len(calls) == 1


def test_city_not_found(client: TestClient, fake_api: FakeAPIFactory) -> None:
    fake_api(ok({"features": []}))

    response = client.get(
        "/v1/weather/current", params={"city": "NotARealCity", "state": "HI"}
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "City not found in that state"}


@pytest.mark.parametrize("city", ["", "   "])
def test_empty_city(client: TestClient, city: str) -> None:
    response = client.get("/v1/weather/current", params={"city": city, "state": "HI"})

    assert response.status_code == 422


@pytest.mark.parametrize("path", ["/v1/weather/current", "/v1/weather/forecast"])
def test_state_required(client: TestClient, path: str) -> None:
    response = client.get(path, params={"city": "Honolulu"})

    assert response.status_code == 422


def test_state_required_for_past_weather(client: TestClient) -> None:
    params = {key: value for key, value in PAST_PARAMS.items() if key != "state"}

    response = client.get("/v1/weather/past", params=params)

    assert response.status_code == 422


@pytest.mark.parametrize("state", ["XX", "hi", "Hawaii", ""])
def test_invalid_state(client: TestClient, state: str) -> None:
    response = client.get(
        "/v1/weather/current", params={"city": "Honolulu", "state": state}
    )

    assert response.status_code == 422


def test_invalid_units(client: TestClient) -> None:
    response = client.get("/v1/weather/current", params={**CITY, "units": "X"})

    assert response.status_code == 422


def test_no_station_near_city(client: TestClient, fake_api: FakeAPIFactory) -> None:
    fake_api(
        mapbox_response(),
        ok({"properties": {"observationStations": "https://nws.test/stations"}}),
        ok({"features": []}),
    )

    response = client.get("/v1/weather/current", params=CITY)

    assert response.status_code == 404
    assert response.json() == {"detail": "No weather station found near this city"}


@pytest.mark.parametrize("path", ["/v1/weather/current", "/v1/weather/forecast"])
def test_location_nws_does_not_cover(
    client: TestClient, fake_api: FakeAPIFactory, path: str
) -> None:
    fake_api(mapbox_response(), status(404))

    response = client.get(path, params=CITY)

    assert response.status_code == 404


def test_temporary_failure_is_retried(
    client: TestClient, fake_api: FakeAPIFactory
) -> None:
    api = fake_api(status(503), mapbox_response(), *observation_responses(OBSERVATION))

    response = client.get("/v1/weather/current", params=CITY)

    assert response.status_code == 200
    assert len(api.requests) == 5


@pytest.mark.parametrize(
    "make_failure",
    [
        lambda: status(500),
        lambda: httpx.ConnectError("no network"),
        lambda: httpx.ReadTimeout("slow"),
    ],
)
def test_external_failure_returns_502(
    client: TestClient,
    fake_api: FakeAPIFactory,
    make_failure: Callable[[], httpx.Response | Exception],
) -> None:
    fake_api(*[make_failure() for _ in range(settings.retry_attempts)])

    response = client.get("/v1/weather/current", params=CITY)

    assert response.status_code == 502
    assert response.json() == {"detail": "External data service error"}


def test_bad_upstream_data_returns_502(
    client: TestClient, fake_api: FakeAPIFactory
) -> None:
    fake_api(mapbox_response(), ok({}))

    response = client.get("/v1/weather/current", params=CITY)

    assert response.status_code == 502


def test_external_error_is_logged_without_token(
    client: TestClient,
    fake_api: FakeAPIFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_api(status(401))

    client.get("/v1/weather/current", params=CITY)

    assert "HTTPStatusError on /v1/weather/current" in caplog.text
    assert settings.mapbox_token.get_secret_value() not in caplog.text


@pytest.mark.parametrize(
    ("start_date", "end_date"),
    [
        ("2020-07-06", "2020-07-04"),
        ("2999-01-01", "2999-01-02"),
        ("2000-01-01", "2020-01-01"),
    ],
)
def test_past_weather_bad_dates(
    client: TestClient, start_date: str, end_date: str
) -> None:
    response = client.get(
        "/v1/weather/past",
        params={**CITY, "start_date": start_date, "end_date": end_date},
    )

    assert response.status_code == 400


def test_past_weather(
    client: TestClient, fake_api: FakeAPIFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_api(mapbox_response())
    calls = []

    async def fake_past_weather(*args: Any) -> PastWeather:
        calls.append(args[1:])
        return PastWeather(station="Airport", distance=6, units="us", records=[])

    monkeypatch.setattr("routes.weather.get_past_weather", fake_past_weather)

    response = client.get("/v1/weather/past", params=PAST_PARAMS)

    assert response.status_code == 200
    assert response.json()["station"] == "Airport"
    assert calls == [(21.31, -157.86, date(2020, 7, 4), date(2020, 7, 5), "us")]


def test_past_weather_not_found(
    client: TestClient, fake_api: FakeAPIFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_api(mapbox_response())

    async def no_data(*args: Any) -> None:
        return None

    monkeypatch.setattr("routes.weather.get_past_weather", no_data)

    response = client.get(
        "/v1/weather/past",
        params={
            **CITY,
            "start_date": "1890-07-04",
            "end_date": "1890-07-06",
        },
    )

    assert response.status_code == 404


def test_rate_limit(client: TestClient, fake_api: FakeAPIFactory) -> None:
    # Only the first request reaches the fake API; the rest come from the cache
    fake_api(mapbox_response(), *observation_responses(OBSERVATION))
    limit = int(settings.rate_limit.split("/")[0])

    codes = [
        client.get("/v1/weather/current", params=CITY).status_code
        for _ in range(limit + 1)
    ]

    assert codes[:limit] == [200] * limit
    assert codes[-1] == 429


def test_health_is_not_rate_limited(client: TestClient) -> None:
    limit = int(settings.rate_limit.split("/")[0])

    codes = {client.get("/health").status_code for _ in range(limit + 1)}

    assert codes == {200}
