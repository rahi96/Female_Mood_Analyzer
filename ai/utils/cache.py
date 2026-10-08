"""LRU Cache with TTL for optimized caching."""

import threading
import time
from collections import OrderedDict
from typing import Any, Optional, Tuple


class LRUCacheWithTTL:
    """Least Recently Used cache with Time-To-Live expiration. Thread-safe."""

    def __init__(self, max_size: int = 500, ttl_seconds: int = 3600):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.timestamps = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache, returns None if expired or missing."""
        with self._lock:
            if key in self.timestamps:
                if time.time() - self.timestamps[key] > self.ttl_seconds:
                    self.cache.pop(key, None)
                    self.timestamps.pop(key, None)
                    return None

            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]

            return None

    def get_with_age(self, key: str) -> Tuple[Optional[Any], Optional[float]]:
        """Return (value, age_seconds) ignoring TTL. Used for stale-while-revalidate."""
        with self._lock:
            if key not in self.cache:
                return None, None
            self.cache.move_to_end(key)
            age = time.time() - self.timestamps.get(key, time.time())
            return self.cache[key], age

    def put(self, key: str, value: Any) -> None:
        """Store value in cache, evicting oldest if full."""
        with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                self.cache[key] = value
                self.timestamps[key] = time.time()
                return

            if len(self.cache) >= self.max_size:
                oldest, _ = self.cache.popitem(last=False)
                self.timestamps.pop(oldest, None)

            self.cache[key] = value
            self.timestamps[key] = time.time()

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self.cache.clear()
            self.timestamps.clear()

    def size(self) -> int:
        """Get current number of cached items."""
        with self._lock:
            return len(self.cache)
