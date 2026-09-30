"""Perimenopause & Menopause API routes - ONE endpoint for UI page with tabs."""

from fastapi import APIRouter, Query
from typing import Optional

from ai.services.perimenopause_service import get_perimenopause_dashboard

router = APIRouter(
    prefix="/menopause",
    responses={404: {"description": "Not found"}}
)


# ============================================================================
# SINGLE ENDPOINT - UNIFIED DASHBOARD (UI shows 3 tabs, 1 data source)
# ============================================================================

@router.get(
    "/dashboard",
    response_model=dict,
    summary="Get complete Perimenopause page data",
    description="Returns all data for Perimenopause page with tabs: Symptoms, Insights, Export. Frontend handles tab switching."
)
async def get_dashboard(
    user_id: int = Query(..., gt=0, description="User ID (must be > 0)", example=6),
    period: str = Query(
        "7d",
        description="Time period",
        regex="^(7d|30d|90d)$",
        example="7d"
    )
):
    """
    Get complete perimenopause dashboard - serves all 3 UI tabs
    
    Returns unified data structure with:
    - Tab 1 (Symptoms): Vasomotor tracker + GSM health metrics
    - Tab 2 (Insights): Symptom matrix with correlations + trends  
    - Tab 3 (Export): Clinical export data + PDF-ready report
    
    The frontend handles tab switching by showing/hiding sections.
    
    Query Parameters:
    - user_id: User ID (required)
    - period: Time period - 7d, 30d, or 90d (default: 7d)
    
    Returns:
    - transition_stage: Menopause stage classification
    - vasomotor_tracker: Hot flash frequency, severity, triggers, trend
    - symptom_matrix: Daily symptom heatmap with correlations
    - gsm_health: Intimate and urinary health metrics
    - clinical_export: Clinical recommendations and warnings
    
    Example:
        GET /api/v1/menopause/dashboard?user_id=6&period=7d
    """
    return get_perimenopause_dashboard(user_id, period)
