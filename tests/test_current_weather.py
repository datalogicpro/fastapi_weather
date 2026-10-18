import httpx
import pytest

from config import settings
from services.current_weather import get_current_weather
from services.errors import ExternalDataError
from tests.helpers import (
    CURRENT_METRIC,
    CURRENT_US,
    OBSERVATION,
    FakeAPI,
    observation_responses,
    ok,
    status,
)

pytestmark = pytest.mark.anyio


async def test_current_weather_us() -> None:
    api = FakeAPI(*observation_responses(OBSERVATION))

    result = await get_current_weather(api.client, 38.58, -121.49, "us")

    assert result is not None
    assert result.model_dump() == CURRENT_US


async def test_current_weather_metric() -> None:
    api = FakeAPI(*observation_responses(OBSERVATION))

    result = await get_current_weather(api.client, 38.58, -121.49, "metric")

    assert result is not None
    assert result.model_dump() == CURRENT_METRIC


@pytest.mark.parametrize(("celsius", "fahrenheit"), [(0, 32.0), (-10, 14.0)])
async def test_current_weather_converts_temperature(
    celsius: float, fahrenheit: float
) -> None:
    api = FakeAPI(*observation_responses({"temperature": {"value": celsius}}))

    result = await get_current_weather(api.client, 38.58, -121.49, "us")

    assert result is not None
    assert result.temperature == fahrenheit


async def test_current_weather_missing_fields() -> None:
    api = FakeAPI(*observation_responses({"temperature": {"value": None}}))

    result = await get_current_weather(api.client, 38.58, -121.49, "us")

    assert result is not None
    assert result.temperature is None
    assert result.conditions is None
    assert result.wind_speed is None


async def test_current_weather_wind_direction_is_whole_number() -> None:
    api = FakeAPI(*observation_responses({"windDirection": {"value": 92.6}}))

    result = await get_current_weather(api.client, 38.58, -121.49, "us")

    assert result is not None
    assert result.wind_direction == 93


async def test_current_weather_no_stations() -> None:
    api = FakeAPI(
        ok({"properties": {"observationStations": "https://nws.test/stations"}}),
        ok({"features": []}),
    )

    assert await get_current_weather(api.client, 38.58, -121.49, "us") is None


async def test_current_weather_location_not_covered() -> None:
    api = FakeAPI(status(404))

    assert await get_current_weather(api.client, 38.58, -121.49, "us") is None


@pytest.mark.parametrize("failing_call", [0, 1, 2])
async def test_current_weather_http_error(failing_call: int) -> None:
    responses = observation_responses(OBSERVATION)
    responses[failing_call] = status(403)
    api = FakeAPI(*responses)

    with pytest.raises(httpx.HTTPStatusError):
        await get_current_weather(api.client, 38.58, -121.49, "us")


async def test_current_weather_network_error() -> None:
    api = FakeAPI(
        *[httpx.ConnectError("no network") for _ in range(settings.retry_attempts)]
    )

    with pytest.raises(httpx.ConnectError):
        await get_current_weather(api.client, 38.58, -121.49, "us")


@pytest.mark.parametrize(
    "bad_response",
    [ok({}), ok([]), httpx.Response(200, text="not json")],
)
async def test_current_weather_bad_data(bad_response: httpx.Response) -> None:
    api = FakeAPI(bad_response)

    with pytest.raises(ExternalDataError):
        await get_current_weather(api.client, 38.58, -121.49, "us")


async def test_current_weather_bad_stations_data() -> None:
    responses = observation_responses(OBSERVATION)
    responses[1] = ok({"features": [{"id": "https://nws.test/PHNL"}]})
    api = FakeAPI(*responses)

    with pytest.raises(ExternalDataError):
        await get_current_weather(api.client, 38.58, -121.49, "us")


async def test_current_weather_bad_observations_data() -> None:
    responses = observation_responses(OBSERVATION)
    responses[2] = ok({})
    api = FakeAPI(*responses)

    with pytest.raises(ExternalDataError):
        await get_current_weather(api.client, 38.58, -121.49, "us")


async def test_current_weather_bad_value_type() -> None:
    api = FakeAPI(*observation_responses({"textDescription": {"not": "text"}}))

    with pytest.raises(ExternalDataError):
        await get_current_weather(api.client, 38.58, -121.49, "us")


async def test_current_weather_skips_reading_without_temperature() -> None:
    incomplete = {**OBSERVATION, "temperature": {"value": None}}
    responses = observation_responses(OBSERVATION)
    responses[2] = ok(
        {"features": [{"properties": incomplete}, {"properties": OBSERVATION}]}
    )
    api = FakeAPI(*responses)

    result = await get_current_weather(api.client, 38.58, -121.49, "us")

    assert result is not None
    assert result.model_dump() == CURRENT_US
    assert api.requests[2].url.params["limit"] == "5"


async def test_current_weather_no_observations() -> None:
    responses = observation_responses(OBSERVATION)
    responses[2] = ok({"features": []})
    api = FakeAPI(*responses)

    assert await get_current_weather(api.client, 38.58, -121.49, "us") is None
