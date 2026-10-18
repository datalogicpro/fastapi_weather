import asyncio
import json
import logging
import math
from dataclasses import dataclass
from datetime import date

import httpx
import meteostat as ms
import requests

from schemas.weather import DailyRecord, PastWeather, Units
from services.errors import ExternalDataError
from services.http_client import fetch

logger = logging.getLogger(__name__)

MIN_METEOSTAT_DATE = date(1931, 1, 1)

NOAA_URL = "https://www.ncei.noaa.gov/access/services/data/v1"

# Lists NOAA stations that have records for given dates inside an area
NOAA_SEARCH_URL = "https://www.ncei.noaa.gov/access/services/search/v1/data"

SEARCH_RADIUS_METERS = 500_000

MAX_STATIONS = 1000

EARTH_RADIUS_METERS = 6_371_000

METERS_PER_DEGREE_LATITUDE = 111_320

METERS_PER_MILE = 1609.34

# Meteostat and NOAA list some of the same stations with slightly different
# coordinates, so NOAA's station must be this much closer to win
CLOSER_BY_METERS = METERS_PER_MILE

# Past this distance, the response includes a note
NOTE_DISTANCE_MILES = 25

# Our field name -> Meteostat column
METEOSTAT_FIELDS = {
    "temperature_avg": "temp",
    "temperature_max": "tmax",
    "temperature_min": "tmin",
    "humidity": "rhum",
    "precipitation": "prcp",
    "snow_depth": "snwd",
    "wind_speed": "wspd",
    "wind_gust": "wpgt",
    "pressure": "pres",
    "sunshine_minutes": "tsun",
    "cloud_cover": "cldc",
}

# Our field name -> NOAA data type
NOAA_FIELDS = {
    "temperature_avg": "TAVG",
    "temperature_max": "TMAX",
    "temperature_min": "TMIN",
    "precipitation": "PRCP",
    "snowfall": "SNOW",
    "snow_depth": "SNWD",
}

METEOSTAT_UNITS = {"us": ms.UnitSystem.IMPERIAL, "metric": ms.UnitSystem.METRIC}

NOAA_UNITS = {"us": "standard", "metric": "metric"}

HPA_TO_INHG = 0.02953

OKTAS_TO_PERCENT = 12.5


@dataclass
class Station:
    id: str
    name: str
    region: str
    distance_meters: float

    @property
    def distance_miles(self) -> int:
        return round(self.distance_meters / METERS_PER_MILE)

    @property
    def distance_km(self) -> int:
        return round(self.distance_meters / 1000)

    @property
    def is_far(self) -> bool:
        return self.distance_miles > NOTE_DISTANCE_MILES


# A station and its records for the requested dates
StationRecords = tuple[Station, list[DailyRecord]]


def distance_meters(
    latitude: float, longitude: float, other_latitude: float, other_longitude: float
) -> float:
    """Distance between two points on the Earth, using the haversine formula."""
    lat1 = math.radians(latitude)
    lat2 = math.radians(other_latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(other_longitude - longitude)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )

    return 2 * EARTH_RADIUS_METERS * math.asin(math.sqrt(a))


def search_box(latitude: float, longitude: float) -> str:
    """NOAA bounding box (north,west,south,east) that holds the search radius."""
    lat_delta = SEARCH_RADIUS_METERS / METERS_PER_DEGREE_LATITUDE
    lon_delta = lat_delta / max(math.cos(math.radians(latitude)), 0.01)

    north = min(latitude + lat_delta, 90)
    south = max(latitude - lat_delta, -90)
    west = max(longitude - lon_delta, -180)
    east = min(longitude + lon_delta, 180)

    return f"{north:.4f},{west:.4f},{south:.4f},{east:.4f}"


def split_noaa_name(full_name: str) -> tuple[str, str]:
    """Turns 'SAN DIEGO AIRPORT, CA US' into ('San Diego Airport', 'CA')."""
    name, _, region = full_name.rpartition(", ")

    if not name:
        return full_name.title(), ""

    return name.title(), region.split()[0]


