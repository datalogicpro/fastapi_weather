import httpx
import pytest

from services.errors import ExternalDataError
from services.forecast_weather import get_forecast
from tests.helpers import (
    FORECAST_PERIOD,
    PERIOD,
    FakeAPI,
    forecast_responses,
    ok,
    status,
)

pytestmark = pytest.mark.anyio


async def test_forecast() -> None:
    api = FakeAPI(*forecast_responses([PERIOD]))

    result = await get_forecast(api.client, 38.58, -121.49, "us")

    assert result is not None
    assert result.model_dump() == {"units": "us", "periods": [FORECAST_PERIOD]}


@pytest.mark.parametrize(("units", "nws_units"), [("us", "us"), ("metric", "si")])
async def test_forecast_asks_nws_for_units(units: str, nws_units: str) -> None:
    api = FakeAPI(*forecast_responses([PERIOD]))

    result = await get_forecast(api.client, 38.58, -121.49, units)  # type: ignore[arg-type]

    assert api.requests[1].url.params["units"] == nws_units
    assert result is not None
    assert result.units == units


async def test_forecast_multiple_periods() -> None:
    tonight = {**PERIOD, "name": "Tonight", "isDaytime": False, "temperature": 78}
    api = FakeAPI(*forecast_responses([PERIOD, tonight]))

    result = await get_forecast(api.client, 38.58, -121.49, "us")

    assert result is not None
    assert [period.name for period in result.periods] == ["Today", "Tonight"]
    assert result.periods[1].temperature == 78


async def test_forecast_null_values() -> None:
    period = {**PERIOD, "temperature": None, "probabilityOfPrecipitation": None}
    api = FakeAPI(*forecast_responses([period]))

    result = await get_forecast(api.client, 38.58, -121.49, "us")

    assert result is not None
    assert result.periods[0].temperature is None
    assert result.periods[0].precipitation_chance is None


async def test_forecast_empty_periods() -> None:
    api = FakeAPI(*forecast_responses([]))

    result = await get_forecast(api.client, 38.58, -121.49, "us")

    assert result is not None
    assert result.periods == []


async def test_forecast_location_not_covered() -> None:
    api = FakeAPI(status(404))

    assert await get_forecast(api.client, 38.58, -121.49, "us") is None


@pytest.mark.parametrize("failing_call", [0, 1])
async def test_forecast_http_error(failing_call: int) -> None:
    responses = forecast_responses([PERIOD])
    responses[failing_call] = status(403)
    api = FakeAPI(*responses)

    with pytest.raises(httpx.HTTPStatusError):
        await get_forecast(api.client, 38.58, -121.49, "us")


@pytest.mark.parametrize(
    "periods_response",
    [
        ok({"properties": {}}),
        ok({"properties": {"periods": [{"name": "Today"}]}}),
        ok({"properties": {"periods": [{**PERIOD, "windSpeed": None}]}}),
    ],
)
async def test_forecast_bad_data(periods_response: httpx.Response) -> None:
    api = FakeAPI(
        ok({"properties": {"forecast": "https://nws.test/forecast"}}),
        periods_response,
    )

    with pytest.raises(ExternalDataError):
        await get_forecast(api.client, 38.58, -121.49, "us")


async def test_forecast_bad_points_data() -> None:
    api = FakeAPI(ok({}))

    with pytest.raises(ExternalDataError):
        await get_forecast(api.client, 38.58, -121.49, "us")
