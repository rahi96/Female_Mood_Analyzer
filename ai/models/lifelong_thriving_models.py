"""Pydantic models for Lifelong Thriving feature (Vitality, Life Arc, Reminders)."""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime, date, timezone
from enum import Enum


# ============================================================================
# Request Models
# ============================================================================

class LifelongThrivingRequest(BaseModel):
    """Common request for all Lifelong Thriving endpoints."""
    user_id: int = Field(..., gt=0, description="User ID")
    include_ai_insights: bool = Field(default=True, description="Include Claude AI insights")


# ============================================================================
# VITALITY TAB Models
# ============================================================================

class VitalityRequest(LifelongThrivingRequest):
    """Request for Vitality Index calculation."""
    years_back: int = Field(default=6, ge=1, le=10, description="Years of history to analyze (1-10)")


class VitalityDimension(BaseModel):
    """Individual health dimension score."""
    name: str = Field(..., description="Dimension name (e.g., 'Mobility', 'Cardiovascular')")
    score: float = Field(..., ge=0, le=100, description="Score 0-100")
    status: str = Field(..., description="Status: thriving, strong, moderate, low, critical")
    trend: str = Field(default="stable", description="Trend: improving, stable, declining")
    last_updated: Optional[date] = Field(None, description="Last data point date")
    description: Optional[str] = Field(None, description="Context about this dimension")


class YearlyVitalityTrend(BaseModel):
    """Yearly aggregated vitality score."""
    year: int = Field(..., description="Year")
    score: float = Field(..., ge=0, le=100, description="Annual average vitality score")
    data_points: int = Field(default=0, description="Number of data points that year")


class VitalityAIInsights(BaseModel):
    """Claude AI-generated insights about vitality."""
    summary: str = Field(..., description="2-3 sentence overall summary")
    strengths: List[str] = Field(default_factory=list, description="Key strengths")
    areas_to_focus: List[str] = Field(default_factory=list, description="Areas for improvement")
    recommendations: List[str] = Field(default_factory=list, description="Actionable recommendations")
    confidence_score: int = Field(default=85, ge=0, le=100, description="Confidence in analysis")


class VitalityResponse(BaseModel):
    """Response for Vitality Tab API."""
    vitality_index: float = Field(..., ge=0, le=100, description="Overall vitality score 0-100")
    vitality_level: str = Field(..., description="Level: Thriving, Strong, Moderate, Low, Critical")
    personal_best: str = Field(..., description="Contextual statement about their performance")
    
    trend_6_years: List[YearlyVitalityTrend] = Field(..., description="6-year trend data")
    
    dimensions: List[VitalityDimension] = Field(..., description="Individual health dimensions")
    
    ai_insights: Optional[VitalityAIInsights] = Field(None, description="Claude AI insights")
    
    eligibility_status: str = Field(default="eligible", description="eligible | ineligible | check_failed")
    data_completeness: float = Field(default=100, ge=0, le=100, description="% of available data sources being used")
    
    last_updated: datetime = Field(default_factory=datetime.now, description="Response generated at")
    
    class Config:
        json_schema_extra = {
            "example": {
                "vitality_index": 85,
                "vitality_level": "Thriving",
                "personal_best": "Personal best — thriving at every level",
                "trend_6_years": [
                    {"year": 2020, "score": 72, "data_points": 180},
                    {"year": 2021, "score": 75, "data_points": 200},
                ],
                "dimensions": [
                    {
                        "name": "Mobility & Strength",
                        "score": 82,
                        "status": "strong",
                        "trend": "improving",
                        "last_updated": "2026-09-20",
                        "description": "Consistent strength training and activity"
                    }
                ],
                "ai_insights": {
                    "summary": "Your vitality is excellent...",
                    "strengths": ["Strong cardiovascular health"],
                    "areas_to_focus": ["Flexibility"],
                    "recommendations": ["Continue current routine"],
                    "confidence_score": 88
                }
            }
        }


# ============================================================================
# LIFE ARC TAB Models
# ============================================================================

class MilestoneHealthContext(BaseModel):
    """Health context for a milestone."""
    cycle_day: Optional[int] = None
    phase: Optional[str] = None
    duration: Optional[str] = None
    progress: Optional[str] = None
    status: Optional[str] = None
    key_findings: Optional[List[str]] = None
    goal_progress: Optional[float] = None


