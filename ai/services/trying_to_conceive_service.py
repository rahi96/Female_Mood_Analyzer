"""Trying-to-conceive service: deterministic skeleton + AI narrative (one field only).

Response shape is identical to the previous AI-only implementation; AI is kept exclusively
for `highest_priority.message` and served stale-while-revalidate from a 15-minute cache so
it never blocks the request path.
"""

import hashlib
import json
import threading
import time
from datetime import date, datetime
from typing import Any

from ai.utils.cache import LRUCacheWithTTL
from ai.utils.coalescer import RequestCoalescer
from ai.utils.db import get_snapshot
from ai.utils.llm_call import llm_call

# Clinical constants (same values the old prompt used verbatim).
SPERM_VIABILITY_DAYS = 5
EGG_VIABILITY_HOURS = 24

# Narrative LLM behaviour.
NARRATIVE_TTL_SECONDS = 900
NARRATIVE_MAX_TOKENS = 220
NARRATIVE_BG_SEMAPHORE_MAX = 10

# Snapshot cache absorbs the 6 sequential MySQL round-trips to AWS RDS per request.
SNAPSHOT_TTL_SECONDS = 30

_NARRATIVE_CACHE = LRUCacheWithTTL(max_size=500, ttl_seconds=NARRATIVE_TTL_SECONDS)
_NARRATIVE_COALESCER = RequestCoalescer()
_NARRATIVE_BG_SEMAPHORE = threading.BoundedSemaphore(NARRATIVE_BG_SEMAPHORE_MAX)
_SNAPSHOT_CACHE = LRUCacheWithTTL(max_size=500, ttl_seconds=SNAPSHOT_TTL_SECONDS)

# Profile fields safe to echo to clients and send to the LLM.
_PROFILE_ALLOWED_FIELDS = frozenset({
    "id", "user_id", "full_name", "age", "height", "weight",
    "life_stage_id", "activity_id",
})

TTC_SYSTEM_PROMPT = (
    "You write short, calm fertility-tracking UI copy. "
    "Use only the facts provided. Do not invent cycle days, OPK results, or dates. "
    "Return 2-3 plain sentences totaling 35-55 words. No markdown, no preamble."
)

# Window descriptions are stable across calls (the previous prompt pinned them), so we
# treat them as constants rather than regenerating with Claude on every request.
_WINDOW_DESCRIPTIONS = (
    "Early fertile window - sperm can survive to ovulation",
    "Pre-peak - OPK rise expected, timing matters",
    "Predicted peak - ovulation window, egg 12-24h viable",
    "Post-ovulatory - BBT shift would confirm ovulation",
)
_WINDOW_PRIORITIES = ("Moderate", "High", "Highest", "Low")
_WINDOW_SCORES = (45, 75, 95, 15)


def fetch_trying_to_conceive_data(user_id: int) -> dict[str, Any]:
    """Public entry point used by the route."""
    snapshot = _get_snapshot_cached(user_id)

    if not snapshot or not (
        snapshot.get("current_cycle")
        or snapshot.get("bbt_logs")
        or snapshot.get("opk_logs")
    ):
        return {
            "status": "empty",
            "service": "trying_to_conceive",
            "fetched": True,
            "sources": {"database": "mysql"},
            "user_id": user_id,
            "message": "No cycle data yet",
            "description": "Start logging your cycle data to see personalized conception insights.",
        }

    trying_to_conceive = _build_ttc_section(user_id, snapshot)

    return {
        "status": "ready",
        "service": "trying_to_conceive",
        "fetched": True,
        "sources": {"database": "mysql"},
        "trying_to_conceive": trying_to_conceive,
    }


# ---------------------------------------------------------------------------
# Deterministic builder
# ---------------------------------------------------------------------------

