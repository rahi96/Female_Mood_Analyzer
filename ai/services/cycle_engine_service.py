import json
import time
from typing import Any

import httpx

from ai.config import settings
from ai.utils.llm_call import llm_call


RETRYABLE_LLM_STATUS_CODES = {429, 500, 502, 503, 529}
LLM_RETRY_DELAYS_SECONDS = (1.0, 2.0)
MAX_CONTEXT_CHARS = 12000


CYCLE_ENGINE_SYSTEM_PROMPT = """You are a careful cycle tracking analysis assistant.

Rules:
- Use only the user profile and health snapshot JSON provided.
- Do not diagnose, prescribe, or claim medical certainty.
- If cycle-specific signals are missing, say they are not logged instead of inventing values.
- The engine status for this request must be "Moderate".
- Return valid JSON only. Do not add markdown, code fences, or extra commentary.
"""

CALENDAR_SYSTEM_PROMPT = """You are a careful cycle calendar analysis assistant.

Rules:
- Use only the user profile and health snapshot JSON provided.
- Do not diagnose, prescribe, or claim medical certainty.
- Generate the Calendar section for a cycle engine UI.
- If detailed cycle history is missing, create cautious estimates from available cycle context and clearly keep values as estimates.
- Return valid JSON only. Do not add markdown, code fences, or extra commentary.
"""

BBT_SYSTEM_PROMPT = """You are a careful basal body temperature chart analysis assistant.

Rules:
- Use only the user profile and health snapshot JSON provided.
- Do not diagnose, prescribe, or claim medical certainty.
- Generate the BBT section for a cycle engine UI.
- If raw BBT readings are missing, create cautious UI-ready estimates and clearly mark them as estimated.
- Return valid JSON only. Do not add markdown, code fences, or extra commentary.
"""

OPK_LH_SYSTEM_PROMPT = """You are a careful OPK, LH, and cervical mucus cycle analysis assistant.

Rules:
- Use only the user profile and health snapshot JSON provided.
- Do not diagnose, prescribe, or claim medical certainty.
- Generate the OPK / LH section for a cycle engine UI.
- If OPK, LH, or cervical mucus logs are missing, create cautious UI-ready estimates and clearly mark missing logs.
- Return valid JSON only. Do not add markdown, code fences, or extra commentary.
"""

def fetch_cycle_engine_data() -> dict[str, Any]:
    user_profile = _get_backend_json(settings.CYCLE_ENGINE_PROFILE_URL)
    snapshot = _get_backend_json(settings.CYCLE_ENGINE_SNAPSHOT_URL)
    engine = _generate_engine_analysis(user_profile, snapshot)
    calendar = _generate_calendar_analysis(user_profile, snapshot)
    bbt = _generate_bbt_analysis(user_profile, snapshot)
    opk_lh = _generate_opk_lh_analysis(user_profile, snapshot)

    return {
        "status": "ready",
        "service": "cycle_engine",
        "fetched": True,
        "sources": {
            "user_profile": settings.CYCLE_ENGINE_PROFILE_URL,
            "snapshot": settings.CYCLE_ENGINE_SNAPSHOT_URL,
        },
        "engine": engine,
        "calendar": calendar,
        "bbt": bbt,
        "opk_lh": opk_lh,
        "user_profile": user_profile,
        "snapshot": snapshot,
    }


def _generate_engine_analysis(user_profile: Any, snapshot: Any) -> dict[str, Any]:
    prompt = _build_engine_prompt(user_profile, snapshot)
    response_text = _call_engine_llm(prompt)
    parsed = _parse_engine_response(response_text)
    if parsed:
        return parsed
    return _fallback_engine_analysis()


def _generate_calendar_analysis(user_profile: Any, snapshot: Any) -> dict[str, Any]:
    prompt = _build_calendar_prompt(user_profile, snapshot)
    response_text = _call_calendar_llm(prompt)
    parsed = _parse_calendar_response(response_text)
    if parsed:
        return parsed
    return _fallback_calendar_analysis()


def _build_calendar_prompt(user_profile: Any, snapshot: Any) -> str:
    context = json.dumps(
        {
            "user_profile": user_profile,
            "snapshot": snapshot,
        },
        ensure_ascii=False,
        default=str,
    )[:MAX_CONTEXT_CHARS]

    return f"""Generate only the Calendar section for a cycle engine UI.

Backend context JSON:
{context}

Return JSON with exactly this structure:
{{
  "next_period": {{
    "title": "Next period",
    "value": "In 11d - Jul 6",
    "description": "Estimated from rolling cycle average"
  }},
  "rolling_avg": {{
    "title": "Rolling avg",
    "value": "27.8 days",
    "description": "Average of the most recent completed cycles"
  }},
  "c1": {{"label": "C1", "value": "26d"}},
  "c2": {{"label": "C2", "value": "28d"}},
  "c3": {{"label": "C3", "value": "29d"}},
  "c4": {{"label": "C4", "value": "28d"}},
  "cycle_variation": {{
    "value": "3 days",
    "status": "within_normal_range",
    "note": "Cycle variation: 3 days - within normal range"
  }},
  "confirm_today": {{
    "question": "Confirm today as Day 1?",
    "description": "Anchors the cycle and recomputes the rolling average.",
    "yes_label": "Yes",
    "no_label": "No"
  }}
}}

Requirements:
- Generate next_period, rolling_avg, c1, c2, c3, and c4.
- Use cycle history from backend context when present.
- If cycle history is missing, use conservative estimates similar to the UI example and keep descriptions as estimated.
- c1 through c4 values must be compact duration strings like "26d".
- rolling_avg.value must be a compact days string like "27.8 days".
- next_period.value must be concise and UI-ready.
"""