async def search_noaa_stations(
    client: httpx.AsyncClient,
    latitude: float,
    longitude: float,
    start_date: date,
    end_date: date,
) -> list[Station]:
    """NOAA stations with temperature records for the dates, closest first."""
    params: dict[str, str | int] = {
        "dataset": "daily-summaries",
        "bbox": search_box(latitude, longitude),
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "dataTypes": "TMAX",
        "limit": MAX_STATIONS,
    }

    response = await fetch(client, NOAA_SEARCH_URL, params)

    stations = []

    try:
        for result in response.json()["results"]:
            station = result["stations"][0]
            station_longitude, station_latitude = result["location"]["coordinates"]
            distance = distance_meters(
                latitude, longitude, station_latitude, station_longitude
            )

            # The box's corners reach past the search radius
            if distance > SEARCH_RADIUS_METERS:
                continue

            name, region = split_noaa_name(station["name"])

            stations.append(
                Station(
                    id=station["id"],
                    name=name,
                    region=region,
                    distance_meters=distance,
                )
            )
    except (KeyError, TypeError, IndexError, ValueError) as exc:
        raise ExternalDataError("NOAA station search") from exc

    return sorted(stations, key=lambda station: station.distance_meters)


def find_stations(latitude: float, longitude: float, start_date: date) -> list[Station]:
    """Meteostat stations with records on start_date, closest first."""
    point = ms.Point(latitude, longitude)
    nearby = ms.stations.nearby(point, radius=SEARCH_RADIUS_METERS, limit=MAX_STATIONS)

    stations = []

    for station_id, row in nearby.iterrows():
        inventory = ms.stations.inventory(station_id)

        if inventory.start is None or inventory.start > start_date:
            continue

        # Skip stations whose records ended before the dates we need
        if inventory.end is not None and inventory.end < start_date:
            continue

        stations.append(
            Station(
                id=str(station_id),
                name=row["name"],
                region=row["region"],
                distance_meters=row["distance"],
            )
        )

    return stations


def get_meteostat_records(
    station_id: str, start_date: date, end_date: date, units: Units
) -> list[DailyRecord]:
    data = ms.daily(station_id, start_date, end_date)
    df = data.fetch(units=METEOSTAT_UNITS[units])

    if df is None or df.empty:
        return []

    rows = json.loads(df.reset_index().to_json(orient="records", date_format="iso"))

    records = []

    for row in rows:
        record = {"date": row["time"][:10]}

        for field, column in METEOSTAT_FIELDS.items():
            record[field] = row.get(column)

        # Meteostat keeps pressure in hPa and cloud cover in oktas for every unit
        if units == "us" and record["pressure"] is not None:
            record["pressure"] = round(record["pressure"] * HPA_TO_INHG, 2)

        if record["cloud_cover"] is not None:
            record["cloud_cover"] = round(record["cloud_cover"] * OKTAS_TO_PERCENT)

        records.append(DailyRecord.model_validate(record))

    return records


async def get_noaa_records(
    client: httpx.AsyncClient,
    station_id: str,
    start_date: date,
    end_date: date,
    units: Units,
) -> list[DailyRecord]:
    params = {
        "dataset": "daily-summaries",
        "stations": station_id,
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "dataTypes": ",".join(NOAA_FIELDS.values()),
        "format": "json",
        "units": NOAA_UNITS[units],
    }

    response = await fetch(client, NOAA_URL, params)

    records = []

    try:
        for row in response.json():
            record = {"date": row["DATE"]}

            for field, data_type in NOAA_FIELDS.items():
                value = row.get(data_type)
                record[field] = float(value) if value else None

            # NOAA metric snow is in mm, but this API uses cm for snow
            if units == "metric":
                for field in ("snowfall", "snow_depth"):
                    if record[field] is not None:
                        record[field] = record[field] / 10

            records.append(DailyRecord.model_validate(record))
    except (KeyError, TypeError, ValueError) as exc:
        raise ExternalDataError("NOAA response") from exc

    return records


