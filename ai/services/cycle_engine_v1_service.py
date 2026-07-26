"""Cycle Engine v1 API.

GET responses fetch backend user profile + snapshot, then Claude analyzes that data
and generates the JSON response. Deterministic helpers remain as fallbacks.
Hormone levels are modeled from cycle phase (not lab measurements).
"""

from __future__ import annotations

import hashlib
import json
import time
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from ai.config import settings
from ai.models.cycle_engine_v1_models import (
    BBTLogRequest,
    ConfirmDayRequest,
    ConsentRequest,
    ModeRequest,
    OPKLogRequest,
)
from ai.utils.llm_call import llm_call


SPERM_VIABILITY_DAYS = 5
EGG_VIABILITY_HOURS = 24
OPK_WINDOW_LEAD_DAYS = 4
CONSENT_VERSION_DEFAULT = "2026-07-cycle-engine-v1"
RETRYABLE_LLM_STATUS_CODES = {429, 500, 502, 503, 529}
LLM_RETRY_DELAYS_SECONDS = (0.5, 1.0)
MAX_CONTEXT_CHARS = 14000

AI_SYSTEM_PROMPT = (
    "You are a careful female cycle-engine analysis assistant. "
    "Analyze only the provided user_profile, snapshot, and local_logs JSON. "
    "Do not invent temperatures, OPK results, mucus logs, period dates, or ovulation days "
    "that are not supported by the data. "
    "Do not diagnose or prescribe. "
    "Return valid JSON only — no markdown, no code fences, no preamble."
)

AI_COPY_SYSTEM_PROMPT = (
    "You write short, calm, clear health-adjacent UI copy for a cycle-tracking app. "
    "Use only the facts provided. Do not invent numbers, diagnoses, or medical advice. "
    "Return plain text only: no markdown, no preamble, 1-2 sentences max."
)

HORMONE_BY_PHASE = {
    "menstrual": {"estrogen": "low", "progesterone": "low", "lh": "low"},
    "follicular": {"estrogen": "rising", "progesterone": "low", "lh": "low"},
    "ovulatory": {"estrogen": "high", "progesterone": "low", "lh": "high"},
    "luteal": {"estrogen": "declining", "progesterone": "high", "lh": "declining"},
}

PHASE_WHEEL_STATUS = {
    "menstrual": "Low",
    "follicular": "Rising",
    "ovulatory": "Peak",
    "luteal": "Falling",
}

PHASE_EDUCATION_FACTS = {
    "menstrual": "Period days; estrogen and progesterone are low; energy often lower; BBT typically at baseline.",
    "follicular": "Post-period rise toward ovulation; estrogen rising; energy often improving; BBT still relatively low.",
    "ovulatory": "Fertile peak window; LH surge then ovulation; estrogen high then dips; BBT starts rising after ovulation.",
    "luteal": "Post-ovulation; progesterone dominant; BBT elevated ~0.4F; energy may soften toward next period.",
}

_AI_CACHE: dict[str, str] = {}
_AI_JSON_CACHE: dict[str, dict[str, Any]] = {}
_PHASE_EDU_CACHE: dict[str, dict[str, str]] = {}
_USER_STATE: dict[int, dict[str, Any]] = {}


class ConsentRequiredError(Exception):
    pass


# ---------------------------------------------------------------------------
# Public auth stub
# ---------------------------------------------------------------------------

def current_user_id() -> int:
    profile, _ = _try_get_backend_json(settings.CYCLE_ENGINE_PROFILE_URL)
    return _extract_user_id(profile) or 4


# ---------------------------------------------------------------------------
# Engine (§2)
# ---------------------------------------------------------------------------

def engine_summary(user_id: int) -> dict[str, Any]:
    state = _cycle_state(user_id)
    _require_consent_if_needed(state)
    reconciliation = _recompute_reconciliation(state)
    fertile_start, fertile_end = _fertile_window(reconciliation["calendar_predicted_day"])
    fallback = {
        "cycle_summary": _cycle_summary(state),
        "fertile_window": {
            "start_day": fertile_start,
            "end_day": fertile_end,
            "label": f"Days {fertile_start}-{fertile_end}",
            "peak_day": reconciliation.get("final_confirmed_day") or reconciliation["calendar_predicted_day"],
            "peak_source": reconciliation.get("final_source"),
            "mucus_peak_day": None,
            "lh_surge_day": reconciliation.get("lh_surge_day"),
            "bbt_confirmed_day": reconciliation.get("bbt_confirmed_day"),
        },
        "reliability": _reliability(state),
        "reconciliation": reconciliation,
        "sources": state["sources"],
        "backend_errors": state["backend_errors"],
    }
    return _ai_endpoint_response(
        "engine_summary",
        state,
        (
            "Build the Engine dashboard summary JSON with keys: "
            "cycle_summary (user_id, current_cycle_day, current_phase, avg_cycle_length, "
            "cycle_variance_days, current_mode), "
            "fertile_window (start_day, end_day, label, peak_day, peak_source, "
            "mucus_peak_day, lh_surge_day, bbt_confirmed_day), "
            "reliability (level low|moderate|high, completed_cycles, text), "
            "reconciliation (calendar_predicted_day, bbt_confirmed_day, lh_surge_day, "
            "final_confirmed_day, final_source, offset_days, luteal_phase_length). "
            "Use profile + snapshot + local_logs. Prefer confirmed BBT/LH over calendar alone."
        ),
        fallback,
    )


def engine_signal_status(user_id: int) -> dict[str, Any]:
    state = _cycle_state(user_id)
    _require_consent_if_needed(state)
    today = _today()
    reconciliation = _recompute_reconciliation(state)
    fallback = {
        "signals": [
            _signal_card(
                "Calendar",
                _has_period_log_today(state, today),
                f"Predicts ovulation Day {reconciliation['calendar_predicted_day']}",
            ),
            _signal_card("OPK / LH", _has_log_today(state["opk_logs"], today), _opk_status_text(state, today)),
            _signal_card("BBT", _has_log_today(state["bbt_logs"], today), _bbt_status_text(state)),
            _signal_card("Mucus", _has_log_today(state["mucus_logs"], today), _mucus_status_text(state, today)),
        ]
    }
    return _ai_endpoint_response(
        "engine_signal_status",
        state,
        (
            "Return JSON {signals:[...]} with exactly 4 signals in order: "
            "Calendar, OPK / LH, BBT, Mucus. Each item needs signal, logged_today (bool), "
            "status_text (short UI string based on today's logs / confirmation state)."
        ),
        fallback,
        max_tokens=900,
    )


