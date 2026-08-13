"""Request coalescing to deduplicate concurrent identical requests."""

import asyncio
from typing import Any, Callable, Dict


class RequestCoalescer:
    """Coalesce multiple identical concurrent requests into a single execution."""
    
    def __init__(self):
        self.in_flight: Dict[str, asyncio.Future] = {}
    
    async def coalesce(self, key: str, async_func: Callable) -> Any:
        """
        Execute async_func for key, or wait for existing execution.
        
        If multiple requests come in with the same key concurrently,
        only one execution happens and all waiters get the same result.
        """
        # If request already in progress, wait for it
        if key in self.in_flight:
            return await self.in_flight[key]
        
        # Create new future for this request
        future = asyncio.Future()
        self.in_flight[key] = future
        
        try:
            result = await async_func()
            future.set_result(result)
            return result
        except Exception as e:
            future.set_exception(e)
            raise
        finally:
            # Clean up when done
            if key in self.in_flight:
                del self.in_flight[key]
