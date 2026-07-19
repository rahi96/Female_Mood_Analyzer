from fastapi import APIRouter, HTTPException

from ai.models.skin_scan_models import SkinScanResponse
from ai.services.skin_scan_service import analyze_skin_scan


router = APIRouter()


@router.get("/skin-scan", response_model=SkinScanResponse)
@router.post("/skin-scan", response_model=SkinScanResponse)
async def skin_scan_endpoint():
    try:
        return analyze_skin_scan()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Skin scan analysis failed: {exc}")
