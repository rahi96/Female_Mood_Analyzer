"""Athlete Performance API routes."""

from fastapi import APIRouter, HTTPException, Query

from ai.services.athlete_service import get_unified_athlete_performance

router = APIRouter()




@router.get("/athlete/unified-performance")
async def get_unified_performance(
    user_id: int = Query(..., ge=1, description="User ID"),
    cycle_phase: str = Query(..., description="Cycle phase: menstrual | follicular | ovulation | luteal"),
):
    """
    **UNIFIED Athlete Performance API**
    
    Combines readiness score and cycle-based training recommendations in ONE response.
    LLM generates phase-specific training insights based on readiness metrics and selected cycle phase.
    
    **Input Parameters:**
    - `user_id`: User ID (required)
    - `cycle_phase`: Cycle phase (menstrual | follicular | ovulation | luteal) - required
    
    **Response includes:**
    - Readiness score (0-100) with level (Peak Ready | Ready | Adequate | Fatigued | Depleted)
    - HRV, Recovery, Training Load metrics
    - Fatigue alerts
    - Cycle information
    - **Cycle-based training focus** - LLM generates phase-specific insights based on readiness score and metrics
    
    **Example response structure:**
    ```json
    {
      "date": "2026-09-26",
      "readiness_score": 84,
      "readiness_level": "Ready",
      "hrv": {
        "value": 62,
        "unit": "ms",
        "trend": -2,
        "status": "good"
      },
      "recovery": {
        "percentage": 74,
        "trend": 4,
        "status": "high"
      },
      "training_load": {
        "value": 210,
        "unit": "AU",
        "trend": 15,
        "status": "moderate"
      },
      "metrics": {...},
      "fatigue_alerts": [
        {
          "type": "overtraining_risk",
          "level": "low",
          "message": ""
        }
      ],
      "cycle_info": {...},
      "training_focus": {
        "cycle_phase": "ovulation",
        "phase_day": "D14",
        "focus": "Peak performance",
        "recommendations": [
          "Max effort workouts",
          "High-intensity cardio",
          "Test 1RM strength",
          "Optimal power & coordination"
        ]
      },
      "next_update": "2026-09-27T08:00:00Z"
    }
    ```
    """
    try:
        return get_unified_athlete_performance(user_id, cycle_phase)
    except HTTPException:
        raise
    except Exception as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=f"User {user_id} not found")
        if "Invalid cycle phase" in str(exc):
            raise HTTPException(status_code=422, detail=f"Invalid cycle phase: {cycle_phase}")
        raise HTTPException(status_code=500, detail=f"Unified performance calculation failed: {exc}")