from fastapi import APIRouter, HTTPException

from ai.services.daily_scripture_service import fetch_daily_scripture_data


router = APIRouter()


@router.get("/daily-scripture")
async def daily_scripture_endpoint():
    try:
        return fetch_daily_scripture_data()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Daily scripture failed: {exc}")
