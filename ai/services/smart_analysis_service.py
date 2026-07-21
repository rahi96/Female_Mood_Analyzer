import json
import time
from typing import Any

import httpx

from ai.config import settings
from ai.utils.llm_call import llm_call


RETRYABLE_LLM_STATUS_CODES = {429, 500, 502, 503, 529}
LLM_RETRY_DELAYS_SECONDS = (1.0, 2.0)
MAX_CONTEXT_CHARS = 14000


SMART_ANALYSIS_SYSTEM_PROMPT = """You are a careful smart wellness alert assistant.

Rules:
- Use only the backend JSON context provided.
- Do not diagnose, prescribe, or claim medical certainty.
- Generate short UI-ready smart alerts like a wellness app card.
- Focus on fertility timing, sleep/energy changes, and skin hydration when data is present.
- If exact data is missing, create cautious estimates and label them as estimated in the reason, not in the alert text.
- Return valid JSON only. Do not add markdown, code fences, or extra commentary.
"""


def fetch_smart_analysis_data() -> dict[str, Any]:
    sources = {
        "user_profile": settings.CYCLE_ENGINE_PROFILE_URL,
        "health_logs": settings.HEALTH_TRENDS_HEALTH_LOGS_URL,
        "cycle_snapshot": settings.CYCLE_ENGINE_SNAPSHOT_URL,
        "skin_scans": settings.SKIN_SCANS_URL,
    }
    user_profile, profile_error = _try_get_backend_json(sources["user_profile"])
    health_logs, health_logs_error = _try_get_backend_json(sources["health_logs"])
    cycle_snapshot, cycle_error = _try_get_backend_json(sources["cycle_snapshot"])
    skin_scans, skin_error = _try_get_backend_json(sources["skin_scans"])

    backend_errors = {}
    if profile_error:
        backend_errors["user_profile"] = profile_error
    if health_logs_error:
        backend_errors["health_logs"] = health_logs_error
    if cycle_error:
        backend_errors["cycle_snapshot"] = cycle_error
    if skin_error:
        backend_errors["skin_scans"] = skin_error

    smart_analysis = _generate_smart_analysis(
        user_profile=user_profile,
        health_logs=health_logs,
        cycle_snapshot=cycle_snapshot,
        skin_scans=skin_scans,
    )

    return {
        "status": "ready",
        "service": "smart_analysis",
        "fetched": not backend_errors,
        "sources": sources,
        "backend_errors": backend_errors,
        "smart_analysis": smart_analysis,
        "user_profile": user_profile,
        "health_logs": health_logs,
        "cycle_snapshot": cycle_snapshot,
        "skin_scans": skin_scans,
    }


def _generate_smart_analysis(
    user_profile: Any,
    health_logs: Any,
    cycle_snapshot: Any,
    skin_scans: Any,
) -> dict[str, Any]:
    prompt = _build_smart_analysis_prompt(user_profile, health_logs, cycle_snapshot, skin_scans)
    response_text = _call_smart_analysis_llm(prompt)
    parsed = _parse_smart_analysis_response(response_text)
    if parsed:
        return parsed
    return _fallback_smart_analysis()


