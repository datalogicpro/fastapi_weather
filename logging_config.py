import logging.config

from config import settings


def setup_logging() -> None:
    """Writes every log line as JSON, with the ID of the request it belongs to."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "request_id": {
                    "()": "asgi_correlation_id.CorrelationIdFilter",
                    "uuid_length": 32,
                    "default_value": "-",
                },
            },
            "formatters": {
                "json": {
                    "()": "pythonjsonlogger.json.JsonFormatter",
                    "fmt": "%(levelname)s %(name)s %(message)s %(correlation_id)s",
                    "rename_fields": {
                        "levelname": "level",
                        "name": "logger",
                        "correlation_id": "request_id",
                    },
                    "timestamp": True,
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "filters": ["request_id"],
                    "formatter": "json",
                },
            },
            "root": {"handlers": ["console"], "level": settings.log_level},
            "loggers": {
                # httpx logs every request URL at INFO, and Mapbox URLs hold the token
                "httpx": {"level": "WARNING"},
                # Replaced by the JSON request log in main.py
                "uvicorn.access": {"level": "WARNING"},
            },
        }
    )
