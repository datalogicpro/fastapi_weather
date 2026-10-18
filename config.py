from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    mapbox_token: SecretStr
    sentry_dsn: SecretStr | None = None
    environment: Literal["development", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    request_timeout: float = 10
    retry_attempts: int = 3
    retry_backoff: float = 0.5
    user_agent: str = "fastapi-weather (github.com/datalogicpro/fastapi_weather)"
    rate_limit: str = "60/minute"


settings = Settings()
