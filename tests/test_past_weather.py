from datetime import date
from types import SimpleNamespace
from typing import Any

import httpx
import meteostat as ms
import pandas as pd
import pytest
import requests

from schemas.weather import PastWeather, Units
from services.errors import ExternalDataError
from services.past_weather import get_noaa_records, get_past_weather, split_noaa_name
from tests.helpers import FakeAPI, make_stations, mock_meteostat, ok, status

pytestmark = pytest.mark.anyio

NOAA_ROW = {"DATE": "1890-07-04", "TMAX": "88", "TMIN": "46", "PRCP": "0.00"}

# Downtown Los Angeles
LATITUDE = 34.05
LONGITUDE = -118.24

OLD_DATE = date(1890, 7, 4)

NEW_DATE = date(1931, 1, 1)

NEW_ROW = {"DATE": "1931-01-01", "TMAX": "60", "TMIN": "50", "PRCP": "0.98"}


def search_result(
    station_id: str, name: str, latitude: float, longitude: float
) -> dict[str, Any]:
    """One station from NOAA's search service. NOAA puts longitude first."""
    return {
        "location": {"coordinates": [longitude, latitude]},
        "stations": [{"id": station_id, "name": name}],
    }


# 111 miles from Downtown Los Angeles
SAN_DIEGO = search_result(
    "USC00047738", "SAN DIEGO WEATHER BUREAU OFFICE, CA US", 32.71667, -117.16667
)

# 215 miles from Downtown Los Angeles
NEEDLES = search_result("USC00046115", "NEEDLES, CA US", 34.83, -114.5936)

# 3 miles from Downtown Los Angeles
DOWNTOWN = search_result(
    "USW00093134", "LOS ANGELES DOWNTOWN USC, CA US", 34.0236, -118.2911
)

# Inside the search box corner, but 691 km away, past the search radius
FAR_AWAY = search_result("USC00420000", "FAR AWAY, UT US", 38.5, -112.85)


async def old_weather(api: FakeAPI, units: Units = "us") -> PastWeather | None:
    return await get_past_weather(
        api.client, LATITUDE, LONGITUDE, OLD_DATE, OLD_DATE, units
    )


def mock_meteostat_station(
    monkeypatch: pytest.MonkeyPatch, name: str, distance_meters: float
) -> None:
    """One Meteostat station with a record for NEW_DATE."""
    df = pd.DataFrame(
        {"tmax": [62.1]}, index=pd.DatetimeIndex(["1931-01-01"], name="time")
    )
    mock_meteostat(monkeypatch, df)
    monkeypatch.setattr(
        ms.stations,
        "nearby",
        lambda point, **kwargs: make_stations(("11111", name, "CA", distance_meters)),
    )


async def new_weather(api: FakeAPI) -> PastWeather | None:
    return await get_past_weather(
        api.client, LATITUDE, LONGITUDE, NEW_DATE, NEW_DATE, "us"
    )


async def test_noaa_records() -> None:
    api = FakeAPI(ok([NOAA_ROW]))

    result = await get_noaa_records(
        api.client, "USW00024128", date(1890, 7, 4), date(1890, 7, 4), "us"
    )

    assert api.requests[0].url.params["units"] == "standard"
    assert [record.model_dump(exclude_none=True) for record in result] == [
        {
            "date": "1890-07-04",
            "temperature_max": 88.0,
            "temperature_min": 46.0,
            "precipitation": 0.0,
        }
    ]


async def test_noaa_records_metric_snow_in_cm() -> None:
    api = FakeAPI(ok([{"DATE": "1890-01-04", "SNOW": "25", "SNWD": "50"}]))

    result = await get_noaa_records(
        api.client, "USW00024128", date(1890, 1, 4), date(1890, 1, 4), "metric"
    )

    assert result[0].snowfall == 2.5
    assert result[0].snow_depth == 5.0


async def test_noaa_records_http_error() -> None:
    api = FakeAPI(status(403))

    with pytest.raises(httpx.HTTPStatusError):
        await get_noaa_records(
            api.client, "USW00024128", date(1890, 7, 4), date(1890, 7, 4), "us"
        )


async def test_noaa_records_bad_data() -> None:
    api = FakeAPI(ok([{"DATE": "1890-07-04", "TMAX": "hot"}]))

    with pytest.raises(ExternalDataError):
        await get_noaa_records(
            api.client, "USW00024128", date(1890, 7, 4), date(1890, 7, 4), "us"
        )


async def test_past_weather_old_uses_closest_noaa_station() -> None:
    # NOAA does not sort its results by distance
    api = FakeAPI(ok({"results": [NEEDLES, SAN_DIEGO]}), ok([NOAA_ROW]))

    result = await old_weather(api)

    search_params = api.requests[0].url.params
    assert search_params["bbox"] == "38.5416,-123.6610,29.5584,-112.8190"
    assert search_params["dataTypes"] == "TMAX"
    assert search_params["startDate"] == "1890-07-04"
    assert api.requests[1].url.params["stations"] == "USC00047738"

    assert result is not None
    assert result.station == "San Diego Weather Bureau Office"
    assert result.distance == 111
    assert result.records[0].temperature_max == 88.0
    assert result.note == (
        "No nearby station has records for these dates. "
        "Closest with records: San Diego Weather Bureau Office, CA (111 miles away)."
    )


