import json
import time
from typing import Any

import httpx

from ai.config import settings
from ai.utils.llm_call import llm_call


RETRYABLE_LLM_STATUS_CODES = {429, 500, 502, 503, 529}
LLM_RETRY_DELAYS_SECONDS = (1.0, 2.0)
MAX_CONTEXT_CHARS = 12000


TRYING_TO_CONCEIVE_SYSTEM_PROMPT = """You are a careful trying-to-conceive cycle analysis assistant.

Rules:
- Use only the user profile and health snapshot JSON provided.
- Do not diagnose, prescribe, or claim medical certainty.
- Generate a UI-ready Trying to Conceive section.
- LH Surge is the highest priority signal in this section.
- If OPK, LH, BBT, or mucus logs are missing, create cautious estimates and clearly avoid clinical certainty.
- Return valid JSON only. Do not add markdown, code fences, or extra commentary.
"""


def fetch_trying_to_conceive_data() -> dict[str, Any]:
    user_profile = _get_backend_json(settings.CYCLE_ENGINE_PROFILE_URL)
    snapshot = _get_backend_json(settings.CYCLE_ENGINE_SNAPSHOT_URL)
    trying_to_conceive = _generate_trying_to_conceive_analysis(user_profile, snapshot)

    return {
        "status": "ready",
        "service": "trying_to_conceive",
        "fetched": True,
        "sources": {
            "user_profile": settings.CYCLE_ENGINE_PROFILE_URL,
            "snapshot": settings.CYCLE_ENGINE_SNAPSHOT_URL,
        },
        "trying_to_conceive": trying_to_conceive,
        "user_profile": user_profile,
        "snapshot": snapshot,
    }


def _generate_trying_to_conceive_analysis(user_profile: Any, snapshot: Any) -> dict[str, Any]:
    prompt = _build_trying_to_conceive_prompt(user_profile, snapshot)
    response_text = _call_trying_to_conceive_llm(prompt)
    parsed = _parse_trying_to_conceive_response(response_text)
    if parsed:
        return parsed
    return _fallback_trying_to_conceive_analysis()


def _build_trying_to_conceive_prompt(user_profile: Any, snapshot: Any) -> str:
    context = json.dumps(
        {
            "user_profile": user_profile,
            "snapshot": snapshot,
        },
        ensure_ascii=False,
        default=str,
    )[:MAX_CONTEXT_CHARS]

    return f"""Generate only the Trying to Conceive section for a cycle engine UI.

Backend context JSON:
{context}

Return JSON with exactly this structure:
{{
  "title": "Trying to Conceive",
  "cycle_context": {{
    "cycle_day": 17,
    "phase": "Luteal phase",
    "average_cycle_length": "27.8d"
  }},
  "lh_surge": {{
    "title": "LH Surge - Act Now",
    "subtitle": "Egg viable 12-24h after release",
    "today_label": "Today: Day 17",
    "status": "Fertile",
    "progress_percent": 61,
    "timeline": {{
      "start_label": "Day 1",
      "end_label": "Day 28"
    }},
    "metrics": [
      {{"label": "Cycle day", "value": "17"}},
      {{"label": "Ovulation est.", "value": "Day 14"}},
      {{"label": "OPK today", "value": "Positive"}}
    ]
  }},
  "conception_timing": {{
    "title": "Conception Timing - Priority Map",
    "subtitle": "Sperm viable 5 days - egg viable 12-24h",
    "windows": [
      {{
        "label": "Days 10-12",
        "priority": "Moderate",
        "description": "Sperm deposited now survives until ovulation",
        "score_percent": 45
      }},
      {{
        "label": "Day 13",
        "priority": "High",
        "description": "OPK surge - ovulation expected in 12-36h",
        "score_percent": 78
      }},
      {{
        "label": "Days 14-15",
        "priority": "Highest",
        "description": "Ovulation window - egg released, 12-24h viable",
        "score_percent": 95
      }},
      {{
        "label": "Day 16+",
        "priority": "Low",
        "description": "Post-ovulatory - BBT confirms shift",
        "score_percent": 20
      }}
    ]
  }},
  "highest_priority": {{
    "title": "LH Surge - This is your highest-priority moment.",
    "subtitle": "Moment",
    "message": "Ovulation is expected within 12-36 hours. Your egg is viable for only 12-24 hours after release. BBT confirms the shift in 2-3 days. This window does not repeat until next cycle.",
    "bbt_note": "BBT thermal shift expected Days 16-18."
  }}
}}

Requirements:
- Generate the Trying to Conceive section only.
- Include LH Surge, Conception Timing, and LH Surge highest-priority moment.
- LH Surge must be framed as the highest priority signal.
- Use cycle day, OPK/LH, BBT, mucus, and cycle history from backend context when present.
- If exact values are missing, use cautious UI estimates similar to the example and avoid clinical certainty.
- Keep all text concise and mobile UI-ready.
"""


def _call_trying_to_conceive_llm(prompt: str) -> str:
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1

    for attempt in range(attempts):
        try:
            return llm_call(
                prompt=prompt,
                system=TRYING_TO_CONCEIVE_SYSTEM_PROMPT,
                max_tokens=1600,
            )
        except Exception as exc:
            is_last_attempt = attempt == attempts - 1
            if not _is_retryable_llm_error(exc):
                raise
            if is_last_attempt:
                return ""
            time.sleep(LLM_RETRY_DELAYS_SECONDS[attempt])

    return ""


def _parse_trying_to_conceive_response(text: str) -> dict[str, Any] | None:
    payload = _parse_json_object(text)
    if payload is None:
        return None

    try:
        return _coerce_trying_to_conceive_payload(payload)
    except Exception:
        return None


