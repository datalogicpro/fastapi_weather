# Changelog

All notable changes to this project are listed here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Current weather from the nearest National Weather Service station.
- 7-day forecast from the National Weather Service, day and night.
- Past daily weather back to the 1800s, from the closest station with records in NOAA or Meteostat.
- City lookup with Mapbox. The city and state are both required and must match exactly.
- US units by default, or metric with `units=metric`.
- A note when the closest station with records is more than 25 miles away.
- Error responses: 400, 404, 422, 429, and 502.
- Retries with exponential backoff when an outside service times out or returns 429 or 5xx.
- JSON logs with a request ID on every line, and an `X-Request-ID` header on every response.
- Sentry error tracking in production, set up so the Mapbox token is never sent.
- Rate limit of 60 requests per minute per client, and short-term caching of results.
- Health check endpoint at `/health`.
- Tests with 100% coverage, Ruff, mypy, pip-audit, and pre-commit.
- GitHub Actions for the checks and tests, a Docker image build, and Dependabot.
