from collections.abc import Callable

import httpx

from schemas.weather import CurrentWeather, Units
from services.errors import ExternalDataError
from services.http_client import fetch

# How many recent readings to check for one with a temperature
RECENT_OBSERVATIONS = 5

# Our field name -> NWS observation field name
FIELDS = {
    "temperature": "temperature",
    "dew_point": "dewpoint",
    "humidity": "relativeHumidity",
    "wind_speed": "windSpeed",
    "wind_direction": "windDirection",
    "wind_gust": "windGust",
    "pressure": "barometricPressure",
    "visibility": "visibility",
    "heat_index": "heatIndex",
    "wind_chill": "windChill",
}


def celsius_to_fahrenheit(celsius: float) -> float:
    return celsius * 9 / 5 + 32


def kmh_to_mph(kmh: float) -> float:
    return kmh / 1.609344


def pascals_to_inhg(pascals: float) -> float:
    return pascals / 3386.389


def pascals_to_hpa(pascals: float) -> float:
    return pascals / 100


def meters_to_miles(meters: float) -> float:
    return meters / 1609.344


def meters_to_km(meters: float) -> float:
    return meters / 1000


# NWS observations are always metric: °C, km/h, Pa, m
CONVERSIONS: dict[Units, dict[str, Callable[[float], float]]] = {
    "us": {
        "temperature": celsius_to_fahrenheit,
        "dew_point": celsius_to_fahrenheit,
        "heat_index": celsius_to_fahrenheit,
        "wind_chill": celsius_to_fahrenheit,
        "wind_speed": kmh_to_mph,
        "wind_gust": kmh_to_mph,
        "pressure": pascals_to_inhg,
        "visibility": meters_to_miles,
    },
    "metric": {
        "pressure": pascals_to_hpa,
        "visibility": meters_to_km,
    },
}


async def get_current_weather(
    client: httpx.AsyncClient, latitude: float, longitude: float, units: Units
) -> CurrentWeather | None:
    try:
        response = await fetch(
            client, f"https://api.weather.gov/points/{latitude},{longitude}"
        )
    except httpx.HTTPStatusError as exc:
        # NWS answers 404 for places it doesn't cover
        if exc.response.status_code == 404:
            return None
        raise

    try:
        stations_url = response.json()["properties"]["observationStations"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ExternalDataError("NWS points response") from exc

    response = await fetch(client, stations_url)

    try:
        stations = response.json()["features"]

        if not stations:
            return None

        station_url = stations[0]["id"]
        station_name = stations[0]["properties"]["name"]
    except (KeyError, TypeError, IndexError, ValueError) as exc:
        raise ExternalDataError("NWS stations response") from exc

    response = await fetch(
        client, f"{station_url}/observations", {"limit": RECENT_OBSERVATIONS}
    )

    try:
        observations = [item["properties"] for item in response.json()["features"]]

        if not observations:
            return None

        # The newest reading is often incomplete, so use the newest with a temperature
        properties = next(
            (
                observation
                for observation in observations
                if (observation.get("temperature") or {}).get("value") is not None
            ),
            observations[0],
        )
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ExternalDataError("NWS observations response") from exc

    conversions = CONVERSIONS[units]

    result: dict[str, float | int | str | None] = {
        "units": units,
        "station": station_name,
        "observed_at": properties.get("timestamp"),
        "conditions": properties.get("textDescription") or None,
    }

    for field, nws_field in FIELDS.items():
        value = (properties.get(nws_field) or {}).get("value")

        if value is not None and field in conversions:
            value = conversions[field](value)

        if value is None:
            result[field] = None
        elif field == "wind_direction":
            result[field] = round(value)
        else:
            result[field] = round(value, 1)

    try:
        return CurrentWeather.model_validate(result)
    except ValueError as exc:
        raise ExternalDataError("NWS observation values") from exc