def engine_discrepancy_note(user_id: int) -> dict[str, Any]:
    state = _cycle_state(user_id)
    _require_consent_if_needed(state)
    reconciliation = _recompute_reconciliation(state)
    calendar_day = reconciliation.get("calendar_predicted_day")
    bbt_day = reconciliation.get("bbt_confirmed_day")
    if not calendar_day or not bbt_day or calendar_day == bbt_day:
        fallback = {
            "active": False,
            "message": "Calendar and confirmed ovulation signals are currently aligned.",
        }
    else:
        offset = bbt_day - calendar_day
        fallback = {
            "active": True,
            "message": (
                f"Calendar predicted Day {calendar_day}, BBT confirmed Day {bbt_day}. "
                f"This {abs(offset)}-day offset has been recorded to refine future predictions."
            ),
        }
    return _ai_endpoint_response(
        "engine_discrepancy_note",
        state,
        (
            "Return JSON {active:bool, message:str}. "
            "If calendar_predicted_day and bbt_confirmed_day both exist and differ, active=true "
            "and message explains the offset calmly in 1-2 sentences. "
            "Otherwise active=false with an aligned message."
        ),
        fallback,
        max_tokens=400,
    )


# ---------------------------------------------------------------------------
# Calendar (§3)
# ---------------------------------------------------------------------------

def calendar_month(user_id: int, month: str) -> dict[str, Any]:
    state = _cycle_state(user_id)
    _require_consent_if_needed(state)
    year, month_number = [int(part) for part in month.split("-")]
    _, days_in_month = monthrange(year, month_number)
    reconciliation = _recompute_reconciliation(state)
    fertile_start, fertile_end = _fertile_window(reconciliation["calendar_predicted_day"])
    period_days = set(_period_cycle_days(state))
    cycle_length = int(round(state["avg_cycle_length"]))
    days = []
    for day_number in range(1, days_in_month + 1):
        current = date(year, month_number, day_number)
        cycle_day = _cycle_day_for_date(state, current)
        in_cycle = 1 <= cycle_day <= cycle_length + 7
        tag = "none"
        if in_cycle:
            if cycle_day in period_days:
                tag = "period"
            elif reconciliation.get("final_confirmed_day") == cycle_day:
                tag = "ovulation_confirmed"
            elif reconciliation["calendar_predicted_day"] == cycle_day:
                tag = "ovulation_predicted"
            elif fertile_start <= cycle_day <= fertile_end:
                tag = "fertile_window"
            elif _phase_for_day(cycle_day, state["avg_cycle_length"]) == "luteal":
                tag = "luteal"
        days.append(
            {
                "date": current.isoformat(),
                "cycle_day": cycle_day if in_cycle else None,
                "tag": tag,
            }
        )
    fallback = {"month": month, "days": days}
    return _ai_endpoint_response(
        f"calendar_month:{month}",
        state,
        (
            f"Build calendar month JSON for {month}. "
            "Return {month, days:[{date, cycle_day|null, tag}]}. "
            "tag must be one of: period, fertile_window, ovulation_predicted, "
            "ovulation_confirmed, luteal, none. "
            "Include every day of the month. Use profile/snapshot period and ovulation data."
        ),
        fallback,
        max_tokens=2500,
    )


def calendar_confirm_day(user_id: int, payload: ConfirmDayRequest) -> dict[str, Any]:
    state = _user_state(user_id)
    state["confirmations"].append({"date": payload.date.isoformat(), "is_day_n": payload.is_day_n})
    if not payload.is_day_n:
        return {
            "accepted": False,
            "requires_cycle_start_correction": True,
            "message": (
                "Please correct the cycle start date so phase and fertile-window "
                "predictions can be recalculated."
            ),
        }
    state["cycle_start_date"] = payload.date.isoformat()
    reconciliation_recompute(user_id)
    _clear_ai_caches()
    return {"accepted": True, "current_cycle_day": 1, "recomputed": True}


def calendar_next_period(user_id: int) -> dict[str, Any]:
    state = _cycle_state(user_id)
    lengths = _last_cycle_lengths(state)
    rolling_avg = round(sum(lengths) / len(lengths), 1) if lengths else float(state["avg_cycle_length"])
    variance = max(lengths) - min(lengths) if lengths else int(state["cycle_variance_days"])
    predicted = state["cycle_start_date"] + timedelta(days=round(rolling_avg))
    fallback = {
        "predicted_date": predicted.isoformat(),
        "days_until": max(0, (predicted - _today()).days),
        "rolling_avg_length": rolling_avg,
        "variance_days": variance,
        "within_normal_range": variance <= 7,
        "last_4_cycle_lengths": lengths[-4:],
    }
    return _ai_endpoint_response(
        "calendar_next_period",
        state,
        (
            "Return JSON with predicted_date (YYYY-MM-DD), days_until, rolling_avg_length, "
            "variance_days, within_normal_range (bool), last_4_cycle_lengths (list of ints). "
            "Derive from profile/snapshot cycle history when available."
        ),
        fallback,
        max_tokens=700,
    )


# ---------------------------------------------------------------------------
# BBT (§4)
# ---------------------------------------------------------------------------

def bbt_log(user_id: int, payload: BBTLogRequest) -> dict[str, Any]:
    state = _user_state(user_id)
    entry = {
        "id": _next_id(state["bbt_logs"]),
        "user_id": user_id,
        "date": payload.date.isoformat(),
        "temperature_f": payload.temperature_f,
        "logged_at_time": payload.time,
        "flags": list(payload.flags),
    }
    state["bbt_logs"] = [log for log in state["bbt_logs"] if log.get("date") != entry["date"]]
    state["bbt_logs"].append(entry)
    cycle_state = _cycle_state(user_id)
    coverline = _coverline_status(cycle_state)
    if coverline.get("confirmed") and coverline.get("confirmed_day"):
        state["bbt_confirmed_day"] = coverline["confirmed_day"]
    reconciliation = reconciliation_recompute(user_id)
    _clear_ai_caches()
    return {
        "stored": True,
        "log": entry,
        "coverline_status": coverline,
        "reconciliation": reconciliation,
    }


def bbt_chart(user_id: int, cycle_day_range: str = "1-28") -> dict[str, Any]:
    state = _cycle_state(user_id)
    _require_consent_if_needed(state)
    start_day, end_day = _parse_day_range(cycle_day_range)
    coverline = _coverline_status(state)
    points = []
    for log in sorted(state["bbt_logs"], key=lambda item: item["date"]):
        cycle_day = _cycle_day_for_date(state, _parse_date(log["date"]))
        if cycle_day < start_day or cycle_day > end_day:
            continue
        points.append(
            {
                "day": cycle_day,
                "date": log["date"],
                "temperature_f": log["temperature_f"],
                "is_excluded": bool(log.get("flags")),
                "flags": log.get("flags") or [],
            }
        )
    confirmed_day = coverline.get("confirmed_day")
    luteal_length = None
    if confirmed_day:
        luteal_length = max(0, int(round(state["avg_cycle_length"])) - confirmed_day)
    fallback = {
        "points": points,
        "coverline_value": coverline.get("coverline_temp"),
        "confirmed_ovulation_day": confirmed_day,
        "luteal_phase_length": luteal_length,
        "phase_label": "Normal",
        "cycle_day_range": {"start": start_day, "end": end_day},
    }
    return _ai_endpoint_response(
        f"bbt_chart:{cycle_day_range}",
        state,
        (
            f"Return BBT chart JSON for cycle days {start_day}-{end_day}: "
            "{points:[{day,date,temperature_f,is_excluded,flags}], coverline_value, "
            "confirmed_ovulation_day, luteal_phase_length, phase_label, "
            "cycle_day_range:{start,end}}. "
            "Coverline = highest of prior 6 unflagged low temps; confirm after 3 days "
            ">= 0.2F above coverline. Only use temperatures present in the data."
        ),
        fallback,
    )


