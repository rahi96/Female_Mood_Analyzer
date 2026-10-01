"""Pydantic models for Pregnancy & Postpartum API."""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import date, datetime


# ============================================================================
# PREGNANCY SUMMARY MODELS
# ============================================================================

class PregnancyAlert(BaseModel):
    """Alert for pregnancy-related monitoring."""
    message: str = Field(..., description="Alert message")
    severity: str = Field(..., description="low, medium, high")
    action_required: bool = Field(default=False)


class PregnancySummary(BaseModel):
    """Pregnancy summary with current status and journey tracking."""
    is_pregnant: bool = Field(..., description="Whether user is currently pregnant")
    current_week: int = Field(..., ge=0, le=42, description="Current pregnancy week (0-42, >40 = postpartum)")
    current_trimester: str = Field(..., description="First, Second, Third, or Postpartum")
    due_date: Optional[str] = Field(None, description="Expected due date (ISO format)")
    days_until_due: Optional[int] = Field(None, ge=0, description="Days remaining until due date")
    last_prenatal_visit: Optional[str] = Field(None, description="Date of last prenatal visit")
    next_appointment: Optional[str] = Field(None, description="Date of next scheduled appointment")
    health_status: str = Field(default="good", description="good, fair, needs_attention")
    alerts: List[PregnancyAlert] = Field(default_factory=list, description="Active pregnancy alerts")
    baby_development: str = Field(..., description="Narrative description of baby development at current week")
    your_body: str = Field(..., description="Narrative description of body changes at current week")
    nutrition_focus: str = Field(..., description="Personalized nutrition recommendations for current week")
    safe_exercises: str = Field(..., description="Safe exercise recommendations for current week")
    clinical_monitoring: List[Dict[str, str]] = Field(default_factory=list, description="Next 5 major clinical tests")
    clinical_warning_signs: str = Field(default="", description="Critical warning signs to seek immediate care for current week")
    pregnancy_status: str = Field(..., description="active_pregnancy, pregnancy_with_loss, postpartum_ready, or postpartum")
    requires_confirmation: bool = Field(default=False, description="Whether frontend should show confirmation popup")
    confirmation_needed_for: Optional[str] = Field(None, description="miscarriage or delivery (if requires_confirmation=True)")
    confirmation_message: Optional[str] = Field(None, description="Popup message to show user (if requires_confirmation=True)")


# ============================================================================
# PREGNANCY MILESTONES MODELS
# ============================================================================

class ClinicalTest(BaseModel):
    """Clinical test/screening with scheduled date."""
    name: str = Field(..., description="Test name (e.g., 'Glucose Tolerance Test')")
    week: str = Field(..., description="Week notation (e.g., 'W24')")
    date: str = Field(..., description="Scheduled date (e.g., 'Nov 8 (Today)')")


class PregnancyMilestones(BaseModel):
    """Complete pregnancy milestones for a specific week - UI-aligned format."""
    week: int = Field(..., ge=0, le=40, description="Pregnancy week 0-40")
    trimester: str = Field(..., description="First, Second, or Third")
    baby_development: str = Field(..., description="Narrative description of baby development")
    your_body: str = Field(..., description="Narrative description of body changes")
    nutrition_focus: str = Field(..., description="Narrative nutrition recommendations")
    safe_exercises: str = Field(..., description="Narrative safe exercise recommendations")
    clinical_monitoring: List[Dict[str, str]] = Field(..., description="Next 5 major clinical tests (unified view)")
    clinical_warning_signs: str = Field(..., description="Red flag warning signs to watch for")


# ============================================================================
# POSTPARTUM RECOVERY MODELS
# ============================================================================

