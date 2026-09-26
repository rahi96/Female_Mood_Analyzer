"""Athlete Performance API routes."""

from fastapi import APIRouter, HTTPException, Query

from ai.services.athlete_service import (
    get_unified_athlete_performance
)

router = APIRouter()


@router.get("/athlete/unified-performance")
async def get_unified_performance(
    user_id: int = Query(..., ge=1, description="User ID"),
):
    """
    Get unified athlete performance with 4 cycle phase cards.
    
    Shows current readiness + 4 phase cards (Menstrual, Follicular, Ovulation, Luteal) for UI.
    Frontend displays these as clickable buttons showing phase-specific training recommendations.
    
    Parameters:
    - user_id: User ID (required)
    
    Returns current readiness score and all 4 phase cards.
    """
    try:
        return get_unified_athlete_performance(user_id)
    except HTTPException:
        raise
    except Exception as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=f"User {user_id} not found")
        raise HTTPException(status_code=500, detail=f"Unified performance calculation failed: {exc}")

