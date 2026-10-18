from typing import Any

import pytest
import sentry_sdk
from pydantic import SecretStr
from sentry_sdk.integrations.httpx import HttpxIntegration

from config import settings
from monitoring import setup_sentry

FAKE_DSN = "https://public@sentry.example.com/1"


@pytest.fixture
def init_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Records calls to sentry_sdk.init instead of starting Sentry."""
    calls: list[dict[str, Any]] = []

    def fake_init(**options: Any) -> None:
        calls.append(options)

    monkeypatch.setattr(sentry_sdk, "init", fake_init)
    return calls


def test_sentry_off_without_dsn(
    init_calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "sentry_dsn", None)

    setup_sentry("1.0.0")

    assert init_calls == []


def test_sentry_on_with_dsn(
    init_calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "sentry_dsn", SecretStr(FAKE_DSN))
    monkeypatch.setattr(settings, "environment", "production")

    setup_sentry("1.0.0")

    [options] = init_calls
    assert options["dsn"] == FAKE_DSN
    assert options["environment"] == "production"
    assert options["release"] == "fastapi-weather@1.0.0"
    assert options["send_default_pii"] is False
    assert options["include_local_variables"] is False

    disabled = options["disabled_integrations"]
    assert any(isinstance(integration, HttpxIntegration) for integration in disabled)
