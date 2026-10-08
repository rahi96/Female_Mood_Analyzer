import logging

from fastapi import APIRouter, HTTPException, Query

from ai.services.trying_to_conceive_service import fetch_trying_to_conceive_data

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/trying-to-conceive")
async def trying_to_conceive_endpoint(user_id: int = Query(..., gt=0, description="User ID")):
    try:
        return fetch_trying_to_conceive_data(user_id)
    except Exception:
        logger.exception("trying_to_conceive_endpoint failed for user_id=%s", user_id)
        raise HTTPException(status_code=500, detail="Internal error")
