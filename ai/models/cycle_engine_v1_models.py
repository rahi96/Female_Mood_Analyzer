from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


CycleMode = Literal["trying_to_conceive", "cycle_awareness", "avoiding_pregnancy"]
CyclePhase = Literal["menstrual", "follicular", "ovulatory", "luteal"]
BBTFlag = Literal["illness", "low_sleep", "alcohol", "restless_sleep"]
OPKResult = Literal["negative", "rising", "positive"]
MucusType = Literal["dry", "sticky", "creamy", "watery", "egg_white"]


class ConfirmDayRequest(BaseModel):
    date: date
    is_day_n: bool


class BBTLogRequest(BaseModel):
    date: date
    temperature_f: float = Field(..., ge=90, le=110)
    time: str
    flags: list[BBTFlag] = Field(default_factory=list)


class OPKLogRequest(BaseModel):
    date: date
    result: OPKResult
    lh_value: float | None = None


class ConsentRequest(BaseModel):
    consented: bool
    consent_version: str


class ModeRequest(BaseModel):
    mode: CycleMode


class OPKUILogRequest(BaseModel):
    """Request to log OPK result and/or mucus type, returns full UI."""
    date: Optional[date] = None  # Defaults to today if not provided
    opk_result: Optional[OPKResult] = None
    lh_value: Optional[float] = None
    mucus_type: Optional[MucusType] = None


class CalendarAllMonthRequest(BaseModel):
    """Request to get calendar for a specific month."""
    date: date


class BBTUILogRequest(BaseModel):
    """Request to log BBT reading, returns full UI.
    
    All fields are optional:
    - date: Defaults to today if null/omitted
    - temperature_f: Required to actually log (90-110°F range)
    - time: Defaults to current time if null/omitted (format: "HH:MM" like "06:30")
    - flags: Optional BBT flags (illness, low_sleep, alcohol, restless_sleep)
    """
    date: Optional[date] = None
    temperature_f: Optional[float] = Field(default=None, ge=90, le=110)
    time: Optional[str] = None
    flags: Optional[list[BBTFlag]] = None