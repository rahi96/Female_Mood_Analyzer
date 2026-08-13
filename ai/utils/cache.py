"""LRU Cache with TTL for optimized caching."""

from collections import OrderedDict
import time
from typing import Any, Optional


class LRUCacheWithTTL:
    """Least Recently Used cache with Time-To-Live expiration."""
    
    def __init__(self, max_size: int = 500, ttl_seconds: int = 3600):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.timestamps = {}
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache, returns None if expired or missing."""
        # Check if expired
        if key in self.timestamps:
            if time.time() - self.timestamps[key] > self.ttl_seconds:
                del self.cache[key]
                del self.timestamps[key]
                return None
        
        # Move to end (mark as recently used)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        
        return None
    
    def put(self, key: str, value: Any) -> None:
        """Store value in cache, evicting oldest if full."""
        # Remove oldest if full
        if len(self.cache) >= self.max_size:
            oldest = next(iter(self.cache))
            del self.cache[oldest]
            del self.timestamps[oldest]
        
        self.cache[key] = value
        self.timestamps[key] = time.time()
    
    def clear(self) -> None:
        """Clear all cache entries."""
        self.cache.clear()
        self.timestamps.clear()
    
    def size(self) -> int:
        """Get current number of cached items."""
        return len(self.cache)
