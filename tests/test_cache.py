import pytest

from services import cache
from services.cache import TTLCache


def test_cache_returns_saved_value() -> None:
    store: TTLCache[str] = TTLCache(ttl_seconds=60)

    store.set("key", "value")

    assert store.get("key") == "value"
    assert store.get("missing") is None


def test_cache_expires_values(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 1000.0
    monkeypatch.setattr(cache.time, "monotonic", lambda: now)
    store: TTLCache[str] = TTLCache(ttl_seconds=60)

    store.set("key", "value")
    now += 61

    assert store.get("key") is None


def test_cache_drops_oldest_when_full() -> None:
    store: TTLCache[int] = TTLCache(ttl_seconds=60, max_size=2)

    store.set("a", 1)
    store.set("b", 2)
    store.set("c", 3)

    assert store.get("a") is None
    assert store.get("b") == 2
    assert store.get("c") == 3