def _build_ttc_section(user_id: int, snapshot: dict[str, Any]) -> dict[str, Any]:
    cycle = snapshot.get("current_cycle") or {}
    opk_logs = snapshot.get("opk_logs") or []
    bbt_logs = snapshot.get("bbt_logs") or []

    cycle_day = _safe_int(cycle.get("current_cycle_day"), 1)
    cycle_length = _safe_int(cycle.get("cycle_length"), 28) or 28
    phase_label = _phase_label(cycle, cycle_day, cycle_length)
    ov_day, ov_label = _ovulation_estimate(cycle, cycle_length)
    opk_date, opk_result = _last_opk(opk_logs)
    fertile_start = _safe_int(cycle.get("fertile_start_day"), max(1, ov_day - SPERM_VIABILITY_DAYS))
    fertile_end = _safe_int(cycle.get("fertile_end_day"), ov_day + 1)
    progress_percent = max(0, min(100, int(round((cycle_day / cycle_length) * 100))))
    status = _status_label(cycle_day, fertile_start, fertile_end)
    lh_title = _lh_title_for_status(status)

    facts = {
        "cycle_day": cycle_day,
        "cycle_length": cycle_length,
        "fertile_start": fertile_start,
        "fertile_end": fertile_end,
        "ov_day": ov_day,
        "status": status,
        "opk_date": opk_date,
        "opk_result": opk_result,
        "bbt_count": len(bbt_logs),
    }

    narrative, narrative_source = _get_narrative(user_id, facts)

    bbt_note = (
        f"{len(bbt_logs)} BBT entries logged - thermal shift tracking active."
        if bbt_logs
        else "No BBT logs recorded - adding daily temperatures can help confirm ovulation shift."
    )

    opk_metric_value = (
        f"{str(opk_result).title()} ({opk_date})" if opk_date else "Not logged"
    )

    section = {
        "title": "Trying to Conceive",
        "cycle_context": {
            "cycle_day": cycle_day,
            "phase": phase_label,
            "average_cycle_length": f"{cycle_length}d",
        },
        "lh_surge": {
            "title": lh_title,
            "subtitle": "Egg viable 12-24h after release",
            "today_label": f"Today: Day {cycle_day}",
            "status": status,
            "progress_percent": progress_percent,
            "timeline": {
                "start_label": "Day 1",
                "end_label": f"Day {cycle_length}",
            },
            "metrics": [
                {"label": "Cycle day", "value": str(cycle_day)},
                {"label": "Ovulation est.", "value": ov_label},
                {"label": "Last OPK", "value": opk_metric_value},
            ],
        },
        "conception_timing": {
            "title": "Conception Timing - Priority Map",
            "subtitle": "Sperm viable 5 days - egg viable 12-24h",
            "windows": _build_windows(fertile_start, ov_day),
        },
        "highest_priority": {
            "title": "LH Surge - This is your highest-priority moment.",
            "subtitle": "Moment",
            "message": narrative,
            "bbt_note": bbt_note,
        },
        "ai_generated": narrative_source != "template",
        "ai_cached": narrative_source == "cache",
    }

    return section


def _build_windows(fertile_start: int, ov_day: int) -> list[dict[str, Any]]:
    pre_peak_day = max(fertile_start + 1, ov_day - 1)
    early_end = max(fertile_start, ov_day - 2)
    labels = (
        f"Days {fertile_start}-{early_end}",
        f"Day {pre_peak_day}",
        f"Days {ov_day}-{ov_day + 1}",
        f"Day {ov_day + 2}+",
    )
    return [
        {
            "label": labels[i],
            "priority": _WINDOW_PRIORITIES[i],
            "description": _WINDOW_DESCRIPTIONS[i],
            "score_percent": _WINDOW_SCORES[i],
        }
        for i in range(4)
    ]


# ---------------------------------------------------------------------------
# Narrative (Claude, stale-while-revalidate)
# ---------------------------------------------------------------------------

def _get_narrative(user_id: int, facts: dict[str, Any]) -> tuple[str, str]:
    """Return (narrative_text, source) where source in {'cache','fresh','template'}."""
    key = _narrative_cache_key(user_id, facts)
    cached, age = _NARRATIVE_CACHE.get_with_age(key)

    if cached is not None and age is not None and age <= NARRATIVE_TTL_SECONDS:
        if age > NARRATIVE_TTL_SECONDS * 0.5:
            _trigger_background_refresh(key, facts)
        return cached, "cache"

    template = _narrative_template(facts)

    try:
        text = _call_narrative_llm(facts)
    except Exception:
        text = ""

    if text:
        _NARRATIVE_CACHE.put(key, text)
        return text, "fresh"

    _trigger_background_refresh(key, facts)
    return template, "template"


def _trigger_background_refresh(key: str, facts: dict[str, Any]) -> None:
    if not _NARRATIVE_BG_SEMAPHORE.acquire(blocking=False):
        return

    def _refresh() -> None:
        try:
            text = _call_narrative_llm(facts)
            if text:
                _NARRATIVE_CACHE.put(key, text)
        except Exception:
            pass
        finally:
            _NARRATIVE_BG_SEMAPHORE.release()

    threading.Thread(target=_refresh, daemon=True).start()


