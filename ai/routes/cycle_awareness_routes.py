from fastapi import APIRouter, HTTPException, Query

from ai.services.cycle_awareness_service import fetch_cycle_awareness_data


router = APIRouter()


@router.get("/cycle-awareness")
async def cycle_awareness_endpoint(user_id: int = Query(..., description="User ID")):
    try:
        return fetch_cycle_awareness_data(user_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cycle awareness failed: {exc}")
