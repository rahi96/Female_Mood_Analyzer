from fastapi import APIRouter, HTTPException

from ai.services.health_trends_service import fetch_health_trends_data


router = APIRouter()


@router.get("/health-trends")
async def health_trends_endpoint():
    try:
        return fetch_health_trends_data()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Health trends failed: {exc}")
