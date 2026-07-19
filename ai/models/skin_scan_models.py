from typing import Optional

from pydantic import BaseModel, Field


class SkinScanMetrics(BaseModel):
    overall_score: int = Field(..., ge=0, le=100)
    hydration_score: int = Field(..., ge=0, le=100)
    redness_score: int = Field(..., ge=0, le=100)
    texture_score: int = Field(..., ge=0, le=100)
    glow_index: int = Field(..., ge=0, le=100)
    pore_health_score: int = Field(..., ge=0, le=100)
    elasticity_score: int = Field(..., ge=0, le=100)
    hydration_status: str
    redness_status: str
    texture_status: str
    glow_status: str
    pore_health_status: str
    elasticity_status: str
    neumera_insight: str


class SkinScanResponse(SkinScanMetrics):
    id: Optional[int] = None
    user_id: Optional[int] = None
    image_path: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
