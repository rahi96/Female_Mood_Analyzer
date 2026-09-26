"""
Routes for Lifelong Thriving feature.
Three main endpoints:
1. GET /api/v1/lifelong-thriving/vitality - Vitality Index + 6-year trends
2. GET /api/v1/lifelong-thriving/life-arc - Timeline of health milestones
3. GET /api/v1/lifelong-thriving/reminders - Preventative health reminders

All endpoints use GET with query parameters for:
- Better HTTP caching (CDN, browser cache)
- Cleaner backend integration
- Stateless architecture
- Performance optimization
"""

import logging
from fastapi import APIRouter, HTTPException, status, Query
from typing import Optional

from ai.models.lifelong_thriving_models import (
    VitalityResponse,
    LifeArcResponse,
    RemindersResponse
)
from ai.services.lifelong_thriving_service import (
    VitalityService, LifeArcService, RemindersService
)

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(
    prefix="/api/v1/lifelong-thriving",
    tags=["Lifelong_Thriving_API"],
    responses={
        400: {"description": "Invalid request"},
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"}
    }
)


# ============================================================================
# VITALITY ENDPOINT
# ============================================================================

@router.get(
    "/vitality",
    response_model=VitalityResponse,
    summary="Get Vitality Index",
    description="""
    Calculate the Vitality Index (0-100) with 6-year trends and health dimensions.
    
    ### Features:
    - **Multi-Year Index**: Aggregated vitality score from all health data
    - **6-Year Trends**: Historical performance showing trajectory
    - **Health Dimensions**: Individual scores for Mobility, Cardiovascular, Cognitive, Sleep, Emotional, Metabolic, Reproductive
    - **AI Insights**: Claude LLM analysis with strengths, areas to focus, and recommendations
    
    ### Data Sources:
    - Health logs (mood, energy, symptoms)
    - Health trends (correlations, patterns)
    - Lab reports (biomarkers, hormone levels)
    - Menstrual cycles (regularity, phases)
    - User profile (activity level, life stage)
    
    ### Scoring:
    - 85-100: **Thriving** - Excellent health across all dimensions
    - 70-84: **Strong** - Good health with minor opportunities
    - 55-69: **Moderate** - Balanced but room for enhancement
    - 40-54: **Low** - Significant room for improvement
    - 0-39: **Critical** - Urgent attention needed
    
    ### Personalization:
    - Weighted algorithm based on scientific health principles
    - Adapted to individual health history and data patterns
    - No hardcoded thresholds—entirely data-driven
    """,
    responses={200: {"model": VitalityResponse, "description": "Vitality analysis successful"}}
)
async def get_vitality(
    user_id: int = Query(..., gt=0, description="User ID (must be > 0)"),
    include_ai_insights: bool = Query(True, description="Include Claude AI insights")
) -> VitalityResponse:
    """
    Calculate vitality index and health dimensions.
    
    Automatically analyzes last 6 years of health data.
    
    **Query Parameters:**
    - `user_id` (required): User ID
    - `include_ai_insights` (optional, default=True): Include Claude LLM insights
    
    **Data Range:** Always analyzes last 6 years of history
    
    **Example Request:**
    ```
    GET /api/v1/lifelong-thriving/vitality?user_id=2&include_ai_insights=true
    GET /api/v1/lifelong-thriving/vitality?user_id=2
    ```
    """
    try:
        # Create service and get vitality (always use 6 years of data)
        years_back = 6
        service = VitalityService(user_id=user_id, years_back=years_back)
        response = service.get_vitality_overview()
        
        return response
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating vitality: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error calculating vitality: {str(e)}"
        )


# ============================================================================
# LIFE ARC ENDPOINT
# ============================================================================

