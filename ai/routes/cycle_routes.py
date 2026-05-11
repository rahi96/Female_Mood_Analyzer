from fastapi import APIRouter, HTTPException
from ai.models.bbt_models import CycleInsightsRequest, CycleInsightsResponse
from ai.services.cycle_service import analyze_cycle, _fetch_user_data

router = APIRouter()


@router.get("/backend-data/{user_id}")
async def get_backend_data(user_id: str):
    try:
        return _fetch_user_data(user_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch backend data: {exc}")


@router.post("/cycle-insights", response_model=CycleInsightsResponse)
async def cycle_insights_endpoint(request: CycleInsightsRequest):
    try:
        return analyze_cycle(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")
