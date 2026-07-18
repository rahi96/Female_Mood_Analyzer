from fastapi import APIRouter, HTTPException
from ai.models.bbt_models import (
    CycleInsightsRequest,
    CycleInsightsResponse,
    DailyTipRequest,
    DailyTipResponse,
    DailyVerseRequest,
    DailyVerseResponse,
)
from ai.services.cycle_service import (
    analyze_cycle,
    fetch_backend_data,
    generate_daily_tip,
    generate_daily_verse,
)

router = APIRouter()


@router.get("/backend-data/{user_id}")
async def get_backend_data(user_id: str):
    try:
        return fetch_backend_data(user_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch backend data: {exc}")


@router.post("/cycle-insights", response_model=CycleInsightsResponse)
async def cycle_insights_endpoint(request: CycleInsightsRequest):
    try:
        return analyze_cycle(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")


@router.post("/daily-tip", response_model=DailyTipResponse)
async def daily_tip_endpoint(request: DailyTipRequest):
    try:
        return generate_daily_tip(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Daily tip failed: {exc}")


@router.post("/daily-verse", response_model=DailyVerseResponse)
async def daily_verse_endpoint(request: DailyVerseRequest):
    try:
        return generate_daily_verse(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Daily verse failed: {exc}")