def bbt_coverline_status(user_id: int) -> dict[str, Any]:
    state = _cycle_state(user_id)
    _require_consent_if_needed(state)
    status = _coverline_status(state)
    if status.get("confirmed") and status.get("confirmed_day"):
        user = _user_state(user_id)
        user["bbt_confirmed_day"] = status["confirmed_day"]
        _recompute_reconciliation(state)
    return _ai_endpoint_response(
        "bbt_coverline_status",
        state,
        (
            "Return JSON {coverline_temp, days_above_coverline_streak, confirmed, confirmed_day}. "
            "Apply coverline rules on BBT logs from profile/snapshot/local_logs only."
        ),
        status,
        max_tokens=500,
    )


# ---------------------------------------------------------------------------
# OPK (§5)
# ---------------------------------------------------------------------------

def opk_testing_window(user_id: int) -> dict[str, Any]:
    state = _cycle_state(user_id)
    _require_consent_if_needed(state)
    reconciliation = _recompute_reconciliation(state)
    peak = reconciliation["calendar_predicted_day"]
    window_start = max(1, peak - OPK_WINDOW_LEAD_DAYS)
    window_end = peak
    current_day = state["current_cycle_day"]
    if current_day < window_start:
        window_status = "not_open"
    elif current_day > window_end:
        window_status = "closed"
    else:
        window_status = "open"
    fallback = {
        "window_start_day": window_start,
        "window_end_day": window_end,
        "predicted_peak_day": peak,
        "window_status": window_status,
    }
    return _ai_endpoint_response(
        "opk_testing_window",
        state,
        (
            "Return JSON {window_start_day, window_end_day, predicted_peak_day, "
            "window_status: not_open|open|closed}. "
            "Window typically opens ~4 days before predicted ovulation."
        ),
        fallback,
        max_tokens=400,
    )


def opk_log(user_id: int, payload: OPKLogRequest) -> dict[str, Any]:
    state = _user_state(user_id)
    cycle_state = _cycle_state(user_id)
    reconciliation = _recompute_reconciliation(cycle_state)
    peak = reconciliation["calendar_predicted_day"]
    window_start = max(1, peak - OPK_WINDOW_LEAD_DAYS)
    window_end = peak
    cycle_day = _cycle_day_for_date(cycle_state, payload.date)
    outside_window = cycle_day < window_start or cycle_day > window_end
    note = {
        "negative": "LH not elevated",
        "rising": "LH rising",
        "positive": "LH surge detected",
    }[payload.result]
    entry = {
        "id": _next_id(state["opk_logs"]),
        "user_id": user_id,
        "date": payload.date.isoformat(),
        "result": payload.result,
        "lh_value": payload.lh_value,
        "note": note,
        "outside_window": outside_window,
        "affects_prediction": not outside_window or payload.result == "positive",
    }
    state["opk_logs"] = [log for log in state["opk_logs"] if log.get("date") != entry["date"]]
    state["opk_logs"].append(entry)
    if payload.result == "positive" and entry["affects_prediction"]:
        state["lh_surge_day"] = cycle_day
        state["lh_surge_at"] = _utc_now().isoformat()
    reconciliation = reconciliation_recompute(user_id)
    _clear_ai_caches()
    return {
        "stored": True,
        "log": entry,
        "outside_window": outside_window,
        "affects_prediction": entry["affects_prediction"],
        "act_now": payload.result == "positive" and not outside_window,
        "reconciliation": reconciliation,
    }


def opk_today_status(user_id: int) -> dict[str, Any]:
    state = _cycle_state(user_id)
    _require_consent_if_needed(state)
    today = _today()
    # Use deterministic window for fallback to avoid nested AI calls.
    reconciliation = _recompute_reconciliation(state)
    peak = reconciliation["calendar_predicted_day"]
    window_start = max(1, peak - OPK_WINDOW_LEAD_DAYS)
    window_end = peak
    current_day = state["current_cycle_day"]
    if current_day < window_start:
        window_status = "not_open"
    elif current_day > window_end:
        window_status = "closed"
    else:
        window_status = "open"
    today_log = next((log for log in state["opk_logs"] if log.get("date") == today.isoformat()), None)
    fallback = {
        "date": today.isoformat(),
        "logged": today_log is not None,
        "result": today_log.get("result") if today_log else None,
        "lh_value": today_log.get("lh_value") if today_log else None,
        "note": today_log.get("note") if today_log else "Not yet logged today",
        "outside_window": window_status != "open",
        "window_status": window_status,
    }
    return _ai_endpoint_response(
        "opk_today_status",
        state,
        (
            "Return today's OPK status JSON: "
            "{date, logged, result, lh_value, note, outside_window, window_status}. "
            "Base note on actual OPK logs in the data."
        ),
        fallback,
        max_tokens=500,
    )


# ---------------------------------------------------------------------------
# Reconciliation (§6)
# ---------------------------------------------------------------------------

def reconciliation_recompute(user_id: int) -> dict[str, Any]:
    state = _cycle_state(user_id)
    return _recompute_reconciliation(state, persist=True)


def reconciliation_current(user_id: int) -> dict[str, Any]:
    state = _cycle_state(user_id)
    _require_consent_if_needed(state)
    fallback = _recompute_reconciliation(state)
    return _ai_endpoint_response(
        "reconciliation_current",
        state,
        (
            "Return OvulationReconciliation JSON: user_id, cycle_id, calendar_predicted_day, "
            "bbt_confirmed_day, lh_surge_day, final_confirmed_day, final_source, offset_days, "
            "luteal_phase_length. Priority for final day: BBT > LH surge (+1 day) > calendar."
        ),
        fallback,
        max_tokens=700,
    )


# ---------------------------------------------------------------------------
# Trying to Conceive (§7)
# ---------------------------------------------------------------------------

