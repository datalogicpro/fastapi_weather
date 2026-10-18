from typing import Any

import httpx

from config import settings
from schemas.weather import StateCode
from services.cache import TTLCache
from services.errors import ExternalDataError
from services.http_client import fetch

MAPBOX_URL = "https://api.mapbox.com/search/geocode/v6/forward"

# A city's coordinates don't change, so lookups are kept for a day
coordinates_cache: TTLCache[tuple[float, float]] = TTLCache(ttl_seconds=24 * 60 * 60)


def normalize(name: str) -> str:
    """Lowercase, with extra spaces removed, so names compare as equal."""
    return " ".join(name.split()).casefold()


def matching_coordinates(
    features: list[Any], city: str, state: StateCode
) -> tuple[float, float] | None:
    """Coordinates of the first place whose name and state match exactly."""
    for feature in features:
        properties = feature["properties"]
        region = properties.get("context", {}).get("region", {})

        # Mapbox also returns places with similar names or in other states
        if normalize(properties["name"]) != normalize(city):
            continue

        if region.get("region_code") != state:
            continue

        longitude, latitude = feature["geometry"]["coordinates"]

        return float(longitude), float(latitude)

    return None


async def get_coordinates(
    client: httpx.AsyncClient, city: str, state: StateCode
) -> tuple[float, float] | None:
    key = (normalize(city), state)

    if (cached := coordinates_cache.get(key)) is not None:
        return cached

    params = {
        "q": f"{city}, {state}",
        "country": "us",
        "types": "place,locality,neighborhood",
        "access_token": settings.mapbox_token.get_secret_value(),
    }

    response = await fetch(client, MAPBOX_URL, params)

    try:
        features = response.json().get("features") or []
        coordinates = matching_coordinates(features, city, state)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ExternalDataError("Mapbox response") from exc

    if coordinates is None:
        return None

    coordinates_cache.set(key, coordinates)

    return coordinates
