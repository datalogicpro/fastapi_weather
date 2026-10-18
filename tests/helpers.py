"""Fake HTTP responses and sample data shared by the tests."""

from datetime import date
from types import SimpleNamespace
from typing import Any

import httpx
import meteostat as ms
import pandas as pd
import pytest


class FakeAPI:
    """Answers HTTP requests with canned responses, in order, and records them."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses.pop(0)

        if isinstance(response, Exception):
            raise response

        return response


def ok(data: Any) -> httpx.Response:
    return httpx.Response(200, json=data)


def status(code: int) -> httpx.Response:
    return httpx.Response(code)


def mapbox_feature(
    name: str = "Honolulu",
    state: str = "HI",
    coordinates: tuple[float, float] = (-157.86, 21.31),
) -> dict[str, Any]:
    """One place from Mapbox. Mapbox puts longitude first."""
    return {
        "geometry": {"coordinates": list(coordinates)},
        "properties": {"name": name, "context": {"region": {"region_code": state}}},
    }


def mapbox_response(*features: dict[str, Any]) -> httpx.Response:
    return ok({"features": list(features) or [mapbox_feature()]})


def observation_responses(properties: dict[str, Any]) -> list[httpx.Response]:
    return [
        ok({"properties": {"observationStations": "https://nws.test/stations"}}),
        ok(
            {
                "features": [
                    {"id": "https://nws.test/PHNL", "properties": {"name": "Airport"}}
                ]
            }
        ),
        ok({"features": [{"properties": properties}]}),
    ]


def forecast_responses(periods: list[dict[str, Any]]) -> list[httpx.Response]:
    return [
        ok({"properties": {"forecast": "https://nws.test/forecast"}}),
        ok({"properties": {"periods": periods}}),
    ]


# NWS observations are always metric: °C, km/h, Pa, m
OBSERVATION = {
    "timestamp": "2026-10-09T17:53:00+00:00",
    "textDescription": "Clear",
    "temperature": {"value": 20},
    "dewpoint": {"value": 10},
    "relativeHumidity": {"value": 52.5},
    "windSpeed": {"value": 16.09344},
    "windDirection": {"value": 90},
    "windGust": {"value": None},
    "barometricPressure": {"value": 101592},
    "visibility": {"value": 16093.44},
    "heatIndex": {"value": None},
    "windChill": {"value": None},
}

CURRENT_US = {
    "units": "us",
    "station": "Airport",
    "observed_at": "2026-10-09T17:53:00+00:00",
    "conditions": "Clear",
    "temperature": 68.0,
    "dew_point": 50.0,
    "humidity": 52.5,
    "wind_speed": 10.0,
    "wind_direction": 90,
    "wind_gust": None,
    "pressure": 30.0,
    "visibility": 10.0,
    "heat_index": None,
    "wind_chill": None,
}

CURRENT_METRIC = {
    **CURRENT_US,
    "units": "metric",
    "temperature": 20.0,
    "dew_point": 10.0,
    "wind_speed": 16.1,
    "pressure": 1015.9,
    "visibility": 16.1,
}

PERIOD = {
    "name": "Today",
    "startTime": "2026-10-09T08:00:00-10:00",
    "isDaytime": True,
    "temperature": 88,
    "probabilityOfPrecipitation": {"value": 38},
    "windSpeed": "7 to 13 mph",
    "windDirection": "SSE",
    "shortForecast": "Scattered Rain Showers",
    "detailedForecast": "Scattered rain showers. Partly sunny, with a high near 88.",
}

FORECAST_PERIOD = {
    "name": "Today",
    "start_time": "2026-10-09T08:00:00-10:00",
    "is_daytime": True,
    "temperature": 88,
    "precipitation_chance": 38,
    "wind_speed": "7 to 13 mph",
    "wind_direction": "SSE",
    "conditions": "Scattered Rain Showers",
}


def make_stations(*rows: tuple[str, str, str, float]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["id", "name", "region", "distance"]).set_index(
        "id"
    )


def mock_meteostat(
    monkeypatch: pytest.MonkeyPatch,
    df: pd.DataFrame,
    fetch_calls: list[Any] | None = None,
) -> None:
    def fetch(units: Any) -> pd.DataFrame:
        if fetch_calls is not None:
            fetch_calls.append(units)
        return df

    monkeypatch.setattr(
        ms.stations,
        "nearby",
        lambda point, **kwargs: make_stations(("91182", "Honolulu", "HI", 5000)),
    )
    monkeypatch.setattr(
        ms.stations,
        "inventory",
        lambda station_id: SimpleNamespace(start=date(1900, 1, 1), end=None),
    )
    monkeypatch.setattr(
        ms, "daily", lambda station_id, start, end: SimpleNamespace(fetch=fetch)
    )