def ttc_surge_banner(user_id: int) -> dict[str, Any]:
    state = _cycle_state(user_id)
    _require_consent_if_needed(state)
    reconciliation = _recompute_reconciliation(state)
    coverline = _coverline_status(state)
    surge_at = state.get("lh_surge_at")
    active = False
    hours_remaining = 0
    if surge_at and not coverline.get("confirmed"):
        elapsed = (_utc_now() - _parse_datetime(surge_at)).total_seconds() / 3600
        if 0 <= elapsed <= 36:
            active = True
            hours_remaining = max(0, int(round(36 - elapsed)))
    message = (
        f"LH surge window is open — about {hours_remaining} hours remain in this fertile window."
        if active
        else "No active LH surge window right now."
    )
    fallback = {
        "active": active,
        "message": message,
        "hours_remaining_estimate": hours_remaining,
        "cycle_day": state["current_cycle_day"],
        "lh_surge_day": reconciliation.get("lh_surge_day"),
    }
    return _ai_endpoint_response(
        "ttc_surge_banner",
        state,
        (
            "Return TTC surge banner JSON: "
            "{active, message, hours_remaining_estimate, cycle_day, lh_surge_day}. "
            "Active only when LH surge is recent (~36h) and BBT has not confirmed yet. "
            "Message should be calm and actionable, based on the data."
        ),
        fallback,
        max_tokens=500,
    )


def ttc_priority_map(user_id: int) -> dict[str, Any]:
    state = _cycle_state(user_id)
    _require_consent_if_needed(state)
    reconciliation = _recompute_reconciliation(state)
    peak = reconciliation.get("final_confirmed_day") or reconciliation["calendar_predicted_day"]
    lh_day = reconciliation.get("lh_surge_day")
    ranges = [
        {
            "start_day": max(1, peak - SPERM_VIABILITY_DAYS),
            "end_day": max(1, peak - 1),
            "label": "sperm_viability_window",
            "priority": "moderate",
        },
    ]
    if lh_day:
        ranges.append(
            {
                "start_day": lh_day,
                "end_day": lh_day,
                "label": "lh_surge_day",
                "priority": "high",
            }
        )
    ranges.append(
        {
            "start_day": peak,
            "end_day": peak,
            "label": "predicted_ovulation_window",
            "priority": "highest",
        }
    )
    ranges.append(
        {
            "start_day": peak + 1,
            "end_day": int(round(state["avg_cycle_length"])),
            "label": "post_ovulation",
            "priority": "low",
        }
    )
    fallback = {"cycle_day": state["current_cycle_day"], "ranges": ranges}
    return _ai_endpoint_response(
        "ttc_priority_map",
        state,
        (
            "Return JSON {cycle_day, ranges:[{start_day,end_day,label,priority}]}. "
            "Priorities: sperm viability ~5 days before ovulation = moderate; "
            "LH surge day = high; ovulation day = highest; post-ovulation = low."
        ),
        fallback,
        max_tokens=800,
    )


def ttc_priority_banner(user_id: int) -> dict[str, Any]:
    state = _cycle_state(user_id)
    _require_consent_if_needed(state)
    reconciliation = _recompute_reconciliation(state)
    peak = reconciliation.get("final_confirmed_day") or reconciliation["calendar_predicted_day"]
    current_day = state["current_cycle_day"]
    if current_day == peak:
        priority, label = "highest", "predicted_ovulation_window"
    elif reconciliation.get("lh_surge_day") == current_day:
        priority, label = "high", "lh_surge_day"
    elif peak - SPERM_VIABILITY_DAYS <= current_day < peak:
        priority, label = "moderate", "sperm_viability_window"
    else:
        priority, label = "low", "outside_priority_window"
    fallbacks = {
        "highest": "This is your highest priority moment — act within the next 24 hours.",
        "high": "Priority is high today — your fertile window is peaking.",
        "moderate": "This is a moderate-priority fertile day — timing still matters.",
        "low": "Fertility priority is low right now.",
    }
    fallback = {
        "priority": priority,
        "label": label,
        "cycle_day": current_day,
        "message": fallbacks[priority],
    }
    return _ai_endpoint_response(
        "ttc_priority_banner",
        state,
        (
            "Return JSON {priority, label, cycle_day, message}. "
            "Choose the highest current priority from the user's cycle data and write one calm sentence."
        ),
        fallback,
        max_tokens=500,
    )


# ---------------------------------------------------------------------------
# Cycle Awareness (§8)
# ---------------------------------------------------------------------------

def awareness_current_phase(user_id: int) -> dict[str, Any]:
    state = _cycle_state(user_id)
    _require_consent_if_needed(state)
    phase = state["current_phase"]
    day_range = _phase_day_range(phase, state["avg_cycle_length"])
    notes = {
        "menstrual": "Estrogen and progesterone are typically low during menses.",
        "follicular": "Estrogen is typically rising as the body prepares for ovulation.",
        "ovulatory": "LH and estrogen are typically peaking around ovulation.",
        "luteal": "Progesterone is typically dominant after ovulation.",
    }
    fallback = {
        "phase": phase,
        "day_range": day_range,
        "dominant_hormone_note": notes[phase],
        "current_cycle_day": state["current_cycle_day"],
        "energy": "Declining" if phase in {"menstrual", "luteal"} else "Rising",
        "skin": "May breakout" if phase == "luteal" else "Clearer",
        "mood": "Relaxed/Inward" if phase == "luteal" else "Steady",
    }
    return _ai_endpoint_response(
        "awareness_current_phase",
        state,
        (
            "Return current phase JSON: "
            "{phase, day_range, dominant_hormone_note, current_cycle_day, energy, skin, mood}. "
            "Derive phase from profile/snapshot cycle day. energy/skin/mood are qualitative UI labels."
        ),
        fallback,
        max_tokens=600,
    )


def awareness_hormone_levels(user_id: int) -> dict[str, Any]:
    """Modeled from phase — not measured lab hormone data."""
    state = _cycle_state(user_id)
    _require_consent_if_needed(state)
    levels = HORMONE_BY_PHASE[state["current_phase"]]
    fallback = {
        **levels,
        "modeled": True,
        "source": "cycle_phase_lookup",
        "note": "Qualitative hormone display is derived from cycle phase, not lab measurements.",
    }
    return _ai_endpoint_response(
        "awareness_hormone_levels",
        state,
        (
            "Return modeled hormone levels JSON: "
            "{estrogen, progesterone, lh, modeled:true, source, note}. "
            "Values must be low|rising|high|declining. "
            "These are phase-modeled qualitative values, NOT lab measurements."
        ),
        fallback,
        max_tokens=400,
    )


def awareness_phase_education(user_id: int) -> dict[str, Any]:
    state = _cycle_state(user_id)
    _require_consent_if_needed(state)
    phase = state["current_phase"]
    fallback_notes = {
        "bbt_note": "BBT usually stays lower before ovulation and rises after ovulation.",
        "energy_note": "Energy often tracks estrogen — lower in menses, rising mid-cycle.",
        "hormone_note": PHASE_EDUCATION_FACTS[phase],
        "focus_note": "Use this phase to notice patterns without over-interpreting single days.",
    }
    fallback = {"phase": phase, **fallback_notes, "cached": False}
    result = _ai_endpoint_response(
        f"awareness_phase_education:{phase}",
        state,
        (
            f"Current phase is {phase}. Return JSON "
            "{phase, bbt_note, energy_note, hormone_note, focus_note}. "
            "Each note 1 short sentence grounded in the user's cycle context."
        ),
        fallback,
        max_tokens=700,
    )
    if result.get("ai_generated"):
        _PHASE_EDU_CACHE[phase] = {
            "bbt_note": result.get("bbt_note", ""),
            "energy_note": result.get("energy_note", ""),
            "hormone_note": result.get("hormone_note", ""),
            "focus_note": result.get("focus_note", ""),
        }
    return result


