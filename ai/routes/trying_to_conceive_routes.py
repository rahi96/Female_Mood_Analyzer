from fastapi import APIRouter, HTTPException

from ai.services.trying_to_conceive_service import fetch_trying_to_conceive_data


router = APIRouter()


@router.get("/trying-to-conceive")
async def trying_to_conceive_endpoint():
    try:
        return fetch_trying_to_conceive_data()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Trying to conceive failed: {exc}")
