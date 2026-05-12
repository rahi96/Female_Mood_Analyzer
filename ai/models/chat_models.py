from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: str


class ChatResponseRequest(BaseModel):
    user_id: str
    message: str = Field(..., min_length=1)
    session_id: Optional[str] = None


class ChatDataSummary(BaseModel):
    temperature_range: str
    data_points_analyzed: int


class ChatResponse(BaseModel):
    response: str
    session_id: str
    timestamp: str
    data_summary: ChatDataSummary


class ChatHistoryRequest(BaseModel):
    user_id: str
    session_id: Optional[str] = None


class ChatHistoryResponse(BaseModel):
    history: list[ChatMessage]
    total_messages: int
    session_id: Optional[str] = None


class ConversationRecord(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: str


class TemperatureStats(BaseModel):
    temperature_range: str
    data_points_analyzed: int
    values: list[float] = []
    dates: list[str] = []
    raw: Any = None
