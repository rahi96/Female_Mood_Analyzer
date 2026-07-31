from fastapi import APIRouter, Depends, HTTPException, Query

from ai.models.cycle_engine_v1_models import (
    BBTLogRequest,
    ConfirmDayRequest,
    ConsentRequest,
    ModeRequest,
    OPKUILogRequest,
)
from ai.services import cycle_engine_v1_service as service


router = APIRouter()


def current_user_id() -> int:
    return service.current_user_id()


def _run(handler, *args, **kwargs):
    try:
        return handler(*args, **kwargs)
    except service.ConsentRequiredError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cycle Engine v1 failed: {exc}")


@router.get("/engine/summary")
async def engine_summary(user_id: int = Depends(current_user_id)):
    return _run(service.engine_summary, user_id)


@router.get("/engine/signal-status")
async def engine_signal_status(user_id: int = Depends(current_user_id)):
    return _run(service.engine_signal_status, user_id)


@router.get("/engine/discrepancy-note")
async def engine_discrepancy_note(user_id: int = Depends(current_user_id)):
    return _run(service.engine_discrepancy_note, user_id)


@router.get("/calendar/month")
async def calendar_month(month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), user_id: int = Depends(current_user_id)):
    return _run(service.calendar_month, user_id, month)


@router.post("/calendar/confirm-day")
async def calendar_confirm_day(payload: ConfirmDayRequest, user_id: int = Depends(current_user_id)):
    return _run(service.calendar_confirm_day, user_id, payload)


@router.get("/calendar/next-period")
async def calendar_next_period(user_id: int = Depends(current_user_id)):
    return _run(service.calendar_next_period, user_id)


@router.post("/bbt/log")
async def bbt_log(payload: BBTLogRequest, user_id: int = Depends(current_user_id)):
    return _run(service.bbt_log, user_id, payload)


@router.get("/bbt/chart")
async def bbt_chart(cycle_day_range: str = "1-28", user_id: int = Depends(current_user_id)):
    return _run(service.bbt_chart, user_id, cycle_day_range)


@router.get("/bbt/coverline-status")
async def bbt_coverline_status(user_id: int = Depends(current_user_id)):
    return _run(service.bbt_coverline_status, user_id)


@router.get("/opk/ui")
async def opk_ui(user_id: int = Depends(current_user_id)):
    return _run(service.opk_ui, user_id)


@router.post("/opk/ui")
async def opk_ui_log(payload: OPKUILogRequest, user_id: int = Depends(current_user_id)):
    return _run(service.opk_ui_log, user_id, payload)


@router.post("/reconciliation/recompute")
async def reconciliation_recompute(user_id: int = Depends(current_user_id)):
    return _run(service.reconciliation_recompute, user_id)


@router.get("/reconciliation/current")
async def reconciliation_current(user_id: int = Depends(current_user_id)):
    return _run(service.reconciliation_current, user_id)


@router.get("/ttc/surge-banner")
async def ttc_surge_banner(user_id: int = Depends(current_user_id)):
    return _run(service.ttc_surge_banner, user_id)


@router.get("/ttc/priority-map")
async def ttc_priority_map(user_id: int = Depends(current_user_id)):
    return _run(service.ttc_priority_map, user_id)


@router.get("/ttc/priority-banner")
async def ttc_priority_banner(user_id: int = Depends(current_user_id)):
    return _run(service.ttc_priority_banner, user_id)


@router.get("/awareness/current-phase")
async def awareness_current_phase(user_id: int = Depends(current_user_id)):
    return _run(service.awareness_current_phase, user_id)


@router.get("/awareness/hormone-levels")
async def awareness_hormone_levels(user_id: int = Depends(current_user_id)):
    return _run(service.awareness_hormone_levels, user_id)


@router.get("/awareness/phase-education")
async def awareness_phase_education(user_id: int = Depends(current_user_id)):
    return _run(service.awareness_phase_education, user_id)


@router.get("/awareness/four-phase-wheel")
async def awareness_four_phase_wheel(user_id: int = Depends(current_user_id)):
    return _run(service.awareness_four_phase_wheel, user_id)


@router.get("/avoiding-pregnancy/consent-status")
async def avoiding_pregnancy_consent_status(user_id: int = Depends(current_user_id)):
    return _run(service.consent_status, user_id)


@router.post("/avoiding-pregnancy/consent")
async def avoiding_pregnancy_consent(payload: ConsentRequest, user_id: int = Depends(current_user_id)):
    return _run(service.set_consent, user_id, payload)


@router.post("/mode")
async def set_mode(payload: ModeRequest, user_id: int = Depends(current_user_id)):
    return _run(service.set_mode, user_id, payload)