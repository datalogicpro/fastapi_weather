from typing import Literal

from pydantic import BaseModel, Field

Units = Literal["us", "metric"]

# The 50 states and Washington, DC
StateCode = Literal[
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
    "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
    "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI",
    "WY",
]  # fmt: skip


class ErrorResponse(BaseModel):
    detail: str = Field(examples=["City not found in that state"])


class CurrentWeather(BaseModel):
    units: Units = Field(description="Unit system used for every value")
    station: str = Field(
        description="Weather station the reading came from",
        examples=["Daniel K Inouye International Airport"],
    )
    observed_at: str | None = Field(
        default=None,
        description="When the reading was taken, in UTC",
        examples=["2026-10-09T17:53:00+00:00"],
    )
    conditions: str | None = Field(default=None, examples=["Partly Cloudy"])
    temperature: float | None = Field(default=None, description="°F or °C")
    dew_point: float | None = Field(default=None, description="°F or °C")
    humidity: float | None = Field(default=None, description="Relative humidity, %")
    wind_speed: float | None = Field(default=None, description="mph or km/h")
    wind_direction: int | None = Field(
        default=None, description="Degrees, where 0 is north"
    )
    wind_gust: float | None = Field(default=None, description="mph or km/h")
    pressure: float | None = Field(default=None, description="inHg or hPa")
    visibility: float | None = Field(default=None, description="Miles or km")
    heat_index: float | None = Field(default=None, description="°F or °C")
    wind_chill: float | None = Field(default=None, description="°F or °C")


class ForecastPeriod(BaseModel):
    name: str = Field(examples=["Tonight"])
    start_time: str = Field(examples=["2026-10-09T18:00:00-10:00"])
    is_daytime: bool
    temperature: int | None = Field(default=None, description="°F or °C")
    precipitation_chance: int | None = Field(
        default=None, description="Chance of precipitation, %"
    )
    wind_speed: str = Field(examples=["5 to 10 mph"])
    wind_direction: str = Field(examples=["NE"])
    conditions: str = Field(examples=["Mostly Clear"])


class Forecast(BaseModel):
    units: Units = Field(description="Unit system used for every value")
    periods: list[ForecastPeriod] = Field(description="Day and night periods")


class DailyRecord(BaseModel):
    date: str = Field(examples=["2020-07-04"])
    temperature_avg: float | None = Field(default=None, description="°F or °C")
    temperature_max: float | None = Field(default=None, description="°F or °C")
    temperature_min: float | None = Field(default=None, description="°F or °C")
    humidity: float | None = Field(default=None, description="Relative humidity, %")
    precipitation: float | None = Field(default=None, description="Inches or mm")
    snowfall: float | None = Field(default=None, description="Inches or cm")
    snow_depth: float | None = Field(default=None, description="Inches or cm")
    wind_speed: float | None = Field(default=None, description="mph or km/h")
    wind_gust: float | None = Field(default=None, description="mph or km/h")
    pressure: float | None = Field(default=None, description="inHg or hPa")
    sunshine_minutes: float | None = Field(default=None, description="Minutes")
    cloud_cover: float | None = Field(default=None, description="%")


class PastWeather(BaseModel):
    station: str = Field(examples=["Honolulu International Airport"])
    distance: int = Field(description="Distance to the station, miles or km")
    units: Units = Field(description="Unit system used for every value")
    records: list[DailyRecord]
    note: str | None = Field(
        default=None,
        description="Set when the closest station with records is over 25 miles away",
    )
