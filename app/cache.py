from __future__ import annotations

import threading
import time
from typing import Any


class TTLCache:
    """Small in-process TTL cache. Single-process app only."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str, default: Any = None) -> Any:
        now = time.time()
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return default
            expires_at, value = item
            if expires_at <= now:
                self._items.pop(key, None)
                return default
            return value

    def set(self, key: str, value: Any, ttl: float) -> Any:
        with self._lock:
            self._items[key] = (time.time() + ttl, value)
        return value

    def delete(self, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)

    def clear(self, prefix: str | None = None) -> None:
        with self._lock:
            if prefix is None:
                self._items.clear()
                return
            for key in [k for k in self._items if k.startswith(prefix)]:
                self._items.pop(key, None)


class CircuitBreaker:
    """Avoid repeatedly waiting on a data provider that is rate limited."""

    def __init__(self, failure_threshold: int = 2, open_seconds: float = 180.0) -> None:
        self.failure_threshold = failure_threshold
        self.open_seconds = open_seconds
        self._failures = 0
        self._open_until = 0.0
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            return time.time() >= self._open_until

    def success(self) -> None:
        with self._lock:
            self._failures = 0
            self._open_until = 0.0

    def fail(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._open_until = time.time() + self.open_seconds

    def open_for(self, seconds: float) -> None:
        with self._lock:
            self._failures = max(self._failures, self.failure_threshold)
            self._open_until = max(self._open_until, time.time() + seconds)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            remaining = max(0, int(self._open_until - time.time()))
            return {
                "open": remaining > 0,
                "seconds_remaining": remaining,
                "failures": self._failures,
            }
