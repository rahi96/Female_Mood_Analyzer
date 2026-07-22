from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from ai.services.health_trends_service import fetch_health_trends_data


router = APIRouter()


@router.get("/health-trends")
async def health_trends_endpoint(period: Literal["7d", "30d"] = Query("7d")):
    try:
        return fetch_health_trends_data(period=period)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Health trends failed: {exc}")