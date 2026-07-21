from fastapi import APIRouter, HTTPException

from ai.services.numera_insight_service import fetch_numera_insight_data


router = APIRouter()


@router.get("/numera-insight")
async def numera_insight_endpoint():
    try:
        return fetch_numera_insight_data()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Numera insight failed: {exc}")