def awareness_four_phase_wheel(user_id: int) -> dict[str, Any]:
    state = _cycle_state(user_id)
    _require_consent_if_needed(state)
    current = state["current_phase"]
    avg = state["avg_cycle_length"]
    phases = []
    for phase in ("menstrual", "follicular", "ovulatory", "luteal"):
        phases.append(
            {
                "phase": phase,
                "day_range": _phase_day_range(phase, avg),
                "status": PHASE_WHEEL_STATUS[phase],
                "is_current": phase == current,
            }
        )
    fallback = {"current_phase": current, "phases": phases}
    return _ai_endpoint_response(
        "awareness_four_phase_wheel",
        state,
        (
            "Return 4-phase wheel JSON: "
            "{current_phase, phases:[{phase, day_range, status, is_current}]}. "
            "status one-word labels like Low/Rising/Peak/Falling. Mark only current phase true."
        ),
        fallback,
        max_tokens=700,
    )


# ---------------------------------------------------------------------------
# Avoiding pregnancy (§9) + mode (§10)
# ---------------------------------------------------------------------------

def consent_status(user_id: int) -> dict[str, Any]:
    state = _user_state(user_id)
    consent = state.get("consent") or {}
    return {
        "has_consented": bool(consent.get("consented")),
        "consent_version": consent.get("consent_version") or CONSENT_VERSION_DEFAULT,
        "consented_at": consent.get("consented_at"),
    }


def set_consent(user_id: int, payload: ConsentRequest) -> dict[str, Any]:
    state = _user_state(user_id)
    state["consent"] = {
        "consented": payload.consented,
        "consent_version": payload.consent_version,
        "consented_at": _utc_now().isoformat() if payload.consented else None,
    }
    return consent_status(user_id)


def set_mode(user_id: int, payload: ModeRequest) -> dict[str, Any]:
    state = _user_state(user_id)
    if payload.mode == "avoiding_pregnancy":
        consent = state.get("consent") or {}
        if not consent.get("consented"):
            raise ConsentRequiredError(
                "Consent required before enabling avoiding_pregnancy mode. "
                "Complete the consent modal first."
            )
        if consent.get("consent_version") != CONSENT_VERSION_DEFAULT and not consent.get("consented"):
            raise ConsentRequiredError("Consent version outdated. Please re-consent.")
    state["current_mode"] = payload.mode
    return {"current_mode": payload.mode, "updated": True}


# ---------------------------------------------------------------------------
# State + domain helpers
# ---------------------------------------------------------------------------

def _user_state(user_id: int) -> dict[str, Any]:
    if user_id not in _USER_STATE:
        _USER_STATE[user_id] = {
            "bbt_logs": [],
            "opk_logs": [],
            "mucus_logs": [],
            "period_logs": [],
            "confirmations": [],
            "current_mode": "cycle_awareness",
            "consent": {"consented": False, "consent_version": CONSENT_VERSION_DEFAULT, "consented_at": None},
            "cycle_start_date": None,
            "bbt_confirmed_day": None,
            "lh_surge_day": None,
            "lh_surge_at": None,
            "offset_days": 0,
            "reconciliation": None,
        }
    return _USER_STATE[user_id]


def _cycle_state(user_id: int) -> dict[str, Any]:
    user = _user_state(user_id)
    profile, profile_error = _try_get_backend_json(settings.CYCLE_ENGINE_PROFILE_URL)
    snapshot, snapshot_error = _try_get_backend_json(settings.CYCLE_ENGINE_SNAPSHOT_URL)

    backend_periods = _extract_period_logs(snapshot, profile, user_id)
    backend_bbt = _extract_bbt_logs(snapshot, user_id)
    backend_opk = _extract_opk_logs(snapshot, user_id)
    backend_mucus = _extract_mucus_logs(snapshot, user_id)

    period_logs = _merge_logs(backend_periods, user["period_logs"], key="start_date")
    bbt_logs = _merge_logs(backend_bbt, user["bbt_logs"], key="date")
    opk_logs = _merge_logs(backend_opk, user["opk_logs"], key="date")
    mucus_logs = _merge_logs(backend_mucus, user["mucus_logs"], key="date")

    cycle_start = _resolve_cycle_start(user, period_logs, snapshot, profile)
    avg_length = _extract_avg_cycle_length(snapshot, profile, period_logs)
    variance = _extract_variance(snapshot, profile, period_logs)
    current_day = max(1, (_today() - cycle_start).days + 1)
    if current_day > int(round(avg_length)) + 10:
        current_day = ((current_day - 1) % max(1, int(round(avg_length)))) + 1

    offset = int(user.get("offset_days") or 0)
    calendar_predicted = max(8, int(round(avg_length)) - 14 + offset)

    coverline_preview = _coverline_from_logs(bbt_logs, cycle_start)
    bbt_confirmed = user.get("bbt_confirmed_day") or coverline_preview.get("confirmed_day")
    lh_surge = user.get("lh_surge_day")

    phase = _phase_for_day(current_day, avg_length, bbt_confirmed or calendar_predicted)

    state = {
        "user_id": user_id,
        "cycle_id": f"{user_id}-{cycle_start.isoformat()}",
        "cycle_start_date": cycle_start,
        "current_cycle_day": current_day,
        "current_phase": phase,
        "avg_cycle_length": avg_length,
        "cycle_variance_days": variance,
        "current_mode": user["current_mode"],
        "consent": user["consent"],
        "period_logs": period_logs,
        "bbt_logs": bbt_logs,
        "opk_logs": opk_logs,
        "mucus_logs": mucus_logs,
        "calendar_predicted_day": calendar_predicted,
        "bbt_confirmed_day": bbt_confirmed,
        "lh_surge_day": lh_surge,
        "lh_surge_at": user.get("lh_surge_at"),
        "offset_days": offset,
        "sources": {
            "user_profile": settings.CYCLE_ENGINE_PROFILE_URL,
            "snapshot": settings.CYCLE_ENGINE_SNAPSHOT_URL,
        },
        "backend_errors": {
            k: v
            for k, v in {
                "user_profile": profile_error,
                "snapshot": snapshot_error,
            }.items()
            if v
        },
        "profile": profile,
        "snapshot": snapshot,
        "_user": user,
    }
    return state


def _cycle_summary(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": state["user_id"],
        "current_cycle_day": state["current_cycle_day"],
        "current_phase": state["current_phase"],
        "avg_cycle_length": state["avg_cycle_length"],
        "cycle_variance_days": state["cycle_variance_days"],
        "current_mode": state["current_mode"],
    }


