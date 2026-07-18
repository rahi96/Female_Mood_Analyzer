from typing import Literal, Optional

from pydantic import BaseModel, Field


class PdfSummaryRequest(BaseModel):
    pdf_path: Optional[str] = Field(default=None, min_length=1)


class HormoneBiomarker(BaseModel):
    name: str
    value: str
    reference_range: str
    status: str
    interpretation: str


class HormoneBiomarkers(BaseModel):
    needs_attention: list[HormoneBiomarker]
    normal_results: list[HormoneBiomarker]


class HormoneAiInsights(BaseModel):
    cross_data_context: list[str]
    estradiol_elevation: str
    cortisol_near_ceiling: str
    hormonal_balance: str


class HormoneNextSteps(BaseModel):
    recommendations: list[str]
    medical_disclaimer: str


class HormonalPanelSummary(BaseModel):
    panel: Literal["Hormonal Panel"] = "Hormonal Panel"
    biomarkers: HormoneBiomarkers
    ai_insights: HormoneAiInsights
    next_steps: HormoneNextSteps


class PdfSummaryResponse(BaseModel):
    source_path: str
    content_type: str
    file_size_bytes: int
    text_extracted: bool
    summary: HormonalPanelSummary