class RecoveryMetrics(BaseModel):
    """Physical recovery metrics for postpartum."""
    physical_recovery_percent: Optional[int] = Field(None, ge=0, le=100, description="Overall physical recovery percentage (0-100%); null if no clinical screening recorded yet")
    hormonal_balance_percent: Optional[int] = Field(None, ge=0, le=100, description="Hormonal balance recovery percentage (0-100%); null if no clinical screening recorded yet")
    energy_level_percent: Optional[int] = Field(None, ge=0, le=100, description="Energy level percentage (0-100%); null if no wearable or logged data available")
    sleep_quality_percent: Optional[int] = Field(None, ge=0, le=100, description="Sleep quality percentage (0-100%); null if no wearable data available")
    energy_data_source: str = Field(default="no_data", description="wearable, health_log, or no_data")
    sleep_data_source: str = Field(default="no_data", description="wearable or no_data")
    recovery_data_source: str = Field(default="no_data", description="screening or no_data")
    hormonal_data_source: str = Field(default="no_data", description="screening or no_data")


class MentalHealth(BaseModel):
    """Postpartum mental health assessment."""
    mood_stability: int = Field(..., ge=0, le=100, description="Mood stability score")
    anxiety_level: int = Field(..., ge=0, le=10, description="Anxiety level 0-10")
    depression_screening: str = Field(..., description="low_risk, moderate_risk, high_risk")
    last_mood_entry: Optional[str] = Field(None, description="Last mood log date")
    mood_trend: str = Field(..., description="improving, stable, declining")
    supportive_resources: List[str] = Field(default_factory=list, description="Available support resources")


class PostpartumAlert(BaseModel):
    """Alert for postpartum monitoring."""
    type: str = Field(..., description="bleeding, infection, mental_health, pain, other")
    level: str = Field(..., description="low, moderate, high")
    message: str = Field(..., description="Alert message and recommended action")


class PostpartumRecovery(BaseModel):
    """Complete postpartum recovery overview."""
    postpartum_week: int = Field(..., ge=0, le=12, description="Weeks since delivery")
    delivery_method: str = Field(..., description="vaginal or cesarean")
    recovery_metrics: RecoveryMetrics
    mental_health: MentalHealth
    activity_level: str = Field(..., description="minimal, light, moderate, active")
    postpartum_alerts: List[PostpartumAlert] = Field(default_factory=list)
    next_follow_up: Optional[str] = Field(None, description="Date of next postpartum checkup")


# ============================================================================
# SUPPORT COMMUNITY MODELS
# ============================================================================

class SupportGroup(BaseModel):
    """Support community/group information."""
    id: int = Field(..., description="Group ID")
    name: str = Field(..., description="Group name")
    description: str = Field(..., description="Group description")
    life_stage: str = Field(..., description="pregnancy, postpartum, etc.")
    member_count: int = Field(..., ge=0, description="Total members in group")
    active_users_today: int = Field(..., ge=0, description="Active members today")
    latest_posts_count: int = Field(..., ge=0, description="Recent posts in this group")
    is_moderated: bool = Field(..., description="Whether group is professionally moderated")
    join_status: str = Field(..., description="joined, not_joined")
    created_at: Optional[str] = Field(None, description="Group creation date")


class SupportGroupResponse(BaseModel):
    """Response for support groups listing."""
    groups: List[SupportGroup] = Field(..., description="List of support groups")
    total_groups: int = Field(..., ge=0, description="Total number of groups")
    user_joined_count: int = Field(..., ge=0, description="Number of groups user has joined")


# ============================================================================
# REQUEST MODELS
# ============================================================================

class PregnancyRequest(BaseModel):
    """Request for pregnancy information."""
    user_id: int = Field(..., ge=1, description="User ID")


class PregnancyMilestonesRequest(BaseModel):
    """Request for specific pregnancy week milestones."""
    user_id: int = Field(..., ge=1, description="User ID")
    week: Optional[int] = Field(None, ge=0, le=40, description="Specific week (optional, defaults to current)")


class PostpartumRecoveryRequest(BaseModel):
    """Request for postpartum recovery data."""
    user_id: int = Field(..., ge=1, description="User ID")


class SupportGroupsRequest(BaseModel):
    """Request for support groups."""
    life_stage: str = Field(..., description="pregnancy or postpartum")
    limit: Optional[int] = Field(10, ge=1, le=50, description="Max groups to return")
    offset: Optional[int] = Field(0, ge=0, description="Pagination offset")
