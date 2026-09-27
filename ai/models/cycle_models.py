"""Pydantic models for Cycle & Fertility endpoint."""

from typing import Optional, List
from pydantic import BaseModel, Field, validator


class CycleRequest(BaseModel):
    """Request model for /api/cycle-overview endpoint."""
    
    user_id: int = Field(
        ..., 
        gt=0, 
        description="User ID (must be positive integer)"
    )
    mode: str = Field(
        default="standard",
        description="Cycle tracking mode: 'standard', 'tracking', 'premium'",
        pattern="^(standard|tracking|premium)$"
    )
    include_bbt: bool = Field(
        default=False,
        description="Include BBT (Basal Body Temperature) analysis"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": 2,
                "mode": "standard",
                "include_bbt": False
            }
        }


class CycleMetrics(BaseModel):
    """Current cycle metrics."""
    
    current_cycle_day: int = Field(..., ge=1, le=50, description="Current day in cycle")
    cycle_length: int = Field(..., ge=20, le=50, description="Cycle length in days")
    current_phase: str = Field(..., description="Current phase: menstrual, follicular, ovulatory, luteal")
    period_start_date: Optional[str] = Field(None, description="ISO format date")
    period_end_date: Optional[str] = Field(None, description="ISO format date")
    predicted_ovulation_day: Optional[int] = Field(None, ge=1, le=50)
    confirmed_ovulation_day: Optional[int] = Field(None, ge=1, le=50)
    is_confirmed: bool = Field(default=False, description="Is ovulation confirmed")
    
    class Config:
        json_schema_extra = {
            "example": {
                "current_cycle_day": 15,
                "cycle_length": 28,
                "current_phase": "follicular",
                "period_start_date": "2026-09-08",
                "period_end_date": "2026-09-12",
                "predicted_ovulation_day": 14,
                "confirmed_ovulation_day": None,
                "is_confirmed": False
            }
        }


class FertileWindow(BaseModel):
    """Fertile window calculation."""
    
    fertile_start_day: Optional[int] = Field(None, ge=1, le=50, description="First fertile day")
    fertile_end_day: Optional[int] = Field(None, ge=1, le=50, description="Last fertile day")
    days_until_ovulation: Optional[int] = Field(None, description="Days until predicted ovulation")
    ovulation_probability: float = Field(default=0.0, ge=0.0, le=100.0, description="Confidence percentage")
    is_fertile_now: bool = Field(default=False, description="Is user in fertile window today")
    
    class Config:
        json_schema_extra = {
            "example": {
                "fertile_start_day": 10,
                "fertile_end_day": 16,
                "days_until_ovulation": 5,
                "ovulation_probability": 92.5,
                "is_fertile_now": True
            }
        }


class BBTAnalysis(BaseModel):
    """BBT (Basal Body Temperature) analysis."""
    
    temperature_entries: int = Field(default=0, description="Number of temperature readings")
    avg_follicular_temp: Optional[float] = Field(None, description="Average temp in follicular phase")
    avg_luteal_temp: Optional[float] = Field(None, description="Average temp in luteal phase")
    temp_rise_detected: bool = Field(default=False, description="Temperature shift detected")
    temp_rise_date: Optional[str] = Field(None, description="ISO format date of temp rise")
    coverline_value: Optional[float] = Field(None, description="BBT coverline (threshold)")
    prediction_confidence: float = Field(default=0.0, ge=0.0, le=100.0, description="Confidence in BBT prediction")
    
    class Config:
        json_schema_extra = {
            "example": {
                "temperature_entries": 28,
                "avg_follicular_temp": 36.4,
                "avg_luteal_temp": 36.8,
                "temp_rise_detected": True,
                "temp_rise_date": "2026-09-22",
                "coverline_value": 36.65,
                "prediction_confidence": 95.0
            }
        }


class CycleHistory(BaseModel):
    """Historical cycle data."""
    
    previous_cycles_count: int = Field(default=0, description="Number of completed cycles in history")
    avg_cycle_length: Optional[int] = Field(None, description="Average cycle length")
    avg_period_length: Optional[int] = Field(None, description="Average period length")
    cycle_regularity_score: float = Field(default=0.0, ge=0.0, le=100.0, description="Regularity percentage")
    
    class Config:
        json_schema_extra = {
            "example": {
                "previous_cycles_count": 6,
                "avg_cycle_length": 28,
                "avg_period_length": 5,
                "cycle_regularity_score": 85.0
            }
        }


class CycleOverviewResponse(BaseModel):
    """Response model for /api/cycle-overview endpoint."""
    
    current_metrics: CycleMetrics = Field(..., description="Current cycle metrics")
    fertile_window: FertileWindow = Field(..., description="Fertile window analysis")
    bbt_analysis: Optional[BBTAnalysis] = Field(None, description="BBT analysis if available")
    cycle_history: CycleHistory = Field(..., description="Historical cycle data")
    hormone_trends: List[dict] = Field(
        default_factory=list,
        description="Numeric hormone trends derived from latest cervical mucus log"
    )
    ai_insights: dict = Field(
        default_factory=dict,
        description="Claude AI generated insights"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "current_metrics": {
                    "current_cycle_day": 15,
                    "cycle_length": 28,
                    "current_phase": "follicular"
                },
                "fertile_window": {
                    "fertile_start_day": 10,
                    "fertile_end_day": 16,
                    "is_fertile_now": True,
                    "ovulation_probability": 92.5
                },
                "bbt_analysis": None,
                "cycle_history": {
                    "previous_cycles_count": 6,
                    "avg_cycle_length": 28
                },
                "ai_insights": {
                    "cycle_assessment": "Your cycle is regular and predictable",
                    "optimal_timing": "Peak fertility window is in 5 days",
                    "recommendations": ["Track symptoms", "Monitor temperature"]
                }
            }
        }
