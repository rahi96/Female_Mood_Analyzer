from fastapi import APIRouter, HTTPException

from ai.models.bbt_models import (
    MovementRecommendationRequest,
    MovementRecommendationResponse,
)
from ai.services.movement_service import generate_movement_recommendation


router = APIRouter()


@router.post("/cycle-movement/follicular", response_model=MovementRecommendationResponse)
def follicular_movement_endpoint(request: MovementRecommendationRequest):
    """Follicular Phase (Day 1-13): AI-powered movement recommendations."""
    try:
        return generate_movement_recommendation(request, "follicular")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Follicular movement recommendation failed: {exc}")


@router.post("/cycle-movement/ovulation", response_model=MovementRecommendationResponse)
def ovulation_movement_endpoint(request: MovementRecommendationRequest):
    """Ovulation Phase (Day 14-16): AI-powered movement recommendations."""
    try:
        return generate_movement_recommendation(request, "ovulation")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ovulation movement recommendation failed: {exc}")


@router.post("/cycle-movement/luteal", response_model=MovementRecommendationResponse)
def luteal_movement_endpoint(request: MovementRecommendationRequest):
    """Luteal Phase (Day 17-28): AI-powered movement recommendations."""
    try:
        return generate_movement_recommendation(request, "luteal")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Luteal movement recommendation failed: {exc}")


@router.post("/cycle-movement/menstrual", response_model=MovementRecommendationResponse)
def menstrual_movement_endpoint(request: MovementRecommendationRequest):
    """Menstrual Phase (Day 1-5): AI-powered movement recommendations."""
    try:
        return generate_movement_recommendation(request, "menstrual")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Menstrual movement recommendation failed: {exc}")