def _call_calendar_llm(prompt: str) -> str:
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1

    for attempt in range(attempts):
        try:
            return llm_call(
                prompt=prompt,
                system=CALENDAR_SYSTEM_PROMPT,
                max_tokens=1000,
            )
        except Exception as exc:
            is_last_attempt = attempt == attempts - 1
            if not _is_retryable_llm_error(exc):
                raise
            if is_last_attempt:
                return ""
            time.sleep(LLM_RETRY_DELAYS_SECONDS[attempt])

    return ""


def _parse_calendar_response(text: str) -> dict[str, Any] | None:
    payload = _parse_json_object(text)
    if payload is None:
        return None

    try:
        return _coerce_calendar_payload(payload)
    except Exception:
        return None


def _coerce_calendar_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _fallback_calendar_analysis()

    fallback = _fallback_calendar_analysis()
    c1 = _coerce_cycle_card(payload.get("c1"), fallback["c1"], "C1")
    c2 = _coerce_cycle_card(payload.get("c2"), fallback["c2"], "C2")
    c3 = _coerce_cycle_card(payload.get("c3"), fallback["c3"], "C3")
    c4 = _coerce_cycle_card(payload.get("c4"), fallback["c4"], "C4")

    variation_days = _cycle_variation_days([c1, c2, c3, c4])
    cycle_variation = payload.get("cycle_variation") if isinstance(payload.get("cycle_variation"), dict) else {}
    variation_value = str(cycle_variation.get("value") or f"{variation_days} days")
    variation_note = str(
        cycle_variation.get("note")
        or f"Cycle variation: {variation_days} days - within normal range"
    )

    return {
        "next_period": _coerce_labeled_value(payload.get("next_period"), fallback["next_period"]),
        "rolling_avg": _coerce_labeled_value(payload.get("rolling_avg"), fallback["rolling_avg"]),
        "c1": c1,
        "c2": c2,
        "c3": c3,
        "c4": c4,
        "cycle_variation": {
            "value": variation_value,
            "status": str(cycle_variation.get("status") or "within_normal_range"),
            "note": variation_note,
        },
        "confirm_today": _coerce_confirm_today(payload.get("confirm_today"), fallback["confirm_today"]),
    }


def _coerce_labeled_value(value: Any, fallback: dict[str, str]) -> dict[str, str]:
    if not isinstance(value, dict):
        value = {}
    return {
        "title": str(value.get("title") or fallback["title"]),
        "value": str(value.get("value") or fallback["value"]),
        "description": str(value.get("description") or fallback["description"]),
    }


