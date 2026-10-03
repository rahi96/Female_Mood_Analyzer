"""Perimenopause & Menopause API routes - 3 independent tab endpoints."""

from fastapi import APIRouter, Query

from ai.services.perimenopause_service import (
    get_perimenopause_symptoms,
    get_perimenopause_insights_tab,
    get_perimenopause_export,
)

router = APIRouter(
    prefix="/menopause",
    responses={404: {"description": "Not found"}}
)


# ============================================================================
# TAB 1 - SYMPTOMS (transition stage + vasomotor tracker + GSM health)
# ============================================================================

@router.get(
    "/symptoms",
    response_model=dict,
    summary="Get Symptoms tab data",
    description="Transition stage tracker + vasomotor tracker + GSM health. No LLM call - fast."
)
async def get_symptoms(
    user_id: int = Query(..., gt=0, description="User ID (must be > 0)", example=6),
    period: str = Query(
        "7d",
        description="Time period",
        regex="^(7d|30d|90d)$",
        example="7d"
    )
):
    """
    Get Symptoms tab data - transition stage, vasomotor tracker, GSM health.

    Example:
        GET /api/v1/menopause/symptoms?user_id=6&period=7d
    """
    return get_perimenopause_symptoms(user_id, period)


# ============================================================================
# TAB 2 - INSIGHTS (symptom matrix with correlations)
# ============================================================================

@router.get(
    "/insights",
    response_model=dict,
    summary="Get Insights tab data",
    description="Symptom matrix with correlations and trends. No LLM call - fast."
)
async def get_insights(
    user_id: int = Query(..., gt=0, description="User ID (must be > 0)", example=6),
    period: str = Query(
        "7d",
        description="Time period",
        regex="^(7d|30d|90d)$",
        example="7d"
    )
):
    """
    Get Insights tab data - symptom matrix with correlations.

    Example:
        GET /api/v1/menopause/insights?user_id=6&period=7d
    """
    return get_perimenopause_insights_tab(user_id, period)


# ============================================================================
# TAB 3 - EXPORT (clinical export, LLM-generated recommendations - slow)
# ============================================================================

@router.get(
    "/export",
    response_model=dict,
    summary="Get Export tab data",
    description="Clinical export with LLM-generated recommendations - call only when the user opens this tab or clicks Export PDF, since it's the slow path (Claude call)."
)
async def get_export(
    user_id: int = Query(..., gt=0, description="User ID (must be > 0)", example=6),
    period: str = Query(
        "7d",
        description="Time period",
        regex="^(7d|30d|90d)$",
        example="7d"
    )
):
    """
    Get Export tab data - clinical_export with clinical/lifestyle recommendations.

    Example:
        GET /api/v1/menopause/export?user_id=6&period=7d
    """
    return get_perimenopause_export(user_id, period)
