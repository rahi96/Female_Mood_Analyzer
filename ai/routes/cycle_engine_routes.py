from fastapi import APIRouter, HTTPException

from ai.services.cycle_engine_service import fetch_cycle_engine_data


router = APIRouter()


@router.get("/cycle-engine")
async def cycle_engine_endpoint():
    try:
        return fetch_cycle_engine_data()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cycle engine failed: {exc}")
