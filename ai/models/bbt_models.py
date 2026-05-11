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
