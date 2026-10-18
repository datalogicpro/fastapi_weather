import time
from collections import OrderedDict
from collections.abc import Hashable


class TTLCache[T]:
    """Keeps values for a set number of seconds, up to a maximum number of entries."""

    def __init__(self, ttl_seconds: float, max_size: int = 1024) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._items: OrderedDict[Hashable, tuple[float, T]] = OrderedDict()

    def get(self, key: Hashable) -> T | None:
        item = self._items.get(key)

        if item is None:
            return None

        expires_at, value = item

        if time.monotonic() > expires_at:
            del self._items[key]
            return None

        return value

    def set(self, key: Hashable, value: T) -> None:
        self._items[key] = (time.monotonic() + self.ttl_seconds, value)
        self._items.move_to_end(key)

        # Drop the oldest entries once the cache is full
        while len(self._items) > self.max_size:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()