def _narrative_cache_key(user_id: int, facts: dict[str, Any]) -> str:
    payload = {
        "user_id": user_id,
        "cycle_day": facts["cycle_day"],
        "status": facts["status"],
        "opk_date": facts["opk_date"],
        "opk_result": facts["opk_result"],
        "bbt_count": facts["bbt_count"],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _call_narrative_llm(facts: dict[str, Any]) -> str:
    prompt = _narrative_prompt(facts)
    try:
        text = llm_call(
            prompt=prompt,
            system=TTC_SYSTEM_PROMPT,
            max_tokens=NARRATIVE_MAX_TOKENS,
        )
    except Exception:
        return ""
    return " ".join(str(text or "").split())


def _narrative_prompt(facts: dict[str, Any]) -> str:
    opk_line = (
        f"Last OPK: {facts['opk_result']} on {facts['opk_date']}"
        if facts["opk_date"]
        else "Last OPK: not logged"
    )
    bbt_line = (
        f"BBT logs: {facts['bbt_count']} entries"
        if facts["bbt_count"]
        else "BBT logs: none"
    )
    return (
        f"User fertility status: {facts['status']}.\n"
        f"Cycle day {facts['cycle_day']} of ~{facts['cycle_length']}.\n"
        f"Fertile window Days {facts['fertile_start']}-{facts['fertile_end']}, "
        f"predicted ovulation Day {facts['ov_day']}.\n"
        f"{opk_line}.\n"
        f"{bbt_line}.\n\n"
        "Write a calm 2-3 sentence summary for the Trying-to-Conceive highest-priority card. "
        "Reference the specific cycle day and OPK history. Do not invent values."
    )


def _narrative_template(facts: dict[str, Any]) -> str:
    status = facts["status"]
    if status == "Pre-fertile":
        return (
            f"Your fertile window opens on Day {facts['fertile_start']}. "
            f"Start LH/OPK testing from Day {max(1, facts['fertile_start'] - 1)} "
            "to catch the surge early."
        )
    if status == "Fertile":
        return (
            f"You're in the fertile window (Days {facts['fertile_start']}-{facts['fertile_end']}). "
            f"Peak conception probability is on ovulation Day {facts['ov_day']}. "
            "Intercourse today and tomorrow maximizes your chance."
        )
    if facts["opk_date"]:
        return (
            f"Your fertile window for this cycle (Days {facts['fertile_start']}-{facts['fertile_end']}) "
            f"has likely passed. A recent {facts['opk_result']} OPK was logged on {facts['opk_date']} - "
            "if it reflects a true surge, ovulation may have occurred shortly after. "
            "The next high-priority LH window will open in your upcoming cycle."
        )
    return (
        f"Your fertile window for this cycle (Days {facts['fertile_start']}-{facts['fertile_end']}) "
        "has likely passed. The next LH window will open in your upcoming cycle."
    )


# ---------------------------------------------------------------------------
# Deterministic helpers
# ---------------------------------------------------------------------------

def _phase_label(cycle: dict[str, Any], cycle_day: int, cycle_length: int) -> str:
    phase = cycle.get("current_phase")
    if phase:
        return f"{str(phase).capitalize()} phase"
    half = max(8, cycle_length - 14)
    if cycle_day <= 5:
        return "Menstrual phase"
    if cycle_day <= half - 2:
        return "Follicular phase"
    if cycle_day <= half + 1:
        return "Ovulatory phase"
    return "Luteal phase"


def _ovulation_estimate(cycle: dict[str, Any], cycle_length: int) -> tuple[int, str]:
    confirmed = cycle.get("confirmed_ovulation_day")
    if confirmed:
        return int(confirmed), f"Day {int(confirmed)} (confirmed)"
    predicted = cycle.get("predicted_ovulation_day") or cycle.get("predicted_peak_day")
    if predicted:
        return int(predicted), f"Day {int(predicted)} (peak)"
    est = max(8, cycle_length - 14)
    return est, f"Day {est} (estimated)"


def _last_opk(opk_logs: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    if not opk_logs:
        return None, None
    latest = max(opk_logs, key=lambda log: str(log.get("log_date") or ""))
    log_date = _parse_date(latest.get("log_date"))
    label = _format_date(log_date) if log_date else None
    return label, (latest.get("result") or None)


def _status_label(cycle_day: int, fertile_start: int, fertile_end: int) -> str:
    if cycle_day < fertile_start:
        return "Pre-fertile"
    if fertile_start <= cycle_day <= fertile_end:
        return "Fertile"
    return "Luteal"


def _lh_title_for_status(status: str) -> str:
    return {
        "Pre-fertile": "LH Surge - Window Approaching",
        "Fertile": "LH Surge - Act Now",
        "Luteal": "LH Surge - Window Likely Passed",
    }[status]


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except (TypeError, ValueError):
        return None


def _format_date(d: date) -> str:
    # strftime("%-d") is platform-dependent, so build the day manually.
    return f"{d.strftime('%b')} {d.day}"


def _safe_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _serialize(data: Any) -> Any:
    """Convert DB rows (dates, decimals) to JSON-safe values and strip PII from profile."""
    normalized = json.loads(json.dumps(data, default=str)) if data is not None else None
    if isinstance(normalized, dict) and isinstance(normalized.get("profile"), dict):
        normalized["profile"] = _sanitize_profile(normalized["profile"])
    return normalized


def _sanitize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in profile.items() if k in _PROFILE_ALLOWED_FIELDS}


def _get_snapshot_cached(user_id: int) -> Any:
    key = f"snapshot:{user_id}"
    cached = _SNAPSHOT_CACHE.get(key)
    if cached is not None:
        return cached
    snapshot = _serialize(get_snapshot(user_id))
    if snapshot is not None:
        _SNAPSHOT_CACHE.put(key, snapshot)
    return snapshot
