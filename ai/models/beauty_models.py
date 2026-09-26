from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class BeautyRequest(BaseModel):
    user_id: int
    days: int = 30
    include_correlations: bool = True

class FindingItem(BaseModel):
    finding: str
    status: str
    badge: str
    score: float

class HistoryItem(BaseModel):
    date: str
    day_of_week: str
    score: float
    days_ago: int
    status_label: str = "Unknown"  # e.g., "Radiant", "Glowing", "Good"

class SleepSkinData(BaseModel):
    correlation_detected: bool
    correlation_strength: float
    correlation_direction: str
    insight: str
    chart_data: List[Dict[str, Any]] = Field(default_factory=list)

class PhaseData(BaseModel):
    label: str
    score: float
    description: str

class CyclePhases(BaseModel):
    phase_breakdown: Dict[str, PhaseData]
    best_phase: str
    worst_phase: str

class Correlations(BaseModel):
    sleep_skin: SleepSkinData
    cycle_phases: CyclePhases

class TodayScan(BaseModel):
    id: int
    user_id: int
    image_path: str
    overall_score: float
    hydration_score: float
    redness_score: float
    texture_score: float
    glow_index: float
    pore_health_score: float
    elasticity_score: float
    hydration_status: str
    redness_status: str
    texture_status: str
    glow_status: str
    pore_health_status: str
    elasticity_status: str
    neumera_insight: str
    created_at: str
    updated_at: str
    status_label: str
    findings: List[FindingItem]
    score_change: Optional[float] = None
    comparison_text: Optional[str] = None

class AIInsights(BaseModel):
    overall_assessment: str
    key_focus_areas: List[str]
    recommendations: List[str]
    confidence_score: int

class BeautyResponse(BaseModel):
    today: TodayScan
    history: List[HistoryItem]
    correlations: Correlations
    tabs: List[str] = Field(default_factory=lambda: ["Today", "History", "Correlations"], description="UI tab labels")