def _reliability(state: dict[str, Any]) -> dict[str, Any]:
    completed = len(_last_cycle_lengths(state))
    if completed >= 6:
        level = "high"
        text = f"High — based on {completed} cycles of data."
    elif completed >= 3:
        level = "moderate"
        text = f"Moderate — based on {completed} cycles of data, improving with each logged cycle."
    else:
        level = "low"
        cycle_word = "cycle" if completed == 1 else "cycles"
        text = f"Low — based on {completed} {cycle_word} of data so far."
    return {"level": level, "completed_cycles": completed, "text": text}


def _require_consent_if_needed(state: dict[str, Any]) -> None:
    if state["current_mode"] != "avoiding_pregnancy":
        return
    consent = state.get("consent") or {}
    if not consent.get("consented"):
        raise ConsentRequiredError(
            "Consent required for avoiding_pregnancy mode. Complete the consent modal first."
        )


def _recompute_reconciliation(state: dict[str, Any], persist: bool = False) -> dict[str, Any]:
    calendar_day = int(state["calendar_predicted_day"])
    bbt_day = state.get("bbt_confirmed_day")
    lh_day = state.get("lh_surge_day")

    if bbt_day:
        final_day = int(bbt_day)
        final_source = "bbt"
    elif lh_day:
        final_day = int(lh_day) + 1
        final_source = "lh_surge"
    else:
        final_day = calendar_day
        final_source = "calendar"

    offset = 0
    if bbt_day:
        offset = int(bbt_day) - calendar_day

    luteal_phase_length = None
    if final_day:
        luteal_phase_length = max(0, int(round(state["avg_cycle_length"])) - int(final_day))

    reconciliation = {
        "user_id": state["user_id"],
        "cycle_id": state["cycle_id"],
        "calendar_predicted_day": calendar_day,
        "bbt_confirmed_day": int(bbt_day) if bbt_day else None,
        "lh_surge_day": int(lh_day) if lh_day else None,
        "final_confirmed_day": final_day,
        "final_source": final_source,
        "offset_days": offset,
        "luteal_phase_length": luteal_phase_length,
    }
    if persist:
        user = state.get("_user") or _user_state(state["user_id"])
        user["offset_days"] = offset
        user["bbt_confirmed_day"] = reconciliation["bbt_confirmed_day"]
        user["lh_surge_day"] = reconciliation["lh_surge_day"]
        user["reconciliation"] = reconciliation
    return reconciliation


def _fertile_window(peak_day: int) -> tuple[int, int]:
    end = int(peak_day)
    start = max(1, end - 5)
    return start, end


def _coverline_status(state: dict[str, Any]) -> dict[str, Any]:
    return _coverline_from_logs(state["bbt_logs"], state["cycle_start_date"])


def _coverline_from_logs(bbt_logs: list[dict[str, Any]], cycle_start: date) -> dict[str, Any]:
    usable = []
    for log in sorted(bbt_logs, key=lambda item: item["date"]):
        if log.get("flags"):
            continue
        cycle_day = ( _parse_date(log["date"]) - cycle_start ).days + 1
        if cycle_day < 1:
            continue
        usable.append({"day": cycle_day, "temperature_f": float(log["temperature_f"])})

    if len(usable) < 7:
        return {
            "coverline_temp": None,
            "days_above_coverline_streak": 0,
            "confirmed": False,
            "confirmed_day": None,
        }

    # Coverline = highest of prior 6 low (pre-shift) temps.
    # Use first 6 usable temps as the pre-shift baseline set.
    baseline = usable[:6]
    coverline = max(item["temperature_f"] for item in baseline)
    threshold = coverline + 0.2

    streak = 0
    confirmed = False
    confirmed_day = None
    for item in usable[6:]:
        if item["temperature_f"] >= threshold:
            streak += 1
            if streak >= 3 and not confirmed:
                confirmed = True
                confirmed_day = item["day"] - 2
        else:
            streak = 0

    return {
        "coverline_temp": round(coverline, 2),
        "days_above_coverline_streak": streak,
        "confirmed": confirmed,
        "confirmed_day": confirmed_day,
    }


def _phase_for_day(cycle_day: int, avg_length: float, ovulation_day: int | None = None) -> str:
    ov_day = ovulation_day or max(8, int(round(avg_length)) - 14)
    if cycle_day <= 5:
        return "menstrual"
    if cycle_day < ov_day:
        return "follicular"
    if cycle_day <= ov_day + 1:
        return "ovulatory"
    return "luteal"


def _phase_day_range(phase: str, avg_length: float) -> str:
    ov_day = max(8, int(round(avg_length)) - 14)
    end = int(round(avg_length))
    ranges = {
        "menstrual": "Days 1-5",
        "follicular": f"Days 6-{ov_day - 1}",
        "ovulatory": f"Days {ov_day}-{ov_day + 1}",
        "luteal": f"Days {ov_day + 2}-{end}",
    }
    return ranges[phase]


def _cycle_day_for_date(state: dict[str, Any], value: date) -> int:
    return (value - state["cycle_start_date"]).days + 1


def _period_cycle_days(state: dict[str, Any]) -> list[int]:
    days: list[int] = []
    for log in state["period_logs"]:
        start = _parse_date(log["start_date"])
        end = _parse_date(log["end_date"]) if log.get("end_date") else start + timedelta(days=4)
        current = start
        while current <= end:
            days.append(_cycle_day_for_date(state, current))
            current += timedelta(days=1)
    if not days:
        days = list(range(1, 6))
    return days


def _last_cycle_lengths(state: dict[str, Any]) -> list[int]:
    starts = sorted({_parse_date(log["start_date"]) for log in state["period_logs"]})
    lengths: list[int] = []
    for index in range(1, len(starts)):
        lengths.append((starts[index] - starts[index - 1]).days)
    if not lengths:
        snapshot_lengths = _dig(state.get("snapshot"), ["cycle_lengths", "last_cycle_lengths", "lengths"])
        if isinstance(snapshot_lengths, list):
            lengths = [int(item) for item in snapshot_lengths if str(item).isdigit() or isinstance(item, (int, float))]
    if not lengths:
        lengths = [int(round(state["avg_cycle_length"]))]
    return lengths[-4:]


def _has_log_today(logs: list[dict[str, Any]], today: date) -> bool:
    return any(log.get("date") == today.isoformat() for log in logs)


def _has_period_log_today(state: dict[str, Any], today: date) -> bool:
    for log in state["period_logs"]:
        start = _parse_date(log["start_date"])
        end = _parse_date(log["end_date"]) if log.get("end_date") else start + timedelta(days=4)
        if start <= today <= end:
            return True
    return False


def _signal_card(name: str, logged_today: bool, status_text: str) -> dict[str, Any]:
    return {
        "signal": name,
        "logged_today": logged_today,
        "status_text": status_text if logged_today or "Predicts" in status_text or "Confirmed" in status_text else "Not yet logged today",
    }