async def test_past_weather_old_metric_distance() -> None:
    api = FakeAPI(ok({"results": [SAN_DIEGO]}), ok([NOAA_ROW]))

    result = await old_weather(api, "metric")

    assert result is not None
    assert result.distance == 179
    assert result.note == (
        "No nearby station has records for these dates. "
        "Closest with records: San Diego Weather Bureau Office, CA (179 km away)."
    )


async def test_past_weather_old_skips_station_without_records() -> None:
    api = FakeAPI(ok({"results": [SAN_DIEGO, NEEDLES]}), ok([]), ok([NOAA_ROW]))

    result = await old_weather(api)

    assert api.requests[2].url.params["stations"] == "USC00046115"
    assert result is not None
    assert result.station == "Needles"
    assert result.distance == 215


async def test_past_weather_old_skips_station_without_temperature() -> None:
    rain_only = {"DATE": "1890-07-04", "PRCP": "0.00"}
    api = FakeAPI(
        ok({"results": [SAN_DIEGO, NEEDLES]}), ok([rain_only]), ok([NOAA_ROW])
    )

    result = await old_weather(api)

    assert api.requests[2].url.params["stations"] == "USC00046115"
    assert result is not None
    assert result.station == "Needles"
    assert result.records[0].temperature_max == 88.0


async def test_past_weather_old_ignores_stations_past_radius() -> None:
    api = FakeAPI(ok({"results": [FAR_AWAY]}))

    result = await old_weather(api)

    assert result is None
    assert len(api.requests) == 1


async def test_past_weather_old_no_stations() -> None:
    api = FakeAPI(ok({"results": []}))

    assert await old_weather(api) is None


async def test_past_weather_old_bad_search_data() -> None:
    api = FakeAPI(ok({"results": [{"stations": []}]}))

    with pytest.raises(ExternalDataError):
        await old_weather(api)


def test_split_noaa_name() -> None:
    assert split_noaa_name("NEEDLES, CA US") == ("Needles", "CA")
    assert split_noaa_name("NEEDLES") == ("Needles", "")


async def test_past_weather_recent_uses_meteostat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    df = pd.DataFrame(
        {"tmax": [86.0], "prcp": [0.358], "pres": [1015.0], "cldc": [4.0]},
        index=pd.DatetimeIndex(["2020-07-04"], name="time"),
    )
    fetch_calls: list[Any] = []
    mock_meteostat(monkeypatch, df, fetch_calls)

    api = FakeAPI(ok({"results": []}))

    result = await get_past_weather(
        api.client, 21.31, -157.86, date(2020, 7, 4), date(2020, 7, 4), "us"
    )

    assert fetch_calls == [ms.UnitSystem.IMPERIAL]
    assert result is not None
    assert result.model_dump(exclude_none=True) == {
        "station": "Honolulu",
        "distance": 3,
        "units": "us",
        "records": [
            {
                "date": "2020-07-04",
                "temperature_max": 86.0,
                "precipitation": 0.358,
                "pressure": 29.97,
                "cloud_cover": 50,
            }
        ],
    }


async def test_past_weather_metric_keeps_hpa(monkeypatch: pytest.MonkeyPatch) -> None:
    df = pd.DataFrame(
        {"tmax": [30.0], "pres": [1015.0]},
        index=pd.DatetimeIndex(["2020-07-04"], name="time"),
    )
    fetch_calls: list[Any] = []
    mock_meteostat(monkeypatch, df, fetch_calls)

    api = FakeAPI(ok({"results": []}))

    result = await get_past_weather(
        api.client, 21.31, -157.86, date(2020, 7, 4), date(2020, 7, 4), "metric"
    )

    assert fetch_calls == [ms.UnitSystem.METRIC]
    assert result is not None
    assert result.distance == 5
    assert result.records[0].temperature_max == 30.0
    assert result.records[0].pressure == 1015.0


async def test_past_weather_no_meteostat_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_meteostat(monkeypatch, pd.DataFrame())

    api = FakeAPI(ok({"results": []}))

    result = await get_past_weather(
        api.client, 21.31, -157.86, date(2020, 7, 4), date(2020, 7, 4), "us"
    )

    assert result is None


