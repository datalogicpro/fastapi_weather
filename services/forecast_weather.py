import httpx

from schemas.weather import Forecast, ForecastPeriod, Units
from services.errors import ExternalDataError
from services.http_client import fetch

# The NWS forecast calls metric units "si"
NWS_UNITS = {"us": "us", "metric": "si"}


async def get_forecast(
    client: httpx.AsyncClient, latitude: float, longitude: float, units: Units
) -> Forecast | None:
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
        forecast_url = response.json()["properties"]["forecast"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ExternalDataError("NWS points response") from exc

    response = await fetch(client, forecast_url, {"units": NWS_UNITS[units]})

    periods = []

    try:
        for period in response.json()["properties"]["periods"]:
            precipitation = period.get("probabilityOfPrecipitation") or {}

            periods.append(
                ForecastPeriod(
                    name=period["name"],
                    start_time=period["startTime"],
                    is_daytime=period["isDaytime"],
                    temperature=period["temperature"],
                    precipitation_chance=precipitation.get("value"),
                    wind_speed=period["windSpeed"],
                    wind_direction=period["windDirection"],
                    conditions=period["shortForecast"],
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExternalDataError("NWS forecast response") from exc

    return Forecast(units=units, periods=periods)