class Milestone(BaseModel):
    """Single milestone on the life arc timeline."""
    date_: date = Field(..., alias="date", description="Milestone date")
    type_: str = Field(..., alias="type", description="Type: cycle_start, phase_transition, symptom_resolution, health_goal, health_insight, activity_milestone, lab_result")
    title: str = Field(..., description="Milestone title")
    description: str = Field(..., description="Human-readable description")
    significance: float = Field(..., ge=0, le=1, description="Significance score 0-1")
    icon: str = Field(..., description="UI icon key")
    health_context: Optional[MilestoneHealthContext] = Field(None, description="Associated health data")
    
    class Config:
        populate_by_name = True


class TimelineSummary(BaseModel):
    """Summary statistics for the timeline."""
    total_milestones: int = Field(..., description="Total milestones in period")
    major_events: int = Field(..., description="High-significance events")
    avg_monthly_milestones: float = Field(..., description="Average per month")
    date_range: dict = Field(..., description="{'start': date, 'end': date}")


class LifeArcResponse(BaseModel):
    """Response for Life Arc Timeline API."""
    milestones: List[Milestone] = Field(..., description="Chronological milestone list")
    timeline_summary: TimelineSummary = Field(..., description="Timeline statistics")
    eligibility_status: str = Field(default="eligible", description="eligible | ineligible | needs_more_data | check_failed")
    message: Optional[str] = Field(None, description="Explanation when not eligible")
    
    class Config:
        json_schema_extra = {
            "example": {
                "milestones": [
                    {
                        "date": "2026-08-07",
                        "type": "cycle_start",
                        "title": "Period Started",
                        "description": "New menstrual cycle began",
                        "significance": 0.6,
                        "icon": "flow",
                        "health_context": {
                            "cycle_day": 1,
                            "phase": "menstrual"
                        }
                    }
                ],
                "timeline_summary": {
                    "total_milestones": 24,
                    "major_events": 5,
                    "avg_monthly_milestones": 4,
                    "date_range": {
                        "start": "2026-03-07",
                        "end": "2026-09-07"
                    }
                }
            }
        }


# ============================================================================
# REMINDERS TAB Models
# ============================================================================

class ReminderStatus(str, Enum):
    """Status of a preventative health reminder."""
    NOT_STARTED = "not_started"
    OVERDUE = "overdue"
    DUE_SOON = "due_soon"
    SCHEDULED = "scheduled"
    UP_TO_DATE = "up_to_date"
    NOT_APPLICABLE = "not_applicable"


class HealthReminder(BaseModel):
    """Single preventative health reminder."""
    id: int = Field(..., description="Unique reminder ID")
    type_: str = Field(..., alias="type", description="Screening type (e.g., Mammogram, Bone Density)")
    status: ReminderStatus = Field(..., description="Current status")
    priority: str = Field(..., description="Priority level (critical, high, medium, low)")
    
    last_done: Optional[date] = Field(None, description="Date of last screening")
    due_date: Optional[date] = Field(None, description="Evidence-based due date")
    scheduled_date: Optional[date] = Field(None, description="If scheduled, the scheduled date")
    
    days_overdue: Optional[int] = Field(None, description="Days past due (if overdue)")
    days_until_due: Optional[int] = Field(None, description="Days until due (if upcoming)")
    days_until_scheduled: Optional[int] = Field(None, description="Days until scheduled")
    
    guideline: str = Field(..., description="Medical guideline for this screening")
    recommendation: str = Field(..., description="Recommended action")
    status_label: str = Field(..., description="Display label (Overdue, Due Soon, etc.)")
    status_color: str = Field(..., description="Color for UI (red, orange, green, blue)")
    
    class Config:
        populate_by_name = True


class MobilityStressMetric(BaseModel):
    """Mobility or stress-related reminder."""
    area: str = Field(..., description="Area of focus (e.g., 'Hip Flexibility')")
    score: float = Field(..., ge=0, le=100, description="Current score")
    status: str = Field(..., description="good, moderate, low")
    last_measured: date = Field(..., description="Last measurement date")
    recommendation: Optional[str] = Field(None, description="Suggested activity")


class RemindersSnapshot(BaseModel):
    """Summary of all reminders."""
    total_reminders: int
    not_started: int = 0
    overdue: int
    due_soon: int
    scheduled: int
    up_to_date: int
    not_applicable: int = 0