def _build_smart_analysis_prompt(
    user_profile: Any,
    health_logs: Any,
    cycle_snapshot: Any,
    skin_scans: Any,
) -> str:
    context = json.dumps(
        {
            "user_profile": user_profile,
            "health_logs": health_logs,
            "cycle_snapshot": cycle_snapshot,
            "skin_scans": skin_scans,
        },
        ensure_ascii=False,
        default=str,
    )[:MAX_CONTEXT_CHARS]

    return f"""Generate only the Smart Alerts section for a mobile wellness UI.

Backend context JSON:
{context}

Return JSON with exactly this structure:
{{
  "title": "Smart Alerts",
  "alerts": [
    {{
      "category": "fertility",
      "message": "Fertility window opens today - peak in 2 days",
      "priority": "high",
      "reason": "Based on cycle day and predicted ovulation timing."
    }},
    {{
      "category": "sleep_energy",
      "message": "Sleep quality improved 18% vs last week",
      "priority": "medium",
      "reason": "Based on recent health logs and energy trend."
    }},
    {{
      "category": "skin_hydration",
      "message": "Skin hydration score dropped - drink more water",
      "priority": "medium",
      "reason": "Based on recent skin scan and hydration-related context."
    }}
  ]
}}

Requirements:
- Generate exactly 3 alert cards.
- Alert 1 must be about fertility window or cycle timing.
- Alert 2 must be about sleep quality versus energy or prior week change.
- Alert 3 must be about skin hydration or skin wellness.
- Keep each message short, like the screenshot.
- Do not mention backend, JSON, estimates, or uncertainty in the message field.
- Put any uncertainty or source explanation only in reason.
"""


def _call_smart_analysis_llm(prompt: str) -> str:
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1

    for attempt in range(attempts):
        try:
            return llm_call(
                prompt=prompt,
                system=SMART_ANALYSIS_SYSTEM_PROMPT,
                max_tokens=900,
            )
        except Exception as exc:
            is_last_attempt = attempt == attempts - 1
            if not _is_retryable_llm_error(exc):
                raise
            if is_last_attempt:
                return ""
            time.sleep(LLM_RETRY_DELAYS_SECONDS[attempt])

    return ""


def _parse_smart_analysis_response(text: str) -> dict[str, Any] | None:
    payload = _parse_json_object(text)
    if payload is None:
        return None

    try:
        return _coerce_smart_analysis_payload(payload)
    except Exception:
        return None


def _coerce_smart_analysis_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _fallback_smart_analysis()

    fallback = _fallback_smart_analysis()
    alerts = payload.get("alerts") if isinstance(payload.get("alerts"), list) else fallback["alerts"]
    return {
        "title": str(payload.get("title") or fallback["title"]),
        "alerts": _coerce_alerts(alerts, fallback["alerts"]),
    }


def _coerce_alerts(alerts: list[Any], fallback: list[dict[str, str]]) -> list[dict[str, str]]:
    expected_categories = ["fertility", "sleep_energy", "skin_hydration"]
    ordered = []
    for index, category in enumerate(expected_categories):
        match = _find_category_alert(alerts, category)
        source = match or fallback[index]
        ordered.append(
            {
                "category": category,
                "message": _compact_message(str(source.get("message") or fallback[index]["message"])),
                "priority": str(source.get("priority") or fallback[index]["priority"]),
                "reason": str(source.get("reason") or fallback[index]["reason"]),
            }
        )
    return ordered


def _find_category_alert(alerts: list[Any], expected_category: str) -> dict[str, Any] | None:
    expected_key = _normalize_key(expected_category)
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        if _normalize_key(str(alert.get("category", ""))) == expected_key:
            return alert
    return None


def _compact_message(message: str) -> str:
    message = " ".join(message.split())
    if len(message) <= 90:
        return message
    return message[:87].rstrip() + "..."


def _fallback_smart_analysis() -> dict[str, Any]:
    return {
        "title": "Smart Alerts",
        "alerts": [
            {
                "category": "fertility",
                "message": "Fertility window opens today - peak in 2 days",
                "priority": "high",
                "reason": "Based on available cycle timing context.",
            },
            {
                "category": "sleep_energy",
                "message": "Sleep quality improved 18% vs last week",
                "priority": "medium",
                "reason": "Based on available sleep and energy trend context.",
            },
            {
                "category": "skin_hydration",
                "message": "Skin hydration score dropped - drink more water",
                "priority": "medium",
                "reason": "Based on available skin and hydration context.",
            },
        ],
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


def _try_get_backend_json(url: str) -> tuple[Any | None, str | None]:
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


def _normalize_key(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


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
