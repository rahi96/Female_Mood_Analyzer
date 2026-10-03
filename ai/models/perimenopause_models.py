"""Perimenopause & Menopause API models with UI-aligned responses."""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import date


# ============================================================================
# VASOMOTOR TRACKER MODELS - Hot Flashes & Night Sweats
# ============================================================================

class VasomotorEvent(BaseModel):
    """Individual hot flash or night sweat event."""
    event_date: date = Field(..., description="Date of event")
    event_time: Optional[str] = Field(None, description="Time in HH:MM format")
    event_type: str = Field(..., description="hot_flash, night_sweat, or chills")
    duration_minutes: Optional[int] = Field(None, ge=1, le=120, description="Event duration")
    severity: int = Field(..., ge=1, le=10, description="1-10 severity scale")
    trigger: Optional[str] = Field(None, description="Trigger (caffeine, stress, warm room, etc)")
    location: Optional[str] = Field(None, description="Body location (face, chest, full_body)")


class VasomotorTracker(BaseModel):
    """Vasomotor event summary and trends - UI Vasomotor Tracker view."""
    period: str = Field(..., description="7d, 30d, or 90d")
    start_date: date
    end_date: date
    
    # Summary Statistics
    total_events: int = Field(..., description="Total hot flashes + night sweats")
    avg_daily_frequency: float = Field(..., description="Average per day (e.g., 6.4)")
    avg_severity: float = Field(..., description="Average severity 1-10 (e.g., 7.2)")
    
    # Distribution by Type
    hot_flash_events: int = Field(..., description="Count of hot flashes")
    hot_flash_avg_severity: float
    night_sweat_events: int
    night_sweat_avg_severity: float
    
    # Time Analysis (for pie chart in UI)
    peak_times: List[Dict[str, int]] = Field(
        ..., 
        description="Times of day with frequency [{'time': '3-6 AM', 'frequency': 5}]"
    )
    
    # Triggers (for trigger analysis in UI)
    common_triggers: Dict[str, int] = Field(
        ...,
        description="Trigger counts {'caffeine': 8, 'stress': 6, 'spicy_food': 4}"
    )
    
    # Severity Distribution (for chart in UI)
    severity_distribution: Dict[str, int] = Field(
        ...,
        description="Count by severity range {'mild (1-3)': 5, 'moderate (4-7)': 25, 'severe (8-10)': 15}"
    )
    
    # Trend (for line chart in UI)
    trend: str = Field(..., description="improving, stable, or worsening")
    trend_description: str = Field(..., description="Natural language trend summary")
    
    # Raw Events
    events: List[VasomotorEvent] = Field(..., description="All events in period")


# ============================================================================
# SYMPTOM MATRIX MODELS - 12 Symptoms Heatmap
# ============================================================================

class SymptomEntry(BaseModel):
    """Single day's symptom entry for matrix."""
    log_date: date
    hot_flash: Optional[str] = Field(None, description="none, mild, moderate, severe")
    hot_flash_count: Optional[int] = Field(None, ge=0)
    night_sweat: Optional[str] = Field(None, description="none, mild, moderate, severe")
    sleep_disruption: Optional[str] = Field(None, description="none, mild, moderate, severe")
    sleep_hours: Optional[float] = Field(None, ge=0, le=24)
    mood: Optional[str] = Field(None, description="happy, neutral, irritable, anxious, sad")
    brain_fog: Optional[str] = Field(None, description="none, mild, moderate, severe")
    joint_pain: Optional[str] = Field(None, description="none, mild, moderate, severe")
    vaginal_dryness: Optional[str] = Field(None, description="none, mild, moderate, severe")
    weight_change_lbs: Optional[float] = Field(None, description="Change in pounds")
    energy_level: Optional[str] = Field(None, description="Very Low, Low, Moderate, High, Very High")
    headaches: Optional[str] = Field(None, description="none, mild, moderate, severe")
    fatigue: Optional[str] = Field(None, description="none, mild, moderate, severe")


class SymptomMatrix(BaseModel):
    """Symptom tracking matrix - UI Symptom Matrix heatmap view."""
    period: str = Field(..., description="7d, 30d, or 90d")
    start_date: date
    end_date: date
    
    # Daily Entries (rows in heatmap)
    entries: List[SymptomEntry] = Field(..., description="Day-by-day symptom data")
    
    # Frequency Analysis (which symptoms appear most often)
    symptom_frequency: Dict[str, float] = Field(
        ...,
        description="% occurrence {'hot_flash': 0.86, 'mood_swing': 0.79, 'sleep_disruption': 0.71}"
    )
    
    # Severity Analysis
    symptom_severity: Dict[str, str] = Field(
        ...,
        description="Average severity per symptom {'hot_flash': 'severe', 'mood': 'moderate'}"
    )
    
    # Symptom Correlations (which occur together) - with percentages
    symptom_correlations: List[Dict] = Field(
        ...,
        description="Correlation data [{'from': 'Hot Flash', 'to': 'Sleep', 'percentage': 87, 'description': '...'}]"
    )
    
    # Top Symptoms
    most_common_symptoms: List[str] = Field(
        ...,
        description="Top 3-5 symptoms by frequency"
    )
    
    # Overall Health Metrics
    avg_energy_level_percent: int = Field(..., ge=0, le=100, description="0-100 scale")
    avg_sleep_hours: float = Field(..., ge=0)
    avg_mood_stability_percent: int = Field(..., ge=0, le=100, description="Mood stability 0-100")
    
    # Trends
    symptom_trends: Dict[str, str] = Field(
        ...,
        description="Trend per symptom {'hot_flash': 'stable', 'anxiety': 'worsening'}"
    )


