from fastapi import APIRouter, HTTPException

from ai.services.smart_analysis_service import fetch_smart_analysis_data


router = APIRouter()


@router.get("/smart-analysis")
async def smart_analysis_endpoint():
    try:
        return fetch_smart_analysis_data()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Smart analysis failed: {exc}")
