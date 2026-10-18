from datetime import date
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from config import settings
from rate_limit import limiter
from schemas.weather import (
    CurrentWeather,
    ErrorResponse,
    Forecast,
    PastWeather,
    StateCode,
    Units,
)
from services.cache import TTLCache
from services.current_weather import get_current_weather
from services.forecast_weather import get_forecast
from services.geocoding import get_coordinates, normalize
from services.http_client import get_http_client
from services.past_weather import get_past_weather

router = APIRouter(prefix="/v1/weather", tags=["weather"])

City = Annotated[
    str,
    Query(
        min_length=1,
        max_length=100,
        pattern=r"\S",
        description="US city name",
        examples=["Honolulu"],
    ),
]
State = Annotated[
    StateCode,
    Query(description="Two-letter US state code, in capitals", examples=["HI"]),
]
UnitSystem = Annotated[
    Units,
    Query(description="`us` for °F, inches, mph, or `metric` for °C, mm, km/h"),
]
HttpClient = Annotated[httpx.AsyncClient, Depends(get_http_client)]

MAX_RANGE_DAYS = 366

# Weather changes slowly, so recent answers are reused for a short time
current_cache: TTLCache[CurrentWeather] = TTLCache(ttl_seconds=10 * 60)
forecast_cache: TTLCache[Forecast] = TTLCache(ttl_seconds=30 * 60)
past_cache: TTLCache[PastWeather] = TTLCache(ttl_seconds=24 * 60 * 60)


def error(description: str) -> dict[str, Any]:
    return {"model": ErrorResponse, "description": description}


COMMON_ERRORS: dict[int | str, dict[str, Any]] = {
    404: error("City not found in that state, or no weather station or data"),
    429: error("Too many requests"),
    502: error("An external data service failed"),
}


async def find_coordinates(
    client: httpx.AsyncClient, city: str, state: StateCode
) -> tuple[float, float]:
    coordinates = await get_coordinates(client, city, state)

    if coordinates is None:
        raise HTTPException(status_code=404, detail="City not found in that state")

    longitude, latitude = coordinates

    return latitude, longitude


@router.get("/current", summary="Current weather", responses=COMMON_ERRORS)
@limiter.limit(settings.rate_limit)
async def current_weather(
    request: Request,
    city: City,
    state: State,
    client: HttpClient,
    units: UnitSystem = "us",
) -> CurrentWeather:
    """Latest reading from the National Weather Service station nearest the city."""
    key = (normalize(city), state, units)

    if (cached := current_cache.get(key)) is not None:
        return cached

    latitude, longitude = await find_coordinates(client, city, state)

    result = await get_current_weather(client, latitude, longitude, units)

    if result is None:
        raise HTTPException(
            status_code=404, detail="No weather station found near this city"
        )

    current_cache.set(key, result)

    return result


@router.get("/forecast", summary="7-day forecast", responses=COMMON_ERRORS)
@limiter.limit(settings.rate_limit)
async def forecast(
    request: Request,
    city: City,
    state: State,
    client: HttpClient,
    units: UnitSystem = "us",
) -> Forecast:
    """Day and night forecast periods from the National Weather Service."""
    key = (normalize(city), state, units)

    if (cached := forecast_cache.get(key)) is not None:
        return cached

    latitude, longitude = await find_coordinates(client, city, state)

    result = await get_forecast(client, latitude, longitude, units)

    if result is None:
        raise HTTPException(
            status_code=404, detail="No forecast available for this city"
        )

    forecast_cache.set(key, result)

    return result


@router.get(
    "/past",
    summary="Past daily weather",
    responses={400: error("Invalid date range"), **COMMON_ERRORS},
)
@limiter.limit(settings.rate_limit)
async def past_weather(
    request: Request,
    city: City,
    state: State,
    client: HttpClient,
    start_date: Annotated[date, Query(description="First day, YYYY-MM-DD")],
    end_date: Annotated[date, Query(description="Last day, YYYY-MM-DD")],
    units: UnitSystem = "us",
) -> PastWeather:
    """Daily records from the closest station that has data for the dates.

    Uses NOAA before 1931. From 1931 on, uses the closer station from Meteostat
    or NOAA.
    """
    if start_date > end_date:
        raise HTTPException(
            status_code=400, detail="start_date must be on or before end_date"
        )

    if end_date > date.today():
        raise HTTPException(status_code=400, detail="end_date can't be in the future")

    if (end_date - start_date).days >= MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"Date range can be at most {MAX_RANGE_DAYS} days",
        )

    key = (normalize(city), state, start_date, end_date, units)

    if (cached := past_cache.get(key)) is not None:
        return cached

    latitude, longitude = await find_coordinates(client, city, state)

    result = await get_past_weather(
        client, latitude, longitude, start_date, end_date, units
    )

    if result is None:
        raise HTTPException(
            status_code=404, detail="No station has data for those dates"
        )

    past_cache.set(key, result)

    return result
