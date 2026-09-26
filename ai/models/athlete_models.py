"""Pydantic models for Athlete Performance API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class HRVMetric(BaseModel):
    """Heart rate variability metric."""
    value: int = Field(..., ge=0, description="HRV 7-day average in milliseconds")
    unit: str = "ms"
    trend: int = Field(..., description="Change from previous day (negative=declining)")
    status: str = Field(..., description="good | warning | poor")


class SleepMetric(BaseModel):
    """Sleep quality metric."""
    percentage: int = Field(..., ge=0, le=100, description="Sleep percentage (hours / 8 * 100)")
    trend: int = Field(..., description="Change from previous day (positive=improving)")
    status: str = Field(..., description="good | fair | poor")


class RecoveryMetric(BaseModel):
    """Recovery status metric."""
    percentage: int = Field(..., ge=0, le=100, description="Recovery percentage (0-100)")
    trend: int = Field(..., description="Change from previous day (positive=recovering)")
    status: str = Field(..., description="high | low | moderate")


class TrainingLoadMetric(BaseModel):
    """Training load/strain metric."""
    value: float = Field(..., ge=0, description="Training load in AU (arbitrary units)")
    unit: str = "AU"
    trend: int = Field(..., description="Change from previous day (negative=decreasing load)")
    status: str = Field(..., description="low | moderate | high")


class Metrics(BaseModel):
    """All performance metrics."""
    hrv: HRVMetric
    sleep: SleepMetric
    recovery: RecoveryMetric
    training_load: TrainingLoadMetric


class FatigueAlert(BaseModel):
    """Individual fatigue alert."""
    type: str = Field(..., description="overtraining_risk | recovery_deficit | cumulative_fatigue | sleep_debt")
    level: str = Field(..., description="low | moderate | high")
    message: str = Field(default="", description="Optional alert message (empty for compact format)")


class CycleInfo(BaseModel):
    """Cycle phase information."""
    phase: str = Field(..., description="menstrual | follicular | ovulatory | luteal | unknown")
    cycle_day: int = Field(..., ge=0, le=100, description="Current day of cycle (0 if unknown)")
    days_to_next_phase: int = Field(..., ge=0, le=100, description="Days until next phase")
    phase_boost: int = Field(..., ge=-15, le=15, description="Readiness score adjustment from phase")
    phase_description: str


class PhaseRecommendation(BaseModel):
    """Phase-based workout recommendation."""
    workout_type: str = Field(..., description="high_intensity | strength | endurance | recovery")
    intensity_level: str = Field(..., description="maximum | high | moderate | low")
    suggested_workouts: list[str]


class AthleteReadinessResponse(BaseModel):
    """Complete athlete performance readiness response."""
    date: str = Field(..., description="ISO date of readiness assessment")
    readiness_score: int = Field(..., ge=0, le=100, description="Overall readiness 0-100")
    readiness_level: str = Field(..., description="Peak Ready | Ready | Adequate | Fatigued | Depleted")
    
    # Quick stat cards displayed below readiness info
    hrv: HRVMetric = Field(..., description="Heart rate variability metric for quick display")
    recovery: RecoveryMetric = Field(..., description="Recovery status metric for quick display")
    training_load: TrainingLoadMetric = Field(..., description="Training load metric for quick display")
    
    # Full metrics object
    metrics: Metrics
    fatigue_alerts: list[FatigueAlert]
    cycle_info: CycleInfo
    recommendations: PhaseRecommendation
    
    next_update: str = Field(..., description="ISO timestamp of next scheduled update")


class AthleteReadinessRequest(BaseModel):
    """Request for athlete readiness."""
    user_id: int = Field(..., ge=1, description="User ID")

class CycleTrainingFocus(BaseModel):
    """Compact training focus recommendations for specific menstrual cycle phase."""
    cycle_phase: str = Field(..., description="menstrual | follicular | ovulation | luteal")
    phase_day: str = Field(..., description="Current cycle day (e.g., 'D14')")
    focus: str = Field(..., description="Training focus in 3-5 words")
    recommendations: list[str] = Field(..., description="4-5 actionable recommendations, max 8 words each")


class UnifiedAthletePerformance(BaseModel):
    """Unified Athlete Performance API combining readiness score and cycle-based training."""
    # Readiness data
    date: str = Field(..., description="ISO date of assessment")
    readiness_score: int = Field(..., ge=0, le=100, description="Overall readiness 0-100")
    readiness_level: str = Field(..., description="Peak Ready | Ready | Adequate | Fatigued | Depleted")
    
    # Quick metrics
    hrv: HRVMetric = Field(..., description="Heart rate variability")
    recovery: RecoveryMetric = Field(..., description="Recovery status")
    training_load: TrainingLoadMetric = Field(..., description="Training load")
    
    # Full metrics
    metrics: Metrics
    fatigue_alerts: list[FatigueAlert]
    cycle_info: CycleInfo
    recommendations: PhaseRecommendation
    
    # Cycle-based training data
    training_focus: CycleTrainingFocus = Field(..., description="Cycle-phase specific training recommendations")
    
    next_update: str = Field(..., description="ISO timestamp of next scheduled update")