def _opk_status_text(state: dict[str, Any], today: date) -> str:
    today_log = next((log for log in state["opk_logs"] if log.get("date") == today.isoformat()), None)
    if today_log:
        return today_log.get("note") or str(today_log.get("result"))
    if state.get("lh_surge_day"):
        return f"LH surge recorded Day {state['lh_surge_day']}"
    return "Not yet logged today"


def _bbt_status_text(state: dict[str, Any]) -> str:
    coverline = _coverline_status(state)
    if coverline.get("confirmed") and coverline.get("confirmed_day"):
        return f"Confirmed shift Day {coverline['confirmed_day']}"
    if _has_log_today(state["bbt_logs"], _today()):
        return "Logged today"
    return "Not yet logged today"


def _mucus_status_text(state: dict[str, Any], today: date) -> str:
    today_log = next((log for log in state["mucus_logs"] if log.get("date") == today.isoformat()), None)
    if today_log:
        return f"Logged as {today_log.get('type')}"
    return "Not yet logged today"


# ---------------------------------------------------------------------------
# AI analysis from backend profile + snapshot
# ---------------------------------------------------------------------------

def _clear_ai_caches() -> None:
    _AI_CACHE.clear()
    _AI_JSON_CACHE.clear()
    _PHASE_EDU_CACHE.clear()


def _ai_endpoint_response(
    endpoint: str,
    state: dict[str, Any],
    instruction: str,
    fallback: dict[str, Any],
    max_tokens: int = 1800,
) -> dict[str, Any]:
    """Fetch-backed Claude analysis for a Cycle Engine v1 GET response."""
    context = _analysis_context(state)
    cache_key = hashlib.sha256(
        f"{endpoint}:{json.dumps(context, sort_keys=True, default=str)}".encode("utf-8")
    ).hexdigest()
    if cache_key in _AI_JSON_CACHE:
        cached = dict(_AI_JSON_CACHE[cache_key])
        cached["ai_generated"] = True
        cached["ai_cached"] = True
        return cached

    prompt = (
        f"Endpoint: {endpoint}\n"
        f"Today: {_today().isoformat()}\n\n"
        "Backend + local cycle context (analyze this data):\n"
        f"{_to_context_json(context)}\n\n"
        f"{instruction}\n\n"
        "Return one JSON object only."
    )
    text = _call_ai_json(prompt, max_tokens=max_tokens)
    parsed = _parse_json_object(text)
    if not isinstance(parsed, dict) or not parsed:
        result = dict(fallback)
        result["ai_generated"] = False
        result["ai_fallback"] = True
        result["sources"] = state.get("sources") or fallback.get("sources")
        result["backend_errors"] = state.get("backend_errors") or fallback.get("backend_errors") or {}
        return result

    parsed["ai_generated"] = True
    parsed["ai_cached"] = False
    parsed["sources"] = state.get("sources")
    if state.get("backend_errors"):
        parsed["backend_errors"] = state["backend_errors"]
    _AI_JSON_CACHE[cache_key] = parsed
    return parsed


def _analysis_context(state: dict[str, Any]) -> dict[str, Any]:
    reconciliation = _recompute_reconciliation(state)
    return {
        "user_profile": state.get("profile"),
        "snapshot": state.get("snapshot"),
        "local_logs": {
            "period_logs": state.get("period_logs") or [],
            "bbt_logs": state.get("bbt_logs") or [],
            "opk_logs": state.get("opk_logs") or [],
            "mucus_logs": state.get("mucus_logs") or [],
        },
        "cycle_summary": _cycle_summary(state),
        "reconciliation": reconciliation,
        "coverline": _coverline_status(state),
        "backend_errors": state.get("backend_errors") or {},
    }


def _to_context_json(payload: Any) -> str:
    text = json.dumps(payload, indent=2, ensure_ascii=True, default=str)
    if len(text) <= MAX_CONTEXT_CHARS:
        return text
    return text[: MAX_CONTEXT_CHARS - 32] + "\n... [truncated]"


def _ai_text(
    endpoint: str,
    facts: dict[str, Any],
    fallback: str,
    prompt_override: str | None = None,
) -> str:
    cache_key = hashlib.sha256(
        f"{endpoint}:{json.dumps(facts, sort_keys=True, default=str)}".encode("utf-8")
    ).hexdigest()
    if cache_key in _AI_CACHE:
        return _AI_CACHE[cache_key]

    prompt = prompt_override or (
        "Facts (do not change these numbers):\n"
        f"{json.dumps(facts, indent=2, default=str)}\n\n"
        "Write one calm UI sentence using only these facts."
    )
    text = _call_ai_copy(prompt)
    if not text:
        text = fallback
    if text:
        _AI_CACHE[cache_key] = text
    return text or fallback


def _call_ai_json(prompt: str, max_tokens: int = 1800) -> str:
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1
    for attempt in range(attempts):
        try:
            result = llm_call(
                prompt=prompt,
                system=AI_SYSTEM_PROMPT,
                max_tokens=max_tokens,
            )
            return str(result or "").strip()
        except Exception as exc:
            if attempt >= attempts - 1 or not _is_retryable_llm_error(exc):
                return ""
            time.sleep(LLM_RETRY_DELAYS_SECONDS[attempt])
    return ""


def _call_ai_copy(prompt: str) -> str:
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1
    for attempt in range(attempts):
        try:
            result = llm_call(
                prompt=prompt,
                system=AI_COPY_SYSTEM_PROMPT,
                max_tokens=150,
            )
            return " ".join(str(result or "").strip().split())
        except Exception as exc:
            if attempt >= attempts - 1 or not _is_retryable_llm_error(exc):
                return ""
            time.sleep(LLM_RETRY_DELAYS_SECONDS[attempt])
    return ""


def _parse_json_object(text: str) -> Any | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(line for line in lines if not line.startswith("```")).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None


def _parse_phase_education(text: str) -> dict[str, str]:
    notes = {"bbt_note": "", "energy_note": "", "hormone_note": "", "focus_note": ""}
    mapping = {
        "bbt": "bbt_note",
        "energy": "energy_note",
        "hormone": "hormone_note",
        "focus": "focus_note",
    }
    for line in text.splitlines():
        cleaned = line.strip().lstrip("-").strip()
        if ":" not in cleaned:
            continue
        label, value = cleaned.split(":", 1)
        key = mapping.get(label.strip().lower())
        if key:
            notes[key] = value.strip()
    return notes


# ---------------------------------------------------------------------------
# Backend extraction helpers
# ---------------------------------------------------------------------------

def _try_get_backend_json(url: str) -> tuple[Any, str | None]:
    try:
        return _get_backend_json(url), None
    except Exception as exc:
        return None, str(exc)


