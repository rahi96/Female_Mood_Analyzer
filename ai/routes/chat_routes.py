from fastapi import APIRouter, HTTPException

from ai.models.chat_models import (
    ChatHistoryRequest,
    ChatHistoryResponse,
    ChatResponse,
    ChatResponseRequest,
)
from ai.services.chat_service import generate_chat_response, get_chat_history


router = APIRouter()


@router.post("/chat/response", response_model=ChatResponse)
async def chat_response_endpoint(request: ChatResponseRequest):
    try:
        return generate_chat_response(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Chat response failed: {exc}")


@router.post("/chat/history", response_model=ChatHistoryResponse)
async def chat_history_endpoint(request: ChatHistoryRequest):
    try:
        return get_chat_history(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Chat history failed: {exc}")
