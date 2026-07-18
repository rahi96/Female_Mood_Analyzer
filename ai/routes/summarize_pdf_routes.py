from fastapi import APIRouter, HTTPException

from ai.models.pdf_summary_models import PdfSummaryResponse
from ai.services.pdf_summary_service import summarize_pdf


router = APIRouter()


@router.get("/summarize-pdf", response_model=PdfSummaryResponse)
async def summarize_pdf_endpoint():
    try:
        return summarize_pdf()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF summary failed: {exc}")
