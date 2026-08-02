from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from ai.models.pdf_summary_models import PdfSummaryResponse
from ai.services.pdf_summary_service import summarize_pdf, get_lab_reports_for_user


router = APIRouter()


def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    """Extract the raw token from an `Authorization: Bearer <token>` header."""
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return authorization


@router.get("/summarize-pdf", response_model=PdfSummaryResponse)
async def summarize_pdf_get(
    user_id: int = Query(..., description="User ID"),
    authorization: Optional[str] = Header(None, description="User's own Bearer token, forwarded to the backend"),
):
    try:
        return summarize_pdf(user_id, access_token=_extract_bearer_token(authorization))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF summary failed: {exc}")


@router.post("/summarize-pdf", response_model=PdfSummaryResponse)
async def summarize_pdf_post(
    user_id: int = Query(..., description="User ID"),
    authorization: Optional[str] = Header(None, description="User's own Bearer token, forwarded to the backend"),
):
    try:
        return summarize_pdf(user_id, access_token=_extract_bearer_token(authorization))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF summary failed: {exc}")


@router.get("/lab-reports")
async def list_lab_reports(user_id: int = Query(..., description="User ID")):
    """List all lab reports for a user."""
    try:
        return get_lab_reports_for_user(user_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch lab reports: {exc}")