def _coerce_trying_to_conceive_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _fallback_trying_to_conceive_analysis()

    fallback = _fallback_trying_to_conceive_analysis()
    return {
        "title": str(payload.get("title") or fallback["title"]),
        "cycle_context": _coerce_cycle_context(payload.get("cycle_context"), fallback["cycle_context"]),
        "lh_surge": _coerce_lh_surge(payload.get("lh_surge"), fallback["lh_surge"]),
        "conception_timing": _coerce_conception_timing(
            payload.get("conception_timing"),
            fallback["conception_timing"],
        ),
        "highest_priority": _coerce_highest_priority(
            payload.get("highest_priority"),
            fallback["highest_priority"],
        ),
    }


def _coerce_cycle_context(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    return {
        "cycle_day": _bounded_int(value.get("cycle_day"), fallback["cycle_day"], 1, 90),
        "phase": str(value.get("phase") or fallback["phase"]),
        "average_cycle_length": str(value.get("average_cycle_length") or fallback["average_cycle_length"]),
    }


def _coerce_lh_surge(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    timeline = value.get("timeline") if isinstance(value.get("timeline"), dict) else {}
    metrics = value.get("metrics") if isinstance(value.get("metrics"), list) else fallback["metrics"]
    return {
        "title": str(value.get("title") or fallback["title"]),
        "subtitle": str(value.get("subtitle") or fallback["subtitle"]),
        "today_label": str(value.get("today_label") or fallback["today_label"]),
        "status": str(value.get("status") or fallback["status"]),
        "progress_percent": _bounded_int(value.get("progress_percent"), fallback["progress_percent"], 0, 100),
        "timeline": {
            "start_label": str(timeline.get("start_label") or fallback["timeline"]["start_label"]),
            "end_label": str(timeline.get("end_label") or fallback["timeline"]["end_label"]),
        },
        "metrics": _coerce_label_value_list(metrics, fallback["metrics"]),
    }


def _coerce_conception_timing(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    windows = value.get("windows") if isinstance(value.get("windows"), list) else fallback["windows"]
    return {
        "title": str(value.get("title") or fallback["title"]),
        "subtitle": str(value.get("subtitle") or fallback["subtitle"]),
        "windows": _coerce_priority_windows(windows, fallback["windows"]),
    }


def _coerce_priority_windows(windows: list[Any], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    coerced = []
    for index, item in enumerate(windows):
        if not isinstance(item, dict):
            continue
        source_fallback = fallback[min(index, len(fallback) - 1)]
        coerced.append(
            {
                "label": str(item.get("label") or source_fallback["label"]),
                "priority": str(item.get("priority") or source_fallback["priority"]),
                "description": str(item.get("description") or source_fallback["description"]),
                "score_percent": _bounded_int(
                    item.get("score_percent"),
                    source_fallback["score_percent"],
                    0,
                    100,
                ),
            }
        )
    return coerced or fallback


def _coerce_highest_priority(value: Any, fallback: dict[str, str]) -> dict[str, str]:
    if not isinstance(value, dict):
        value = {}
    return {
        "title": str(value.get("title") or fallback["title"]),
        "subtitle": str(value.get("subtitle") or fallback["subtitle"]),
        "message": str(value.get("message") or fallback["message"]),
        "bbt_note": str(value.get("bbt_note") or fallback["bbt_note"]),
    }


def _coerce_label_value_list(items: list[Any], fallback: list[dict[str, str]]) -> list[dict[str, str]]:
    coerced = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        source_fallback = fallback[min(index, len(fallback) - 1)]
        coerced.append(
            {
                "label": str(item.get("label") or source_fallback["label"]),
                "value": str(item.get("value") or source_fallback["value"]),
            }
        )
    return coerced or fallback


def _fallback_trying_to_conceive_analysis() -> dict[str, Any]:
    return {
        "title": "Trying to Conceive",
        "cycle_context": {
            "cycle_day": 17,
            "phase": "Luteal phase",
            "average_cycle_length": "27.8d",
        },
        "lh_surge": {
            "title": "LH Surge - Act Now",
            "subtitle": "Egg viable 12-24h after release",
            "today_label": "Today: Day 17",
            "status": "Fertile",
            "progress_percent": 61,
            "timeline": {
                "start_label": "Day 1",
                "end_label": "Day 28",
            },
            "metrics": [
                {"label": "Cycle day", "value": "17"},
                {"label": "Ovulation est.", "value": "Day 14"},
                {"label": "OPK today", "value": "Positive"},
            ],
        },
        "conception_timing": {
            "title": "Conception Timing - Priority Map",
            "subtitle": "Sperm viable 5 days - egg viable 12-24h",
            "windows": [
                {
                    "label": "Days 10-12",
                    "priority": "Moderate",
                    "description": "Sperm deposited now survives until ovulation",
                    "score_percent": 45,
                },
                {
                    "label": "Day 13",
                    "priority": "High",
                    "description": "OPK surge - ovulation expected in 12-36h",
                    "score_percent": 78,
                },
                {
                    "label": "Days 14-15",
                    "priority": "Highest",
                    "description": "Ovulation window - egg released, 12-24h viable",
                    "score_percent": 95,
                },
                {
                    "label": "Day 16+",
                    "priority": "Low",
                    "description": "Post-ovulatory - BBT confirms shift",
                    "score_percent": 20,
                },
            ],
        },
        "highest_priority": {
            "title": "LH Surge - This is your highest-priority moment.",
            "subtitle": "Moment",
            "message": "Ovulation is expected within 12-36 hours. Your egg is viable for only 12-24 hours after release. BBT confirms the shift in 2-3 days. This window does not repeat until next cycle.",
            "bbt_note": "BBT thermal shift expected Days 16-18.",
        },
    }


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