def build_result(
    station: Station, records: list[DailyRecord], units: Units
) -> PastWeather:
    distance = station.distance_miles if units == "us" else station.distance_km
    distance_unit = "miles" if units == "us" else "km"

    note = None

    if station.is_far:
        place = ", ".join(part for part in (station.name, station.region) if part)
        note = (
            f"No nearby station has records for these dates. "
            f"Closest with records: {place} ({distance} {distance_unit} away)."
        )

    return PastWeather(
        station=station.name,
        distance=distance,
        units=units,
        records=records,
        note=note,
    )


async def find_noaa_records(
    client: httpx.AsyncClient,
    latitude: float,
    longitude: float,
    start_date: date,
    end_date: date,
    units: Units,
) -> StationRecords | None:
    """The closest NOAA station with a temperature on the requested days."""
    stations = await search_noaa_stations(
        client, latitude, longitude, start_date, end_date
    )

    for station in stations:
        records = await get_noaa_records(
            client, station.id, start_date, end_date, units
        )

        # The search lists stations with temperature records somewhere in the
        # date range, so some have no temperature on the requested days
        if any(record.temperature_max is not None for record in records):
            return station, records

    return None


async def find_meteostat_records(
    latitude: float,
    longitude: float,
    start_date: date,
    end_date: date,
    units: Units,
) -> StationRecords | None:
    """The closest Meteostat station with records for the requested days."""
    # Meteostat is not async, so its calls run in a worker thread
    try:
        stations = await asyncio.to_thread(
            find_stations, latitude, longitude, start_date
        )

        for station in stations:
            records = await asyncio.to_thread(
                get_meteostat_records, station.id, start_date, end_date, units
            )

            if records:
                return station, records
    except requests.RequestException as exc:
        raise ExternalDataError("Meteostat request") from exc

    return None


async def find_closest_records(
    client: httpx.AsyncClient,
    latitude: float,
    longitude: float,
    start_date: date,
    end_date: date,
    units: Units,
) -> StationRecords | None:
    """The closer of Meteostat's and NOAA's closest stations, asking both at once."""
    # Meteostat is missing many stations' older NOAA records, so NOAA can
    # have a closer station even for recent dates
    results = await asyncio.gather(
        find_meteostat_records(latitude, longitude, start_date, end_date, units),
        find_noaa_records(client, latitude, longitude, start_date, end_date, units),
        return_exceptions=True,
    )

    found: dict[str, StationRecords] = {}
    errors: list[BaseException] = []

    for source, result in zip(("Meteostat", "NOAA"), results, strict=True):
        if isinstance(result, BaseException):
            errors.append(result)
            logger.warning(
                "Past weather source failed",
                extra={"source": source, "error": type(result).__name__},
            )
        elif result is not None:
            found[source] = result

    # With no station found, the failed source might have had one, so it's an error
    if errors and not found:
        raise errors[0]

    meteostat_found = found.get("Meteostat")
    noaa_found = found.get("NOAA")

    if meteostat_found is None:
        return noaa_found

    if noaa_found is None:
        return meteostat_found

    # Meteostat wins close calls for its extra fields
    noaa_gain = meteostat_found[0].distance_meters - noaa_found[0].distance_meters

    if noaa_gain > CLOSER_BY_METERS:
        return noaa_found

    return meteostat_found


async def get_past_weather(
    client: httpx.AsyncClient,
    latitude: float,
    longitude: float,
    start_date: date,
    end_date: date,
    units: Units,
) -> PastWeather | None:
    # Meteostat has no records before 1931, so NOAA finds the stations and the data
    if start_date < MIN_METEOSTAT_DATE:
        found = await find_noaa_records(
            client, latitude, longitude, start_date, end_date, units
        )
    else:
        found = await find_closest_records(
            client, latitude, longitude, start_date, end_date, units
        )

    if found is None:
        return None

    station, records = found

    return build_result(station, records, units)