def _get_backend_json(url: str) -> Any:
    response = httpx.get(
        url,
        headers=_backend_headers(),
        timeout=30.0,
        follow_redirects=True,
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type.lower():
        raise ValueError(f"Backend route did not return JSON: {url}")
    return response.json()


def _backend_headers() -> dict[str, str]:
    token = settings.CYCLE_ENGINE_ACCESS_TOKEN or settings.BACKEND_ACCESS_TOKEN
    headers = {
        "Accept": "application/json",
        "ngrok-skip-browser-warning": "true",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["access-token"] = token
        headers["x-access-token"] = token
    return headers


def _extract_user_id(profile: Any) -> int | None:
    for path in (
        ["id"],
        ["user_id"],
        ["user", "id"],
        ["data", "id"],
        ["data", "user_id"],
        ["data", "user", "id"],
    ):
        value = _dig(profile, path)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _resolve_cycle_start(
    user: dict[str, Any],
    period_logs: list[dict[str, Any]],
    snapshot: Any,
    profile: Any,
) -> date:
    if user.get("cycle_start_date"):
        return _parse_date(user["cycle_start_date"])
    if period_logs:
        latest = max(period_logs, key=lambda item: item["start_date"])
        return _parse_date(latest["start_date"])
    for path in (
        ["cycle_start_date"],
        ["current_cycle", "start_date"],
        ["data", "cycle_start_date"],
        ["data", "current_cycle", "start_date"],
        ["last_period_start"],
        ["data", "last_period_start"],
    ):
        value = _dig(snapshot, path) or _dig(profile, path)
        if value:
            return _parse_date(str(value)[:10])
    return _today() - timedelta(days=10)


def _extract_avg_cycle_length(snapshot: Any, profile: Any, period_logs: list[dict[str, Any]]) -> float:
    for path in (
        ["avg_cycle_length"],
        ["average_cycle_length"],
        ["cycle_length"],
        ["data", "avg_cycle_length"],
        ["data", "average_cycle_length"],
    ):
        value = _dig(snapshot, path) or _dig(profile, path)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    lengths = []
    starts = sorted({_parse_date(log["start_date"]) for log in period_logs})
    for index in range(1, len(starts)):
        lengths.append((starts[index] - starts[index - 1]).days)
    if lengths:
        return round(sum(lengths) / len(lengths), 1)
    return 28.0


def _extract_variance(snapshot: Any, profile: Any, period_logs: list[dict[str, Any]]) -> int:
    for path in (["cycle_variance_days"], ["variance_days"], ["data", "cycle_variance_days"]):
        value = _dig(snapshot, path) or _dig(profile, path)
        if isinstance(value, (int, float)):
            return int(value)
    lengths = []
    starts = sorted({_parse_date(log["start_date"]) for log in period_logs})
    for index in range(1, len(starts)):
        lengths.append((starts[index] - starts[index - 1]).days)
    if len(lengths) >= 2:
        return max(lengths) - min(lengths)
    return 2


def _extract_period_logs(snapshot: Any, profile: Any, user_id: int) -> list[dict[str, Any]]:
    raw = (
        _dig(snapshot, ["period_logs"])
        or _dig(snapshot, ["periods"])
        or _dig(snapshot, ["data", "period_logs"])
        or _dig(profile, ["period_logs"])
        or []
    )
    logs: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            start = item.get("start_date") or item.get("start") or item.get("date")
            if not start:
                continue
            end = item.get("end_date") or item.get("end")
            logs.append(
                {
                    "id": item.get("id") or index + 1,
                    "user_id": user_id,
                    "start_date": str(start)[:10],
                    "end_date": str(end)[:10] if end else None,
                }
            )
    return logs


def _extract_bbt_logs(snapshot: Any, user_id: int) -> list[dict[str, Any]]:
    raw = (
        _dig(snapshot, ["bbt_logs"])
        or _dig(snapshot, ["temperatures"])
        or _dig(snapshot, ["data", "bbt_logs"])
        or []
    )
    logs: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return logs
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        temp = item.get("temperature_f") or item.get("temperature") or item.get("temp")
        day = item.get("date") or item.get("logged_at")
        if temp is None or not day:
            continue
        logs.append(
            {
                "id": item.get("id") or index + 1,
                "user_id": user_id,
                "date": str(day)[:10],
                "temperature_f": float(temp),
                "logged_at_time": str(item.get("time") or item.get("logged_at_time") or "06:00"),
                "flags": item.get("flags") or [],
            }
        )
    return logs


def _extract_opk_logs(snapshot: Any, user_id: int) -> list[dict[str, Any]]:
    raw = _dig(snapshot, ["opk_logs"]) or _dig(snapshot, ["lh_logs"]) or _dig(snapshot, ["data", "opk_logs"]) or []
    logs: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return logs
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        day = item.get("date")
        result = str(item.get("result") or "negative").lower()
        if result not in {"negative", "rising", "positive"} or not day:
            continue
        logs.append(
            {
                "id": item.get("id") or index + 1,
                "user_id": user_id,
                "date": str(day)[:10],
                "result": result,
                "lh_value": item.get("lh_value"),
                "note": item.get("note"),
            }
        )
    return logs


def _extract_mucus_logs(snapshot: Any, user_id: int) -> list[dict[str, Any]]:
    raw = _dig(snapshot, ["mucus_logs"]) or _dig(snapshot, ["cervical_mucus"]) or _dig(snapshot, ["data", "mucus_logs"]) or []
    logs: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return logs
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        day = item.get("date")
        mucus_type = str(item.get("type") or item.get("mucus_type") or "").lower()
        if not day or mucus_type not in {"dry", "sticky", "creamy", "watery", "egg_white"}:
            continue
        logs.append(
            {
                "id": item.get("id") or index + 1,
                "user_id": user_id,
                "date": str(day)[:10],
                "type": mucus_type,
            }
        )
    return logs


def _merge_logs(base: list[dict[str, Any]], overlay: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    merged = {item[key]: item for item in base if key in item}
    for item in overlay:
        if key in item:
            merged[item[key]] = item
    return list(merged.values())


# ---------------------------------------------------------------------------
# Small utils
# ---------------------------------------------------------------------------

def _dig(data: Any, path: list[str]) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _next_id(logs: list[dict[str, Any]]) -> int:
    if not logs:
        return 1
    return max(int(item.get("id") or 0) for item in logs) + 1


def _parse_day_range(value: str) -> tuple[int, int]:
    try:
        start_raw, end_raw = value.split("-", 1)
        start, end = int(start_raw), int(end_raw)
        if start < 1 or end < start:
            raise ValueError
        return start, end
    except Exception as exc:
        raise ValueError("cycle_day_range must look like '1-28'") from exc


def _parse_date(value: str | date) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value)[:10])


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_retryable_llm_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in RETRYABLE_LLM_STATUS_CODES:
        return True
    message = str(exc).lower()
    return any(
        marker in message
        for marker in ("overloaded", "rate_limit", "rate limit", "timeout", "temporarily")
    )
