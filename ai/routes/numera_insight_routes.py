from fastapi import APIRouter, HTTPException, Query

from ai.services.numera_insight_service import fetch_numera_insight_data


router = APIRouter()


@router.get("/numera-insight")
async def numera_insight_endpoint(user_id: int = Query(..., description="User ID")):
    try:
        return fetch_numera_insight_data(user_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Numera insight failed: {exc}")