# ============================================================================
# MENOPAUSE STAGE MODELS
# ============================================================================

class MenopauseSummary(BaseModel):
    """Quick overview of menopause status - UI Dashboard view."""
    is_in_perimenopause: bool = Field(..., description="Current life stage")
    menopause_stage: str = Field(
        ..., 
        description="perimenopause, menopause, or postmenopause"
    )
    months_since_last_period: Optional[int] = Field(None, description="If known")
    months_in_current_stage: Optional[int] = Field(None, description="Duration")
    
    # Current Status
    last_period_date: Optional[str] = Field(None, description="ISO format date")
    cycle_status: str = Field(..., description="regular, irregular, or absent")
    
    # Symptom Overview
    primary_symptoms: List[str] = Field(..., description="Top 3 symptoms")
    symptom_severity_overview: str = Field(..., description="mild, moderate, or severe overall")
    
    # Quick Health Metrics
    avg_hot_flashes_per_day: float = Field(..., description="Last 7 days average")
    avg_sleep_hours: float = Field(..., description="Last 7 days average")
    mood_stability_percent: int = Field(..., ge=0, le=100)
    
    # Alert Status
    alert_status: str = Field(..., description="normal, warning, or critical")
    active_alerts: List[str] = Field(..., description="Current warning flags")
    
    # Recommendations
    recommended_actions: List[str] = Field(
        ...,
        description="Top 2-3 recommended actions"
    )


# ============================================================================
# CLINICAL EXPORT MODELS - PDF Report
# ============================================================================

class ClinicalExport(BaseModel):
    """Clinical report ready for export/sharing with healthcare provider."""
    export_date: str = Field(..., description="Export date (e.g., Sep 24, 2026)")
    period_covered: str = Field(..., description="Date range (e.g., Jul 15 - Sep 24, 2026)")
    
    # Menopause Classification
    menopause_stage: str = Field(..., description="perimenopause, menopause, or postmenopause")
    months_since_onset: Optional[int] = Field(None, description="If known")
    months_since_last_period: Optional[int] = Field(None, description="If applicable")
    
    # Vasomotor Summary
    vasomotor_events_total: int
    vasomotor_avg_frequency_per_day: float
    vasomotor_avg_severity: float = Field(..., ge=0, le=10)  # 0 = no events recorded
    vasomotor_trend: str = Field(..., description="improving, stable, or worsening")
    vasomotor_primary_triggers: List[str] = Field(..., description="Top 3 identified triggers")
    
    # Symptom Summary
    primary_symptoms: List[str] = Field(..., description="Top 5 symptoms")
    symptom_severity_breakdown: Dict[str, str] = Field(
        ...,
        description="Per-symptom severity"
    )
    
    # Health Metrics
    avg_sleep_hours: float
    sleep_quality: str = Field(..., description="poor, fair, good, or excellent")
    avg_mood_stability: int = Field(..., ge=0, le=100)
    weight_change_lbs: Optional[float] = Field(None, description="Over reporting period")
    
    # Clinical Recommendations (LLM-generated)
    clinical_recommendations: List[str] = Field(
        ...,
        description="Doctor-actionable recommendations"
    )
    
    # Lifestyle Recommendations (LLM-generated)
    lifestyle_recommendations: List[str] = Field(
        ...,
        description="Diet, exercise, sleep recommendations"
    )
    
    # Warning Flags
    warning_flags: List[str] = Field(..., description="Critical items requiring attention")
    
    # Suggested Clinical Tests
    suggested_tests: List[str] = Field(
        ...,
        description="FSH, TSH, Vitamin D, etc."
    )
    
    # Data Quality
    data_points_collected: int = Field(..., description="Total symptom entries")
    data_completeness_percent: int = Field(..., ge=0, le=100)


# ============================================================================
# INSIGHT RESPONSE MODEL - Combined Endpoint
# ============================================================================

class PerimenopauseInsights(BaseModel):
    """Combined insights endpoint response - flexible query-based response."""
    summary: MenopauseSummary
    vasomotor_tracker: Optional[VasomotorTracker] = Field(
        None,
        description="Included if ?include=vasomotor"
    )
    symptom_matrix: Optional[SymptomMatrix] = Field(
        None,
        description="Included if ?include=symptoms"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "summary": {
                    "is_in_perimenopause": True,
                    "menopause_stage": "perimenopause",
                    "primary_symptoms": ["hot_flash", "sleep_disruption", "mood_swings"]
                }
            }
        }