def _coerce_cycle_card(value: Any, fallback: dict[str, str], label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        value = {}
    raw_value = value.get("value") or fallback["value"]
    return {
        "label": label,
        "value": _display_cycle_length(raw_value, fallback["value"]),
    }


def _coerce_confirm_today(value: Any, fallback: dict[str, str]) -> dict[str, str]:
    if not isinstance(value, dict):
        value = {}
    return {
        "question": str(value.get("question") or fallback["question"]),
        "description": str(value.get("description") or fallback["description"]),
        "yes_label": str(value.get("yes_label") or fallback["yes_label"]),
        "no_label": str(value.get("no_label") or fallback["no_label"]),
    }


def _display_cycle_length(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        stripped = value.strip()
        normalized = stripped.lower().replace("days", "").replace("day", "").replace("d", "").strip()
        try:
            return f"{int(float(normalized))}d"
        except ValueError:
            return stripped
    try:
        return f"{int(float(value))}d"
    except (TypeError, ValueError):
        return fallback


def _cycle_variation_days(cycles: list[dict[str, str]]) -> int:
    values = []
    for cycle in cycles:
        value = cycle.get("value", "").replace("days", "").replace("day", "").replace("d", "").strip()
        try:
            values.append(int(float(value)))
        except ValueError:
            continue
    if not values:
        return 3
    return max(values) - min(values)


def _fallback_calendar_analysis() -> dict[str, Any]:
    return {
        "next_period": {
            "title": "Next period",
            "value": "In 11d - Jul 6",
            "description": "Estimated from rolling cycle average",
        },
        "rolling_avg": {
            "title": "Rolling avg",
            "value": "27.8 days",
            "description": "Average of the most recent completed cycles",
        },
        "c1": {"label": "C1", "value": "26d"},
        "c2": {"label": "C2", "value": "28d"},
        "c3": {"label": "C3", "value": "29d"},
        "c4": {"label": "C4", "value": "28d"},
        "cycle_variation": {
            "value": "3 days",
            "status": "within_normal_range",
            "note": "Cycle variation: 3 days - within normal range",
        },
        "confirm_today": {
            "question": "Confirm today as Day 1?",
            "description": "Anchors the cycle and recomputes the rolling average.",
            "yes_label": "Yes",
            "no_label": "No",
        },
    }


def _generate_bbt_analysis(user_profile: Any, snapshot: Any) -> dict[str, Any]:
    prompt = _build_bbt_prompt(user_profile, snapshot)
    response_text = _call_bbt_llm(prompt)
    parsed = _parse_bbt_response(response_text)
    if parsed:
        return parsed
    return _fallback_bbt_analysis()


def _build_bbt_prompt(user_profile: Any, snapshot: Any) -> str:
    context = json.dumps(
        {
            "user_profile": user_profile,
            "snapshot": snapshot,
        },
        ensure_ascii=False,
        default=str,
    )[:MAX_CONTEXT_CHARS]

    return f"""Generate only the BBT section for a cycle engine UI.

Backend context JSON:
{context}

Return JSON with exactly this structure:
{{
  "chart": {{
    "title": "BBT Chart",
    "cycle_day_range": "Cycle day 1-28",
    "subtitle": "Coverline 97.6F - shift confirmed Day 18",
    "time_filter": "This month",
    "unit": "F",
    "coverline": {{"value": 97.6, "label": "Coverline"}},
    "shift": {{"confirmed": true, "confirmed_day": 18, "label": "shift confirmed Day 18"}},
    "points": [
      {{"cycle_day": 1, "temperature": 97.4, "type": "normal"}},
      {{"cycle_day": 2, "temperature": 97.5, "type": "ovulation"}}
    ],
    "ovulation_markers": [{{"cycle_day": 18, "label": "Ov."}}],
    "legend": [
      {{"label": "Coverline", "type": "coverline"}},
      {{"label": "Ov.", "type": "ovulation"}}
    ]
  }},
  "coverline_algorithm": {{
    "title": "Coverline Algorithm",
    "steps": [
      {{"status": "confirmed", "label": "Coverline", "description": "Highest of the 6 pre-shift low temps (Days 6-15) + 0.2F"}},
      {{"status": "confirmed", "label": "Shift rule", "description": "Requires 3 consecutive days at least 0.2F above coverline"}},
      {{"status": "confirmed", "label": "Shift confirmed", "description": "Days 16-18 confirm ovulation timing"}}
    ],
    "metrics": [
      {{"label": "Coverline", "value": "97.6F"}},
      {{"label": "Luteal length", "value": "12d"}},
      {{"label": "Phase", "value": "Normal"}}
    ]
  }},
  "log_today_bbt": {{
    "title": "Log today's BBT",
    "instructions": "Take immediately upon waking, at the same time every day.",
    "subtext": "Subtract 0.1F for every 30 minutes after normal wake time.",
    "input_placeholder": "e.g. 98.1F",
    "submit_label": "Log",
    "flags_note": "Flag disturbances - flagged readings are excluded from coverline calculation.",
    "flags": ["Illness", "Late night", "Alcohol", "Restless sleep"]
  }}
}}

Requirements:
- Generate chart, coverline_algorithm, and log_today_bbt.
- If raw BBT readings are not present in backend context, points may be estimated for UI display and should avoid claiming exact clinical certainty.
- chart.points should contain around 28 cycle-day temperature points when possible.
- Temperatures must be Fahrenheit numbers around 96.8 to 98.8.
- Keep strings concise and UI-ready.
"""


def _call_bbt_llm(prompt: str) -> str:
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1

    for attempt in range(attempts):
        try:
            return llm_call(
                prompt=prompt,
                system=BBT_SYSTEM_PROMPT,
                max_tokens=1800,
            )
        except Exception as exc:
            is_last_attempt = attempt == attempts - 1
            if not _is_retryable_llm_error(exc):
                raise
            if is_last_attempt:
                return ""
            time.sleep(LLM_RETRY_DELAYS_SECONDS[attempt])

    return ""


def _parse_bbt_response(text: str) -> dict[str, Any] | None:
    payload = _parse_json_object(text)
    if payload is None:
        return None

    try:
        return _coerce_bbt_payload(payload)
    except Exception:
        return None


def _coerce_bbt_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _fallback_bbt_analysis()

    fallback = _fallback_bbt_analysis()
    chart = payload.get("chart") if isinstance(payload.get("chart"), dict) else {}
    algorithm = payload.get("coverline_algorithm") if isinstance(payload.get("coverline_algorithm"), dict) else {}
    log_today = payload.get("log_today_bbt") if isinstance(payload.get("log_today_bbt"), dict) else {}

    return {
        "chart": _coerce_bbt_chart(chart, fallback["chart"]),
        "coverline_algorithm": _coerce_coverline_algorithm(algorithm, fallback["coverline_algorithm"]),
        "log_today_bbt": _coerce_log_today_bbt(log_today, fallback["log_today_bbt"]),
    }


def _coerce_bbt_chart(value: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    points = value.get("points") if isinstance(value.get("points"), list) else fallback["points"]
    markers = value.get("ovulation_markers") if isinstance(value.get("ovulation_markers"), list) else fallback["ovulation_markers"]
    legend = value.get("legend") if isinstance(value.get("legend"), list) else fallback["legend"]
    coverline = value.get("coverline") if isinstance(value.get("coverline"), dict) else fallback["coverline"]
    shift = value.get("shift") if isinstance(value.get("shift"), dict) else fallback["shift"]

    return {
        "title": str(value.get("title") or fallback["title"]),
        "cycle_day_range": str(value.get("cycle_day_range") or fallback["cycle_day_range"]),
        "subtitle": str(value.get("subtitle") or fallback["subtitle"]),
        "time_filter": str(value.get("time_filter") or fallback["time_filter"]),
        "unit": str(value.get("unit") or fallback["unit"]),
        "coverline": {
            "value": _temperature_value(coverline.get("value"), fallback["coverline"]["value"]),
            "label": str(coverline.get("label") or fallback["coverline"]["label"]),
        },
        "shift": {
            "confirmed": bool(shift.get("confirmed", fallback["shift"]["confirmed"])),
            "confirmed_day": _bounded_int(shift.get("confirmed_day"), fallback["shift"]["confirmed_day"], 1, 60),
            "label": str(shift.get("label") or fallback["shift"]["label"]),
        },
        "points": _coerce_bbt_points(points, fallback["points"]),
        "ovulation_markers": _coerce_markers(markers, fallback["ovulation_markers"]),
        "legend": _coerce_legend(legend, fallback["legend"]),
    }


def _coerce_coverline_algorithm(value: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    steps = value.get("steps") if isinstance(value.get("steps"), list) else fallback["steps"]
    metrics = value.get("metrics") if isinstance(value.get("metrics"), list) else fallback["metrics"]
    return {
        "title": str(value.get("title") or fallback["title"]),
        "steps": _coerce_algorithm_steps(steps, fallback["steps"]),
        "metrics": _coerce_label_value_list(metrics, fallback["metrics"]),
    }


def _coerce_log_today_bbt(value: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    flags = value.get("flags") if isinstance(value.get("flags"), list) else fallback["flags"]
    return {
        "title": str(value.get("title") or fallback["title"]),
        "instructions": str(value.get("instructions") or fallback["instructions"]),
        "subtext": str(value.get("subtext") or fallback["subtext"]),
        "input_placeholder": str(value.get("input_placeholder") or fallback["input_placeholder"]),
        "submit_label": str(value.get("submit_label") or fallback["submit_label"]),
        "flags_note": str(value.get("flags_note") or fallback["flags_note"]),
        "flags": [str(flag) for flag in flags],
    }


def _coerce_bbt_points(points: list[Any], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    coerced = []
    for item in points:
        if not isinstance(item, dict):
            continue
        coerced.append(
            {
                "cycle_day": _bounded_int(item.get("cycle_day"), len(coerced) + 1, 1, 60),
                "temperature": _temperature_value(item.get("temperature"), 97.4),
                "type": str(item.get("type") or "normal"),
            }
        )
    return coerced or fallback


def _coerce_markers(markers: list[Any], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    coerced = []
    for item in markers:
        if not isinstance(item, dict):
            continue
        coerced.append(
            {
                "cycle_day": _bounded_int(item.get("cycle_day"), 18, 1, 60),
                "label": str(item.get("label") or "Ov."),
            }
        )
    return coerced or fallback


def _coerce_legend(items: list[Any], fallback: list[dict[str, str]]) -> list[dict[str, str]]:
    coerced = []
    for item in items:
        if not isinstance(item, dict):
            continue
        coerced.append({"label": str(item.get("label") or ""), "type": str(item.get("type") or "normal")})
    return coerced or fallback


def _coerce_algorithm_steps(steps: list[Any], fallback: list[dict[str, str]]) -> list[dict[str, str]]:
    coerced = []
    for item in steps:
        if not isinstance(item, dict):
            continue
        coerced.append(
            {
                "status": str(item.get("status") or "pending"),
                "label": str(item.get("label") or "Step"),
                "description": str(item.get("description") or "Awaiting more logged BBT data."),
            }
        )
    return coerced or fallback


def _coerce_label_value_list(items: list[Any], fallback: list[dict[str, str]]) -> list[dict[str, str]]:
    coerced = []
    for item in items:
        if not isinstance(item, dict):
            continue
        coerced.append({"label": str(item.get("label") or ""), "value": str(item.get("value") or "")})
    return coerced or fallback


def _temperature_value(value: Any, default: float) -> float:
    try:
        number = float(str(value).replace("F", "").strip())
    except (TypeError, ValueError):
        number = default
    return round(max(95.0, min(100.5, number)), 2)


def _fallback_bbt_analysis() -> dict[str, Any]:
    return {
        "chart": {
            "title": "BBT Chart",
            "cycle_day_range": "Cycle day 1-28",
            "subtitle": "Coverline 97.6F - shift confirmed Day 18",
            "time_filter": "This month",
            "unit": "F",
            "coverline": {"value": 97.6, "label": "Coverline"},
            "shift": {"confirmed": True, "confirmed_day": 18, "label": "shift confirmed Day 18"},
            "points": _fallback_bbt_points(),
            "ovulation_markers": [{"cycle_day": 18, "label": "Ov."}],
            "legend": [
                {"label": "Coverline", "type": "coverline"},
                {"label": "Ov.", "type": "ovulation"},
            ],
        },
        "coverline_algorithm": {
            "title": "Coverline Algorithm",
            "steps": [
                {
                    "status": "confirmed",
                    "label": "Coverline",
                    "description": "Highest of the 6 pre-shift low temps (Days 6-15) + 0.2F",
                },
                {
                    "status": "confirmed",
                    "label": "Shift rule",
                    "description": "Requires 3 consecutive days at least 0.2F above coverline.",
                },
                {
                    "status": "confirmed",
                    "label": "Shift confirmed",
                    "description": "Days 16-18 confirm ovulation timing.",
                },
            ],
            "metrics": [
                {"label": "Coverline", "value": "97.6F"},
                {"label": "Luteal length", "value": "12d"},
                {"label": "Phase", "value": "Normal"},
            ],
        },
        "log_today_bbt": {
            "title": "Log today's BBT",
            "instructions": "Take immediately upon waking, at the same time every day.",
            "subtext": "Subtract 0.1F for every 30 minutes after normal wake time.",
            "input_placeholder": "e.g. 98.1F",
            "submit_label": "Log",
            "flags_note": "Flag disturbances - flagged readings are excluded from coverline calculation.",
            "flags": ["Illness", "Late night", "Alcohol", "Restless sleep"],
        },
    }


def _fallback_bbt_points() -> list[dict[str, Any]]:
    values = [
        97.35, 97.45, 97.32, 97.58, 97.5, 97.43, 97.47, 97.41,
        97.55, 97.48, 97.52, 97.39, 97.56, 97.44, 97.53, 97.85,
        98.02, 97.94, 98.12, 98.05, 98.0, 97.86, 97.97, 97.82,
        97.88, 97.62, 97.51, 97.35,
    ]
    points = []
    for index, temperature in enumerate(values, start=1):
        point_type = "ovulation" if index == 18 else "normal"
        points.append({"cycle_day": index, "temperature": temperature, "type": point_type})
    return points

def _generate_opk_lh_analysis(user_profile: Any, snapshot: Any) -> dict[str, Any]:
    prompt = _build_opk_lh_prompt(user_profile, snapshot)
    response_text = _call_opk_lh_llm(prompt)
    parsed = _parse_opk_lh_response(response_text)
    if parsed:
        return parsed
    return _fallback_opk_lh_analysis()


def _build_opk_lh_prompt(user_profile: Any, snapshot: Any) -> str:
    context = json.dumps(
        {
            "user_profile": user_profile,
            "snapshot": snapshot,
        },
        ensure_ascii=False,
        default=str,
    )[:MAX_CONTEXT_CHARS]

    return f"""Generate only the OPK / LH section for a cycle engine UI.

Backend context JSON:
{context}

Return JSON with exactly this structure:
{{
  "info_alert": {{
    "title": "OPK is forward-looking",
    "message": "In general, OPK is the only forward-looking exact now signal. A positive LH test means ovulation is expected within 12-36 hours. BBT only confirms ovulation after it has already occurred."
  }},
  "testing_window": {{
    "title": "Testing Window",
    "subtitle": "Days 10-15 - starts 4 days before predicted ovulation",
    "status": "Window closed",
    "cards": [
      {{"cycle_day": 10, "label": "D10", "result": "not_tested", "symbol": "-"}},
      {{"cycle_day": 11, "label": "D11", "result": "not_tested", "symbol": "-"}},
      {{"cycle_day": 12, "label": "D12", "result": "almost", "symbol": "-"}},
      {{"cycle_day": 13, "label": "D13", "result": "positive", "symbol": "+"}},
      {{"cycle_day": 14, "label": "D14", "result": "unknown", "symbol": "?"}},
      {{"cycle_day": 15, "label": "D15", "result": "unknown", "symbol": "?"}}
    ],
    "summary": [
      {{"label": "Window", "value": "Days 10-15"}},
      {{"label": "OPK peak", "value": "Day 13"}},
      {{"label": "BBT confirmed", "value": "Day 16"}}
    ]
  }},
  "lh_surge_detection": {{
    "title": "LH Surge detected on Day 13",
    "message": "Ovulation was expected Day 14-15. BBT confirmed actual ovulation Day 16, two-day offset noted.",
    "status": "detected",
    "surge_day": 13,
    "expected_ovulation_window": "Day 14-15",
    "bbt_confirmed_day": 16
  }},
  "log_todays_test": {{
    "title": "Log today's test - Day 17",
    "guidance": "You are past the main testing window. OPK is less predictive post-ovulation; results here are logged for your record but will not affect this cycle's fertile window prediction.",
    "options": [
      {{"label": "Negative", "symbol": "-", "description": "LH not elevated", "state": "negative"}},
      {{"label": "Almost", "symbol": "-", "description": "LH rising", "state": "almost"}},
      {{"label": "Positive", "symbol": "+", "description": "LH surge", "state": "positive"}}
    ]
  }},
  "cervical_mucus": {{
    "title": "Cervical mucus",
    "description": "Supports OPK - lowest reliability alone, highest combined.",
    "note": "Egg-white mucus indicates peak fertility signal.",
    "options": [
      {{"label": "Dry", "description": "No moisture", "fertility": "Low fertility"}},
      {{"label": "Sticky", "description": "Thick, crumbly", "fertility": "Low fertility"}},
      {{"label": "Creamy", "description": "Lotion-like", "fertility": "Moderate"}},
      {{"label": "Watery", "description": "Clear, thin", "fertility": "High fertility"}},
      {{"label": "Egg white", "description": "Clear, stretchy", "fertility": "Peak fertility"}}
    ]
  }}
}}

Requirements:
- Generate testing_window, lh_surge_detection, log_todays_test, and cervical_mucus.
- Include negative, almost, and positive OPK states.
- Include cervical mucus choices: Dry, Sticky, Creamy, Watery, Egg white.
- If OPK/LH logs are missing from backend context, use cautious estimated UI copy and avoid claiming clinical certainty.
- Keep all strings concise and UI-ready.
"""


def _call_opk_lh_llm(prompt: str) -> str:
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1

    for attempt in range(attempts):
        try:
            return llm_call(
                prompt=prompt,
                system=OPK_LH_SYSTEM_PROMPT,
                max_tokens=1800,
            )
        except Exception as exc:
            is_last_attempt = attempt == attempts - 1
            if not _is_retryable_llm_error(exc):
                raise
            if is_last_attempt:
                return ""
            time.sleep(LLM_RETRY_DELAYS_SECONDS[attempt])

    return ""


def _parse_opk_lh_response(text: str) -> dict[str, Any] | None:
    payload = _parse_json_object(text)
    if payload is None:
        return None

    try:
        return _coerce_opk_lh_payload(payload)
    except Exception:
        return None


def _coerce_opk_lh_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _fallback_opk_lh_analysis()

    fallback = _fallback_opk_lh_analysis()
    return {
        "info_alert": _coerce_title_message(payload.get("info_alert"), fallback["info_alert"]),
        "testing_window": _coerce_testing_window(payload.get("testing_window"), fallback["testing_window"]),
        "lh_surge_detection": _coerce_lh_surge_detection(payload.get("lh_surge_detection"), fallback["lh_surge_detection"]),
        "log_todays_test": _coerce_log_todays_test(payload.get("log_todays_test"), fallback["log_todays_test"]),
        "cervical_mucus": _coerce_cervical_mucus(payload.get("cervical_mucus"), fallback["cervical_mucus"]),
    }


def _coerce_title_message(value: Any, fallback: dict[str, str]) -> dict[str, str]:
    if not isinstance(value, dict):
        value = {}
    return {
        "title": str(value.get("title") or fallback["title"]),
        "message": str(value.get("message") or fallback["message"]),
    }


def _coerce_testing_window(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    cards = value.get("cards") if isinstance(value.get("cards"), list) else fallback["cards"]
    summary = value.get("summary") if isinstance(value.get("summary"), list) else fallback["summary"]
    return {
        "title": str(value.get("title") or fallback["title"]),
        "subtitle": str(value.get("subtitle") or fallback["subtitle"]),
        "status": str(value.get("status") or fallback["status"]),
        "cards": _coerce_testing_cards(cards, fallback["cards"]),
        "summary": _coerce_label_value_list(summary, fallback["summary"]),
    }


def _coerce_testing_cards(cards: list[Any], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    coerced = []
    for item in cards:
        if not isinstance(item, dict):
            continue
        cycle_day = _bounded_int(item.get("cycle_day"), 10 + len(coerced), 1, 60)
        coerced.append(
            {
                "cycle_day": cycle_day,
                "label": str(item.get("label") or f"D{cycle_day}"),
                "result": str(item.get("result") or "unknown"),
                "symbol": str(item.get("symbol") or "?"),
            }
        )
    return coerced or fallback


def _coerce_lh_surge_detection(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    return {
        "title": str(value.get("title") or fallback["title"]),
        "message": str(value.get("message") or fallback["message"]),
        "status": str(value.get("status") or fallback["status"]),
        "surge_day": _bounded_int(value.get("surge_day"), fallback["surge_day"], 1, 60),
        "expected_ovulation_window": str(value.get("expected_ovulation_window") or fallback["expected_ovulation_window"]),
        "bbt_confirmed_day": _bounded_int(value.get("bbt_confirmed_day"), fallback["bbt_confirmed_day"], 1, 60),
    }


def _coerce_log_todays_test(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    options = value.get("options") if isinstance(value.get("options"), list) else fallback["options"]
    return {
        "title": str(value.get("title") or fallback["title"]),
        "guidance": str(value.get("guidance") or fallback["guidance"]),
        "options": _coerce_opk_options(options, fallback["options"]),
    }


def _coerce_opk_options(options: list[Any], fallback: list[dict[str, str]]) -> list[dict[str, str]]:
    expected = ["Negative", "Almost", "Positive"]
    ordered = []
    for index, label in enumerate(expected):
        match = _find_named_option(options, label)
        source = match or fallback[index]
        ordered.append(
            {
                "label": label,
                "symbol": str(source.get("symbol") or fallback[index]["symbol"]),
                "description": str(source.get("description") or fallback[index]["description"]),
                "state": str(source.get("state") or fallback[index]["state"]),
            }
        )
    return ordered


def _coerce_cervical_mucus(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    options = value.get("options") if isinstance(value.get("options"), list) else fallback["options"]
    return {
        "title": str(value.get("title") or fallback["title"]),
        "description": str(value.get("description") or fallback["description"]),
        "note": str(value.get("note") or fallback["note"]),
        "options": _coerce_mucus_options(options, fallback["options"]),
    }


def _coerce_mucus_options(options: list[Any], fallback: list[dict[str, str]]) -> list[dict[str, str]]:
    expected = ["Dry", "Sticky", "Creamy", "Watery", "Egg white"]
    ordered = []
    for index, label in enumerate(expected):
        match = _find_named_option(options, label)
        source = match or fallback[index]
        ordered.append(
            {
                "label": label,
                "description": str(source.get("description") or fallback[index]["description"]),
                "fertility": str(source.get("fertility") or fallback[index]["fertility"]),
            }
        )
    return ordered


def _find_named_option(options: list[Any], label: str) -> dict[str, Any] | None:
    expected = _signal_key(label)
    for option in options:
        if not isinstance(option, dict):
            continue
        if _signal_key(str(option.get("label", ""))) == expected:
            return option
    return None


def _fallback_opk_lh_analysis() -> dict[str, Any]:
    return {
        "info_alert": {
            "title": "OPK is forward-looking",
            "message": "In general, OPK is the only forward-looking exact now signal. A positive LH test means ovulation is expected within 12-36 hours. BBT only confirms ovulation after it has already occurred.",
        },
        "testing_window": {
            "title": "Testing Window",
            "subtitle": "Days 10-15 - starts 4 days before predicted ovulation",
            "status": "Window closed",
            "cards": [
                {"cycle_day": 10, "label": "D10", "result": "not_tested", "symbol": "-"},
                {"cycle_day": 11, "label": "D11", "result": "not_tested", "symbol": "-"},
                {"cycle_day": 12, "label": "D12", "result": "almost", "symbol": "-"},
                {"cycle_day": 13, "label": "D13", "result": "positive", "symbol": "+"},
                {"cycle_day": 14, "label": "D14", "result": "unknown", "symbol": "?"},
                {"cycle_day": 15, "label": "D15", "result": "unknown", "symbol": "?"},
            ],
            "summary": [
                {"label": "Window", "value": "Days 10-15"},
                {"label": "OPK peak", "value": "Day 13"},
                {"label": "BBT confirmed", "value": "Day 16"},
            ],
        },
        "lh_surge_detection": {
            "title": "LH Surge detected on Day 13",
            "message": "Ovulation was expected Day 14-15. BBT confirmed actual ovulation Day 16, two-day offset noted.",
            "status": "detected",
            "surge_day": 13,
            "expected_ovulation_window": "Day 14-15",
            "bbt_confirmed_day": 16,
        },
        "log_todays_test": {
            "title": "Log today's test - Day 17",
            "guidance": "You are past the main testing window. OPK is less predictive post-ovulation; results here are logged for your record but will not affect this cycle's fertile window prediction.",
            "options": [
                {"label": "Negative", "symbol": "-", "description": "LH not elevated", "state": "negative"},
                {"label": "Almost", "symbol": "-", "description": "LH rising", "state": "almost"},
                {"label": "Positive", "symbol": "+", "description": "LH surge", "state": "positive"},
            ],
        },
        "cervical_mucus": {
            "title": "Cervical mucus",
            "description": "Supports OPK - lowest reliability alone, highest combined.",
            "note": "Egg-white mucus indicates peak fertility signal.",
            "options": [
                {"label": "Dry", "description": "No moisture", "fertility": "Low fertility"},
                {"label": "Sticky", "description": "Thick, crumbly", "fertility": "Low fertility"},
                {"label": "Creamy", "description": "Lotion-like", "fertility": "Moderate"},
                {"label": "Watery", "description": "Clear, thin", "fertility": "High fertility"},
                {"label": "Egg white", "description": "Clear, stretchy", "fertility": "Peak fertility"},
            ],
        },
    }
def _build_engine_prompt(user_profile: Any, snapshot: Any) -> str:
    context = json.dumps(
        {
            "user_profile": user_profile,
            "snapshot": snapshot,
        },
        ensure_ascii=False,
        default=str,
    )[:MAX_CONTEXT_CHARS]

    return f"""Generate only the Engine section for a cycle engine UI.

Backend context JSON:
{context}

Return JSON with exactly this structure:
{{
  "status": "Moderate",
  "confidence_dots": 3,
  "confidence_max": 5,
  "summary": "Based on available cycle and wellness data. Improving with each logged cycle.",
  "signal_hierarchy": {{
    "title": "Signal Hierarchy",
    "subtitle": "Layered by reliability. Disagreements shown, not hidden.",
    "signals": [
      {{
        "name": "Calendar",
        "rank": 1,
        "state": "active",
        "headline": "Predicts ovulation window from logged cycle pattern",
        "detail": "Baseline predictor; lower reliability alone.",
        "reliability": "baseline"
      }},
      {{
        "name": "OPK / LH",
        "rank": 2,
        "state": "not_logged",
        "headline": "Not yet logged today",
        "detail": "Forward-looking signal when LH data is available.",
        "reliability": "high when logged"
      }},
      {{
        "name": "BBT",
        "rank": 3,
        "state": "not_logged",
        "headline": "No reading today",
        "detail": "Confirms ovulation after the fact only.",
        "reliability": "confirmation"
      }},
      {{
        "name": "Mucus",
        "rank": 4,
        "state": "not_logged",
        "headline": "Not yet logged today",
        "detail": "Supports OPK and calendar signals when available.",
        "reliability": "supporting"
      }}
    ],
    "disagreement_note": "Calendar, OPK/LH, BBT, and mucus signals should be compared together as more logs become available."
  }}
}}

Requirements:
- status must be exactly "Moderate".
- signal_hierarchy.signals must include Calendar, OPK / LH, BBT, and Mucus in that order.
- Use available profile/snapshot context if relevant.
- Do not invent exact ovulation days, BBT readings, OPK values, or mucus logs unless present in the backend context.
"""


def _call_engine_llm(prompt: str) -> str:
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1

    for attempt in range(attempts):
        try:
            return llm_call(
                prompt=prompt,
                system=CYCLE_ENGINE_SYSTEM_PROMPT,
                max_tokens=1400,
            )
        except Exception as exc:
            is_last_attempt = attempt == attempts - 1
            if not _is_retryable_llm_error(exc):
                raise
            if is_last_attempt:
                return ""
            time.sleep(LLM_RETRY_DELAYS_SECONDS[attempt])

    return ""


def _parse_engine_response(text: str) -> dict[str, Any] | None:
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
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None

    try:
        return _coerce_engine_payload(payload)
    except Exception:
        return None



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
def _coerce_engine_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _fallback_engine_analysis()

    fallback = _fallback_engine_analysis()
    signal_hierarchy = payload.get("signal_hierarchy")
    if not isinstance(signal_hierarchy, dict):
        signal_hierarchy = fallback["signal_hierarchy"]

    return {
        "status": "Moderate",
        "confidence_dots": _bounded_int(payload.get("confidence_dots"), 3, 0, 5),
        "confidence_max": _bounded_int(payload.get("confidence_max"), 5, 1, 5),
        "summary": str(payload.get("summary") or fallback["summary"]),
        "signal_hierarchy": _coerce_signal_hierarchy(signal_hierarchy),
    }


def _coerce_signal_hierarchy(value: dict[str, Any]) -> dict[str, Any]:
    fallback = _fallback_engine_analysis()["signal_hierarchy"]
    signals = value.get("signals") if isinstance(value, dict) else None
    if not isinstance(signals, list):
        signals = fallback["signals"]

    return {
        "title": str(value.get("title") or fallback["title"]),
        "subtitle": str(value.get("subtitle") or fallback["subtitle"]),
        "signals": _ordered_signals(signals),
        "disagreement_note": str(value.get("disagreement_note") or fallback["disagreement_note"]),
    }


def _ordered_signals(signals: list[Any]) -> list[dict[str, Any]]:
    fallback_signals = _fallback_engine_analysis()["signal_hierarchy"]["signals"]
    expected = ["Calendar", "OPK / LH", "BBT", "Mucus"]
    ordered = []

    for index, name in enumerate(expected):
        match = _find_signal(signals, name)
        ordered.append(_coerce_signal(match, fallback_signals[index], name, index + 1))

    return ordered


def _find_signal(signals: list[Any], expected_name: str) -> dict[str, Any] | None:
    expected_key = _signal_key(expected_name)
    for signal in signals:
        if not isinstance(signal, dict):
            continue
        if _signal_key(str(signal.get("name", ""))) == expected_key:
            return signal
    return None


def _coerce_signal(value: dict[str, Any] | None, fallback: dict[str, Any], name: str, rank: int) -> dict[str, Any]:
    value = value or {}
    return {
        "name": name,
        "rank": rank,
        "state": str(value.get("state") or fallback["state"]),
        "headline": str(value.get("headline") or fallback["headline"]),
        "detail": str(value.get("detail") or fallback["detail"]),
        "reliability": str(value.get("reliability") or fallback["reliability"]),
    }


def _signal_key(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


def _fallback_engine_analysis() -> dict[str, Any]:
    return {
        "status": "Moderate",
        "confidence_dots": 3,
        "confidence_max": 5,
        "summary": "Based on available cycle and wellness data. Improving with each logged cycle.",
        "signal_hierarchy": {
            "title": "Signal Hierarchy",
            "subtitle": "Layered by reliability. Disagreements shown, not hidden.",
            "signals": [
                {
                    "name": "Calendar",
                    "rank": 1,
                    "state": "active",
                    "headline": "Predicts ovulation window from logged cycle pattern",
                    "detail": "Baseline predictor; lower reliability alone.",
                    "reliability": "baseline",
                },
                {
                    "name": "OPK / LH",
                    "rank": 2,
                    "state": "not_logged",
                    "headline": "Not yet logged today",
                    "detail": "Forward-looking signal when LH data is available.",
                    "reliability": "high when logged",
                },
                {
                    "name": "BBT",
                    "rank": 3,
                    "state": "not_logged",
                    "headline": "No reading today",
                    "detail": "Confirms ovulation after the fact only.",
                    "reliability": "confirmation",
                },
                {
                    "name": "Mucus",
                    "rank": 4,
                    "state": "not_logged",
                    "headline": "Not yet logged today",
                    "detail": "Supports OPK and calendar signals when available.",
                    "reliability": "supporting",
                },
            ],
            "disagreement_note": "Calendar, OPK/LH, BBT, and mucus signals should be compared together as more logs become available.",
        },
    }


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


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


def _is_retryable_llm_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in RETRYABLE_LLM_STATUS_CODES:
        return True

    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "overloaded",
            "rate_limit",
            "rate limit",
            "temporarily unavailable",
            "timeout",
        )
    )
