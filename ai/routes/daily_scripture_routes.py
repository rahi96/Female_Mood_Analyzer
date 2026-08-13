import asyncio
from fastapi import APIRouter, HTTPException

from ai.services.daily_scripture_service import fetch_daily_scripture_data
from ai.utils.coalescer import RequestCoalescer

router = APIRouter()

# Request coalescer for deduplicating concurrent requests
_coalescer = RequestCoalescer()


@router.get("/daily-scripture")
async def daily_scripture_endpoint():
    """
    Get daily scripture with optimization algorithms:
    - Request coalescing: Multiple concurrent requests → single LLM call
    - LRU caching: Repeat requests get instant cached response
    - Circuit breaker: Fallback when LLM is down
    """
    try:
        # Use request coalescer to deduplicate concurrent requests
        async def fetch():
            # Run sync function in thread pool to avoid blocking
            return await asyncio.to_thread(fetch_daily_scripture_data)
        
        # Same key for all requests on the same date
        # Multiple users requesting at same time → only 1 LLM call!
        result = await _coalescer.coalesce("daily_scripture", fetch)
        return result
    
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Daily scripture failed: {exc}")