@router.get(
    "/life-arc",
    response_model=LifeArcResponse,
    summary="Get Life Arc Timeline",
    description="""
    Generate chronological timeline of significant health milestones.
    
    ### Features:
    - **Automatic Detection**: Milestones detected from:
      - Menstrual cycles (period starts, cycle completions)
      - Health goals (achievements and progress milestones)
      - Lab results (significant biomarker findings)
      - Life stage transitions (major health journey changes)
      - Activity level changes
    
    - **AI Descriptions**: Claude LLM generates natural language descriptions
    - **Significance Scoring**: ML algorithm weights events by importance
    - **Chronological Organization**: Date-sorted with detailed context
    
    ### Milestone Types:
    - `cycle_start` - New menstrual period
    - `cycle_end` - Cycle completion
    - `pregnancy` - Pregnancy confirmed
    - `health_goal` - Health goal achievement
    - `lab_result` - Medical test completion
    - `activity_change` - Activity level shift
    - `life_stage_transition` - Major health journey change
    - `perimenopause` - Perimenopause indicators
    
    ### Personalization:
    - Automatically extracts from user's actual health data
    - Intelligent significance weighting based on health impact
    - AI-generated descriptions specific to user context
    - Dynamic filtering based on relevance
    """,
    responses={200: {"model": LifeArcResponse, "description": "Timeline generated successfully"}}
)
async def get_life_arc(
    user_id: int = Query(..., gt=0, description="User ID (must be > 0)"),
    include_ai_insights: bool = Query(True, description="Include AI descriptions")
) -> LifeArcResponse:
    """
    Generate life arc timeline with health milestones.
    
    Automatically analyzes last 6 years (72 months) of health data.
    
    **Query Parameters:**
    - `user_id` (required): User ID
    - `include_ai_insights` (optional, default=True): Include AI descriptions
    
    **Data Range:** Always analyzes last 6 years of history
    
    **Example Requests:**
    ```
    GET /api/v1/lifelong-thriving/life-arc?user_id=2&include_ai_insights=true
    GET /api/v1/lifelong-thriving/life-arc?user_id=2
    ```
    """
    try:
        # Create service and get timeline (always use 72 months = 6 years of data)
        months_back = 72
        service = LifeArcService(user_id=user_id, months_back=months_back)
        response = service.get_life_arc_timeline()
        
        return response
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating life arc: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating life arc: {str(e)}"
        )


# ============================================================================
# REMINDERS ENDPOINT
# ============================================================================

@router.get(
    "/reminders",
    response_model=RemindersResponse,
    summary="Get Preventative Health Reminders",
    description="""
    Generate evidence-based preventative health reminders with dynamic status.
    
    ### Features:
    - **Medical Guidelines Compliance**: Screening recommendations based on:
      - Age and life stage
      - Gender-specific guidelines
      - Personalized risk assessment
    
    - **Dynamic Status**: Real-time determination based on:
      - **OVERDUE**: Last screening > (guideline interval + 30 days)
      - **DUE_SOON**: Days until due ≤ 30 days
      - **SCHEDULED**: Appointment explicitly booked
      - **UP_TO_DATE**: Within guideline intervals
      - **NOT_APPLICABLE**: Outside age range or not needed
    
    - **Priority Ranking**: 1-5 scale based on:
      - Medical urgency
      - User's risk profile
      - Current health status
      - Evidence-based guidelines
    
    - **Mobility & Stress Indicators**: Secondary health metrics
    
    ### Included Screenings:
    - Mammogram (Age 40+, annual)
    - Bone Density Scan (Age 50+, every 1-2 years)
    - Colonoscopy (Age 45+, every 10 years)
    - Pap Smear (Age 21+, every 3 years)
    - Blood Pressure (Age 18+, every 2 years)
    - Cholesterol Panel (Age 20+, every 4 years)
    - Skin Cancer Check (Annual)
    - Eye Exam (Every 1-2 years)
    - Dental Checkup (Annual)
    
    ### Personalization:
    - Calculates due dates from actual last screening dates
    - Adapts recommendations based on health history
    - No hardcoded dates—entirely dynamic
    """,
    responses={200: {"model": RemindersResponse, "description": "Reminders generated successfully"}}
)
async def get_reminders(
    user_id: int = Query(..., gt=0, description="User ID (must be > 0)"),
    include_ai_insights: bool = Query(True, description="Include AI context and recommendations")
) -> RemindersResponse:
    """
    Generate preventative health reminders.
    
    **Query Parameters:**
    - `user_id` (required): User ID
    - `include_ai_insights` (optional, default=True): Include AI context
    
    **Example Requests:**
    ```
    GET /api/v1/lifelong-thriving/reminders?user_id=2&include_ai_insights=true
    GET /api/v1/lifelong-thriving/reminders?user_id=2
    ```
    
    **Response Includes:**
    - Preventative screenings with status
    - Due dates and days overdue/until due
    - Priority ranking
    - Mobility/stress metrics
    - Summary statistics
    """
    try:
        # Create service and get reminders
        service = RemindersService(user_id=user_id)
        response = service.get_preventative_reminders()
        
        return response
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating reminders: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating reminders: {str(e)}"
        )


# ============================================================================
# HEALTH CHECK ENDPOINT
# ============================================================================

@router.get(
    "/health",
    summary="Health Check",
    description="Check if Lifelong Thriving service is available"
)
async def health_check():
    """Health check endpoint for service availability."""
    return {
        "status": "healthy",
        "service": "Lifelong Thriving",
        "endpoints": [
            "/api/v1/lifelong-thriving/vitality",
            "/api/v1/lifelong-thriving/life-arc",
            "/api/v1/lifelong-thriving/reminders"
        ]
    }