async def test_past_weather_skips_station_that_starts_later(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetched: list[str] = []
    monkeypatch.setattr(
        ms.stations,
        "nearby",
        lambda point, **kwargs: make_stations(("11111", "Newer", "HI", 5000)),
    )
    monkeypatch.setattr(
        ms.stations,
        "inventory",
        lambda station_id: SimpleNamespace(start=date(2021, 1, 1), end=None),
    )
    monkeypatch.setattr(
        ms, "daily", lambda station_id, start, end: fetched.append(station_id)
    )

    api = FakeAPI(ok({"results": []}))

    result = await get_past_weather(
        api.client, 21.31, -157.86, date(2020, 7, 4), date(2020, 7, 4), "us"
    )

    assert result is None
    assert fetched == []


async def test_past_weather_skips_station_whose_records_ended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetched: list[str] = []
    monkeypatch.setattr(
        ms.stations,
        "nearby",
        lambda point, **kwargs: make_stations(("11111", "Closed", "HI", 5000)),
    )
    monkeypatch.setattr(
        ms.stations,
        "inventory",
        lambda station_id: SimpleNamespace(
            start=date(1950, 1, 1), end=date(1990, 12, 31)
        ),
    )
    monkeypatch.setattr(
        ms, "daily", lambda station_id, start, end: fetched.append(station_id)
    )

    api = FakeAPI(ok({"results": []}))

    result = await get_past_weather(
        api.client, 21.31, -157.86, date(2020, 7, 4), date(2020, 7, 4), "us"
    )

    assert result is None
    assert fetched == []


async def test_past_weather_meteostat_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(point: Any, **kwargs: Any) -> None:
        raise requests.ConnectionError("no network")

    monkeypatch.setattr(ms.stations, "nearby", fail)

    api = FakeAPI(ok({"results": []}))

    with pytest.raises(ExternalDataError):
        await get_past_weather(
            api.client, 21.31, -157.86, date(2020, 7, 4), date(2020, 7, 4), "us"
        )


async def test_past_weather_far_meteostat_uses_closer_noaa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_meteostat_station(monkeypatch, "Salinas", 420_000)
    api = FakeAPI(ok({"results": [DOWNTOWN]}), ok([NEW_ROW]))

    result = await new_weather(api)

    assert api.requests[0].url.params["startDate"] == "1931-01-01"
    assert result is not None
    assert result.station == "Los Angeles Downtown Usc"
    assert result.distance == 3
    assert result.records[0].temperature_max == 60.0
    assert result.note is None


async def test_past_weather_near_meteostat_loses_to_closer_noaa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_meteostat_station(monkeypatch, "Long Beach Airport", 27_000)
    api = FakeAPI(ok({"results": [DOWNTOWN]}), ok([NEW_ROW]))

    result = await new_weather(api)

    assert result is not None
    assert result.station == "Los Angeles Downtown Usc"


async def test_past_weather_same_station_keeps_meteostat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Both sources list Downtown Los Angeles, NOAA's copy 51 meters closer
    mock_meteostat_station(monkeypatch, "Los Angeles / Jefferson", 5_600)
    api = FakeAPI(ok({"results": [DOWNTOWN]}), ok([NEW_ROW]))

    result = await new_weather(api)

    assert result is not None
    assert result.station == "Los Angeles / Jefferson"


async def test_past_weather_meteostat_kept_when_closer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_meteostat_station(monkeypatch, "Riverside", 100_000)
    api = FakeAPI(ok({"results": [NEEDLES]}), ok([NEW_ROW]))

    result = await new_weather(api)

    assert result is not None
    assert result.station == "Riverside"
    assert result.distance == 62


async def test_past_weather_meteostat_kept_without_noaa_station(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_meteostat_station(monkeypatch, "Salinas", 420_000)
    api = FakeAPI(ok({"results": []}))

    result = await new_weather(api)

    assert result is not None
    assert result.station == "Salinas"


async def test_past_weather_no_meteostat_station_uses_noaa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_meteostat(monkeypatch, pd.DataFrame())
    api = FakeAPI(ok({"results": [DOWNTOWN]}), ok([NEW_ROW]))

    result = await new_weather(api)

    assert result is not None
    assert result.station == "Los Angeles Downtown Usc"


async def test_past_weather_noaa_error_keeps_meteostat(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    mock_meteostat_station(monkeypatch, "Salinas", 420_000)
    api = FakeAPI(status(403))

    result = await new_weather(api)

    assert result is not None
    assert result.station == "Salinas"
    record = next(
        r for r in caplog.records if r.message == "Past weather source failed"
    )
    assert record.__dict__["source"] == "NOAA"
    assert record.__dict__["error"] == "HTTPStatusError"


async def test_past_weather_meteostat_error_keeps_noaa(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fail(point: Any, **kwargs: Any) -> None:
        raise requests.ConnectionError("no network")

    monkeypatch.setattr(ms.stations, "nearby", fail)
    api = FakeAPI(ok({"results": [DOWNTOWN]}), ok([NEW_ROW]))

    result = await new_weather(api)

    assert result is not None
    assert result.station == "Los Angeles Downtown Usc"
    record = next(
        r for r in caplog.records if r.message == "Past weather source failed"
    )
    assert record.__dict__["source"] == "Meteostat"
    assert record.__dict__["error"] == "ExternalDataError"


async def test_past_weather_noaa_error_without_meteostat_station(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_meteostat(monkeypatch, pd.DataFrame())
    api = FakeAPI(status(403))

    with pytest.raises(httpx.HTTPStatusError):
        await new_weather(api)