class PreventativeRemindersResponse(BaseModel):
    """Response for Preventative Health Reminders endpoint."""
    reminders: List[HealthReminder] = Field(..., description="Preventative health reminders")
    summary: RemindersSnapshot = Field(..., description="Summary statistics")
    eligibility_status: str = Field(default="eligible", description="eligible | ineligible | check_failed")
    message: Optional[str] = Field(None, description="Explanation when not eligible")
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    class Config:
        json_schema_extra = {
            "example": {
                "reminders": [
                    {
                        "id": 1,
                        "type": "Mammogram",
                        "status": "overdue",
                        "priority": "critical",
                        "last_done": "2024-06-15",
                        "due_date": "2026-06-15",
                        "days_overdue": 101,
                        "guideline": "Annual for ages 40+",
                        "recommendation": "Schedule immediately",
                        "status_label": "Overdue",
                        "status_color": "red"
                    },
                    {
                        "id": 2,
                        "type": "Bone Density Scan",
                        "status": "due_soon",
                        "priority": "high",
                        "last_done": "2025-01-20",
                        "due_date": "2026-10-20",
                        "days_until_due": 22,
                        "guideline": "Every 1-2 years for ages 50+",
                        "recommendation": "Schedule in next 2-3 weeks",
                        "status_label": "Due soon",
                        "status_color": "orange"
                    }
                ],
                "summary": {
                    "total_reminders": 9,
                    "overdue": 1,
                    "due_soon": 2,
                    "scheduled": 1,
                    "up_to_date": 5,
                    "not_applicable": 0
                }
            }
        }


class MobilityStressIndicatorsResponse(BaseModel):
    """Response for Mobility & Stress Indicators endpoint."""
    indicators: List[MobilityStressMetric] = Field(..., description="Mobility and stress metrics")
    overall_mobility_score: float = Field(..., ge=0, le=100, description="Average mobility score")
    overall_stress_status: str = Field(..., description="Overall stress status: good, moderate, needs_attention")
    eligibility_status: str = Field(default="eligible", description="eligible | ineligible | check_failed")
    message: Optional[str] = Field(None, description="Explanation when not eligible")
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    class Config:
        json_schema_extra = {
            "example": {
                "indicators": [
                    {
                        "area": "Hip Flexibility",
                        "score": 78,
                        "status": "good",
                        "last_measured": "2026-09-20",
                        "recommendation": "Continue current stretching routine"
                    },
                    {
                        "area": "Grip Strength",
                        "score": 82,
                        "status": "good",
                        "last_measured": "2026-09-18",
                        "recommendation": None
                    },
                    {
                        "area": "Balance Score",
                        "score": 65,
                        "status": "moderate",
                        "last_measured": "2026-09-15",
                        "recommendation": "Increase balance training exercises"
                    }
                ],
                "overall_mobility_score": 75,
                "overall_stress_status": "good"
            }
        }


class RemindersResponse(BaseModel):
    """Response for Reminders Tab API (combined - kept for backward compatibility)."""
    reminders: List[HealthReminder] = Field(..., description="Preventative health reminders")
    mobility_stress_reminders: List[MobilityStressMetric] = Field(
        default_factory=list,
        description="Mobility & stress indicators"
    )
    summary: RemindersSnapshot = Field(..., description="Summary statistics")
    eligibility_status: str = Field(default="eligible", description="eligible | ineligible | check_failed")
    data_completeness: float = Field(default=100, ge=0, le=100, description="% of available data sources being used")
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    class Config:
        json_schema_extra = {
            "example": {
                "reminders": [
                    {
                        "id": "mammogram_001",
                        "type": "Mammogram",
                        "status": "overdue",
                        "priority": 1,
                        "last_done": "2024-06-15",
                        "due_date": "2026-06-15",
                        "days_overdue": 101,
                        "guideline": "Annual for ages 40+",
                        "recommendation": "Schedule immediately",
                        "status_label": "Overdue",
                        "status_color": "red"
                    }
                ],
                "mobility_stress_reminders": [
                    {
                        "area": "Hip Flexibility",
                        "score": 78,
                        "status": "good",
                        "last_measured": "2026-09-20"
                    }
                ],
                "summary": {
                    "total_reminders": 12,
                    "overdue": 1,
                    "due_soon": 3,
                    "scheduled": 2,
                    "up_to_date": 6,
                    "not_applicable": 0
                }
            }
        }


# ============================================================================
# Combined Response (Single Endpoint for All 3 Tabs)
# ============================================================================

class LifelongThrivingAllTabsResponse(BaseModel):
    """Combined response if all 3 tabs requested in single call."""
    user_id: int
    vitality: VitalityResponse
    life_arc: LifeArcResponse
    reminders: RemindersResponse
    generated_at: datetime = Field(default_factory=datetime.now)
