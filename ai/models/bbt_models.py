from pydantic import BaseModel
from typing import List, Optional


class TemperatureReading(BaseModel):
    date: str
    temp: float
    time: Optional[str] = None


class BackendInnerData(BaseModel):
    heightTemperature: float
    lowestTemperature: float
    currentPhase: str
    averageTemperature: float
    last30DaysReport: List[dict]


class BackendData(BaseModel):
    success: bool
    data: BackendInnerData


class CycleInsightsRequest(BaseModel):
    user_id: str


class CycleInsightsResponse(BaseModel):
    cycle_phase: str
    message: str


class DailyTipRequest(BaseModel):
    user_id: str


class DailyTipResponse(BaseModel):
    title: str
    tip: str


class DailyVerseRequest(BaseModel):
    user_id: str


class DailyVerseResponse(BaseModel):
    verse: str
    reference: str
