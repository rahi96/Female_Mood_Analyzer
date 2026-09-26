from fastapi import APIRouter, HTTPException

from ai.models.beauty_models import BeautyRequest, BeautyResponse
from ai.services.beauty_service import get_beauty_overview


router = APIRouter()


@router.get("/beauty-overview", response_model=BeautyResponse)
async def beauty_overview(
    user_id: int,
    days: int = 30,
    include_correlations: bool = True
) -> BeautyResponse:
    """
    GET /api/beauty-overview?user_id=2&days=30&include_correlations=true
    
    Get beauty & radiance analysis for a user.
    
    Query Parameters:
    - user_id (int, required): User ID
    - days (int, optional): Historical days to include (default: 30)
    - include_correlations (bool, optional): Include correlations analysis (default: true)
    
    Returns:
    {
        "today": { skin metrics for today },
        "history": [ past skin scans ],
        "correlations": { lifestyle-skin correlations },
        "ai_insights": { Claude-generated personalized insights }
    }
    """
    try:
        request = BeautyRequest(user_id=user_id, days=days, include_correlations=include_correlations)
        return get_beauty_overview(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Beauty overview analysis failed: {exc}")
