# Weather Lookup API

[![Tests](https://github.com/datalogicpro/fastapi_weather/actions/workflows/tests.yml/badge.svg)](https://github.com/datalogicpro/fastapi_weather/actions/workflows/tests.yml)

A FastAPI app that returns current weather, a 7-day forecast, and past weather for US cities.

**Live demo:** [fastapi-weather-iu1o.onrender.com/docs](https://fastapi-weather-iu1o.onrender.com/docs)

## Features

- Current weather from the nearest National Weather Service station: conditions, temperature, humidity, wind, pressure, and visibility
- 7-day forecast, day and night, with conditions, chance of rain, and wind
- Past daily weather back to the 1800s, from the closest station with records in NOAA or Meteostat
- US units by default (°F, inches, mph), or metric with `units=metric`
- A note when the closest station with records is far from the city
- City lookup with Mapbox: the city and state are both required and must match exactly
- Clear error codes: 400, 404, 422, 429, 502
- Health check endpoint for deployment
- Async requests with one shared HTTP client
- Retries with exponential backoff when an outside service times out or returns 429 or 5xx
- JSON logs with a request ID on every line, and an `X-Request-ID` header on every response
- Error tracking with Sentry in production
- Rate limit of 60 requests per minute per client, and short-term caching of results
- Versioned endpoints under `/v1`

## Tech Stack

- **App:** Python 3.13, FastAPI, Pydantic, pydantic-settings, httpx, tenacity, Meteostat, slowapi
- **Observability:** python-json-logger and asgi-correlation-id (JSON logs with request IDs), Sentry (error tracking)
- **Quality:** pytest, pytest-cov, mypy, Ruff, pip-audit, pre-commit
- **Packaging:** uv (locked versions in `uv.lock`)
- **Deployment:** Docker, GitHub Actions

## Installation

```powershell
git clone https://github.com/datalogicpro/fastapi_weather.git
cd fastapi_weather
uv sync
uv run pre-commit install
```

`uv sync` creates the `.venv` folder and installs the exact versions in `uv.lock`, including the testing and code-check tools.

## Environment Variables

Copy `.env.example` to `.env` in the project folder and add your token:

```text
MAPBOX_TOKEN=your_mapbox_token
```

Do not commit your `.env` file. If the token is missing, the app stops at startup with an error naming it.

These are optional:

```text
SENTRY_DSN=your_sentry_dsn
ENVIRONMENT=production
LOG_LEVEL=INFO
```

- `SENTRY_DSN` turns on Sentry. Set it only in production (on Render), so local runs and tests never send errors to it.
- `ENVIRONMENT` accepts `development` (the default) or `production`.
- `LOG_LEVEL` accepts `DEBUG`, `INFO` (the default), `WARNING`, `ERROR`, or `CRITICAL`.

Any other value for `ENVIRONMENT` or `LOG_LEVEL` stops the app at startup with an error naming it.

## Running the App

```powershell
uv run fastapi dev main.py
```

Interactive docs: http://127.0.0.1:8000/docs

## Run with Docker

Create your `.env` file first (see Environment Variables), then run:

```bash
docker build -t fastapi-weather .
docker run --rm -p 8000:8000 --env-file .env fastapi-weather
```

Interactive docs: http://127.0.0.1:8000/docs

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/weather/current` | Current weather for a city |
| GET | `/v1/weather/forecast` | 7-day forecast for a city |
| GET | `/v1/weather/past` | Daily records for a date range |
| GET | `/health` | Health check |

### `GET /v1/weather/current` and `GET /v1/weather/forecast`

| Parameter | Required | Values |
|---|---|---|
| city | yes | e.g. `Honolulu` |
| state | yes | Two-letter code in capitals, e.g. `HI` |
| units | no | `us` (default) or `metric` |

Example request:

```text
GET /v1/weather/current?city=Honolulu&state=HI
```

Example response:

```json
{
    "units": "us",
    "station": "Daniel K Inouye International Airport",
    "observed_at": "2026-10-10T14:53:00+00:00",
    "conditions": "Partly Cloudy",
    "temperature": 78.1,
    "dew_point": 66.0,
    "humidity": 66.4,
    "wind_speed": 10.4,
    "wind_direction": 70,
    "wind_gust": null,
    "pressure": 30.0,
    "visibility": 10.0,
    "heat_index": 79.5,
    "wind_chill": null
}
```

Example request:

```text
GET /v1/weather/forecast?city=Honolulu&state=HI
```

Example response, shortened to one period:

```json
{
    "units": "us",
    "periods": [
        {
            "name": "Saturday",
            "start_time": "2026-10-10T06:00:00-10:00",
            "is_daytime": true,
            "temperature": 87,
            "precipitation_chance": 12,
            "wind_speed": "9 to 16 mph",
            "wind_direction": "E",
            "conditions": "Sunny"
        }
    ]
}
```

### `GET /v1/weather/past`

| Parameter | Required | Values |
|---|---|---|
| city | yes | e.g. `Honolulu` |
| state | yes | Two-letter code in capitals, e.g. `HI` |
| start_date | yes | `YYYY-MM-DD` |
| end_date | yes | `YYYY-MM-DD` |
| units | no | `us` (default) or `metric` |

Returns the station name, its distance, and daily records. If the station is more than 25 miles away, a `note` explains that.

Example request:

```text
GET /v1/weather/past?city=Honolulu&state=HI&start_date=2020-07-04&end_date=2020-07-04
```

Example response:

```json
{
    "station": "Honolulu International Airport",
    "distance": 6,
    "units": "us",
    "records": [
        {
            "date": "2020-07-04",
            "temperature_avg": 78.3,
            "temperature_max": 86.0,
            "temperature_min": 72.0,
            "humidity": 78.0,
            "precipitation": 0.358,
            "snowfall": null,
            "snow_depth": null,
            "wind_speed": 6.7,
            "wind_gust": null,
            "pressure": 29.98,
            "sunshine_minutes": null,
            "cloud_cover": null
        }
    ],
    "note": null
}
```

Fields a station didn't record are `null`.

Records from NOAA only include temperature, precipitation, snowfall, and snow depth. Humidity, wind, pressure, sunshine, and cloud cover are always `null` in them. NOAA gives the records for every date before 1931, and for later dates when its station is more than 1 mile closer than Meteostat's.

### Units

| Measurement | `us` (default) | `metric` |
|---|---|---|
| Temperature | °F | °C |
| Precipitation | in | mm |
| Snow | in | cm |
| Wind speed | mph | km/h |
| Pressure | inHg | hPa |
| Visibility | mi | km |
| Distance to station | mi | km |

### `GET /health`

Returns `{"status": "ok"}` when the app is running.

## Error Responses

Errors return JSON with a `detail` message, for example `{"detail": "City not found in that state"}`.

| Code | When |
|------|------|
| 400 | `start_date` is after `end_date`, `end_date` is in the future, or the range is longer than 366 days |
| 404 | City not found in that state, location not covered by the National Weather Service, no station near the city, or no data for those dates |
| 422 | Missing or invalid parameter, such as no `state`, `state=hi`, or `units=X` |
| 429 | More than 60 requests in a minute from the same client |
| 502 | An external data service failed |

## Logging

Every log line is JSON, with a timestamp, level, logger name, message, and request ID:

```json
{"level": "INFO", "logger": "main", "message": "Request handled", "request_id": "3f2b9c...", "method": "GET", "path": "/v1/weather/current", "status": 200, "duration_ms": 412.6, "timestamp": "2026-10-13T17:20:05.123+00:00"}
```

Each response has an `X-Request-ID` header with the same ID. A client can send its own `X-Request-ID` (a UUID4), and the API uses it.

When an outside service fails, the log names the service and its status code, never the full URL. The Mapbox token is never written to the logs or sent to Sentry.

Requests to `/health` aren't logged. Render calls it every 5 seconds, and those lines would bury real requests.

## Limitations

- The cache and rate limit are kept in memory. They reset when the app restarts and are not shared between servers.
- The live demo runs on Render's free tier, which sleeps when unused. The first request after a quiet period can take up to a minute.
- Station searches don't cross the 180° line, so in the far western Aleutian Islands, stations on the other side of it aren't found.

## Tests and Linting

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pip-audit
```

The tests mock every external call, so they run without network access or API keys. Each test run also reports coverage and fails if it drops below 100%.

pre-commit runs these before every commit:

- File checks: trailing spaces, end of file, YAML, TOML, merge conflicts, and large files
- The uv lock check, which stops a commit if `uv.lock` is out of date with `pyproject.toml`
- Ruff lint and format, and mypy

## Project Structure

```text
fastapi_weather/
├── main.py                   App setup, request logging, error handlers, shared HTTP client
├── config.py                 Settings loaded from environment variables
├── logging_config.py         JSON logging with request IDs
├── monitoring.py             Sentry error tracking
├── rate_limit.py             Rate limiter
├── routes/                   API endpoints
├── services/                 Calls to Mapbox, NWS, Meteostat, and NOAA, plus retries and caching
├── schemas/                  Pydantic response models
├── tests/                    pytest tests, split by feature
├── Dockerfile
├── .github/
│   ├── workflows/            CI: lint, type check, audit, tests, and Docker build on every push
│   └── dependabot.yml        Weekly dependency updates
├── .pre-commit-config.yaml   Checks run before every commit
├── pyproject.toml            Version, dependencies, plus pytest, coverage, Ruff, and mypy settings
├── uv.lock                   Exact package versions, made by uv
├── CHANGELOG.md              Changes in each release
├── LICENSE
└── .env.example
```

## Challenges

### Finding past weather for any date

Past weather was the hardest part. The further back you go, the fewer records exist. The US only set up a national network of volunteer weather observers in 1890, when Congress passed the Organic Act ([National Weather Service](https://www.weather.gov/chs/coop_background)). Before that, records came from scattered individual observers, so many cities have no nearby station with data from those years.

**Problem:** Requests for older dates returned "no data", even for cities with long weather histories.

**Cause:** I tested old and recent dates in Postman to find where it failed, then turned on Meteostat's debug logging and tested one year at a time. That showed three causes:

- Meteostat's station search stopped at 100 stations, so older stations farther away were never checked.
- Meteostat only serves NOAA's daily records from 1931 on, even though NOAA's own records go back further.
- Meteostat's station list only covers the records Meteostat holds. Downtown Los Angeles is listed from 2000, though NOAA has its records from 1906. Stations looked too new and were skipped, so a 1931 lookup for Los Angeles picked a station 261 miles away.

**Fix:**

- Before 1931, use NOAA's own station search to find stations with temperature records on those dates within 500 km, sort them by distance, and get the records straight from NOAA. Skip any station with no temperature on the requested days.
- For 1931 and later, search up to 1,000 Meteostat stations within 500 km, closest first, and skip stations that started too late or stopped too early.
- For 1931 and later, also run the NOAA search at the same time, and use whichever station is closer. Both sources list some of the same stations with slightly different coordinates, so NOAA's station must be more than 1 mile closer to replace Meteostat's, whose records have more fields.
- Add a note to the response when the station is more than 25 miles away.

**Result:** A lookup for an 1890 date now returns real records from the closest station that has them, with a note giving the station and its distance. A 1931 lookup for Los Angeles returns Downtown Los Angeles, 3 miles away, instead of a station 261 miles away.

### Other findings

- **502 errors from the National Weather Service.**
  Cause: NWS answers some requests with a redirect, and httpx doesn't follow redirects by default.
  Fix: turned on `follow_redirects` and added a regression test.
- **Current weather full of `null` values.**
  Cause: the newest NWS station reading is often incomplete.
  Fix: fetch the last 5 readings and use the newest one that has a temperature.
- **Wrong city from Mapbox.**
  Cause: Mapbox returns places with similar names first. A search for "Adak" returned "Adako, North Carolina" before Adak, Alaska.
  Fix: the city and state are both required, and only a place whose name and state match exactly is used.

## Data Sources

- [Mapbox Geocoding](https://docs.mapbox.com/api/search/geocoding/): converts the city and state to coordinates.
- [National Weather Service API](https://www.weather.gov/documentation/services-web-api): current weather and 7-day forecasts.
- [Meteostat](https://meteostat.net/): finds nearby stations and serves daily records from 1931 on, including humidity, wind, and pressure.
- [NOAA GHCN-Daily](https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily): finds stations and serves their daily records, for every date before 1931 and for later dates when it has the closer station.

## Repository History

This repository was re-created in October 2026 from an earlier version of the project. The project was developed from September 2 to October 13, 2026. The earlier version had more than 50 commits, and I messed up by rushing some of them. Two days later I deleted it, took some time to decide how to fix the commit history, and started over to make a cleaner one. That mess-up is part of my learning experience, and I own it. I had too much work in the project to throw it away.

## License

MIT. See [LICENSE](LICENSE).
