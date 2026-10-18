import json
import logging
from uuid import uuid4

import pytest
from asgi_correlation_id import correlation_id
from fastapi.testclient import TestClient
from pythonjsonlogger.json import JsonFormatter


def test_response_has_request_id(client: TestClient) -> None:
    response = client.get("/health")

    assert len(response.headers["X-Request-ID"]) == 32


def test_request_id_is_passed_through(client: TestClient) -> None:
    request_id = uuid4().hex

    response = client.get("/health", headers={"X-Request-ID": request_id})

    assert response.headers["X-Request-ID"] == request_id


def test_requests_are_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    client.get("/v1/weather/current", params={"city": "Honolulu", "units": "X"})

    record = next(r for r in caplog.records if r.getMessage() == "Request handled")
    assert record.__dict__["method"] == "GET"
    assert record.__dict__["path"] == "/v1/weather/current"
    assert record.__dict__["status"] == 422
    assert record.__dict__["duration_ms"] >= 0


def test_health_checks_are_not_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    client.get("/health")

    assert not any(r.getMessage() == "Request handled" for r in caplog.records)


def test_log_lines_are_json_with_request_id() -> None:
    handler = next(
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler.formatter, JsonFormatter)
    )
    record = logging.LogRecord("main", logging.INFO, __file__, 1, "hello", None, None)
    token = correlation_id.set("abc123")

    try:
        handler.filter(record)
        line = json.loads(handler.format(record))
    finally:
        correlation_id.reset(token)

    assert line["message"] == "hello"
    assert line["level"] == "INFO"
    assert line["logger"] == "main"
    assert line["request_id"] == "abc123"
    assert "timestamp" in line
