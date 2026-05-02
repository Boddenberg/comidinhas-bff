from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TTLCache(Generic[T]):
    """Thread-safe TTL cache with LRU eviction.

    The Places enricher hits Google text-search and place-details with very
    repetitive queries when many guides import similar lists. A small
    in-process cache cuts cost and latency without introducing infra
    (no Redis). Suitable for a single-worker BFF.
    """

    def __init__(self, *, max_entries: int, ttl_seconds: int) -> None:
        self._max_entries = max(1, int(max_entries))
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._data: "OrderedDict[str, tuple[float, T]]" = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> T | None:
        now = time.monotonic()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return None
            expires_at, value = entry
            if expires_at < now:
                self._data.pop(key, None)
                self._misses += 1
                return None
            self._data.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: T) -> None:
        expires_at = time.monotonic() + self._ttl_seconds
        with self._lock:
            self._data[key] = (expires_at, value)
            self._data.move_to_end(key)
            while len(self._data) > self._max_entries:
                self._data.popitem(last=False)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "size": len(self._data),
                "max_entries": self._max_entries,
                "ttl_seconds": self._ttl_seconds,
                "hits": self._hits,
                "misses": self._misses,
            }

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


def normalize_query_key(query: str) -> str:
    return " ".join((query or "").lower().split())
