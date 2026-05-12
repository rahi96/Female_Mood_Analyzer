import json
import time
import httpx
from typing import Any

from ai.utils.llm_call import llm_call
from ai.models.bbt_models import (
    CycleInsightsRequest,
    CycleInsightsResponse,
)
from ai.config import settings


SYSTEM_PROMPT = """You are a BBT (Basal Body Temperature) cycle analysis expert.

Rules:
- Analyze only the temperature report data provided by the backend.
- Return one simple, friendly cycle insight tip in 1-2 short sentences.
- Mention the likely temperature pattern in plain language when the data supports it.
- If the temperature report is limited or missing, say more readings are needed.
- Do not return JSON, markdown, bullets, a title, or a heading.
"""


RETRYABLE_LLM_STATUS_CODES = {429, 500, 502, 503, 529}
LLM_RETRY_DELAYS_SECONDS = (1.0, 2.0)


def fetch_backend_data(user_id: str) -> dict:
    return _get_backend_json(f"/user/onboarding-log-temperature-for-ai/{user_id}")


def fetch_cycle_temperature_report(user_id: str) -> dict:
    return _get_backend_json(f"/user/lon-temperature-report/{user_id}")


def _get_backend_json(path: str) -> dict:
    headers = {}

    if settings.BACKEND_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {settings.BACKEND_ACCESS_TOKEN}"
        headers["x-access-token"] = settings.BACKEND_ACCESS_TOKEN

    url = f"{settings.BACKEND_URL.rstrip('/')}{path}"

    response = httpx.get(url, headers=headers, timeout=30.0)
    response.raise_for_status()
    return response.json()


def analyze_cycle(request: CycleInsightsRequest) -> CycleInsightsResponse:
    payload = fetch_cycle_temperature_report(request.user_id)

    report_data = _extract_report_data(payload)
    current_phase = _extract_cycle_phase(report_data)

    prompt = f"""Analyze this temperature report from the backend.

Current phase from backend: {current_phase}

Temperature report data:
{_to_pretty_json(report_data) if report_data else "No temperature report data available"}

Generate only one short cycle insight tip for the user."""

    message = _generate_cycle_tip(prompt)

    return CycleInsightsResponse(
        cycle_phase=current_phase,
        message=message or _fallback_cycle_tip(current_phase),
    )


def _extract_report_data(payload: dict) -> Any:
    data = payload.get("data")
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    if data is not None:
        return data
    return payload


def _extract_cycle_phase(report_data: Any) -> str:
    if not isinstance(report_data, dict):
        return "Unknown"

    for key in ("currentPhase", "cyclePhase", "phase", "current_phase", "cycle_phase"):
        value = report_data.get(key)
        if isinstance(value, str) and value.strip():
            return value

    return "Unknown"


def _generate_cycle_tip(prompt: str) -> str:
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1

    for attempt in range(attempts):
        try:
            response_text = llm_call(
                prompt=prompt,
                system=SYSTEM_PROMPT,
                max_tokens=220,
            )
            return _clean_simple_response(response_text)
        except Exception as exc:
            is_last_attempt = attempt == attempts - 1
            if not _is_retryable_llm_error(exc):
                raise
            if is_last_attempt:
                return ""
            time.sleep(LLM_RETRY_DELAYS_SECONDS[attempt])

    return ""


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


def _fallback_cycle_tip(current_phase: str) -> str:
    phase = current_phase.strip().lower()

    if phase == "luteal":
        return "Keep logging your temperature at the same time each morning; steady higher readings can help confirm your luteal-phase pattern."
    if phase in {"ovulatory", "ovulation"}:
        return "Watch for a sustained temperature rise over the next few days, since that can help confirm ovulation."
    if phase == "follicular":
        return "Keep collecting daily readings; a later sustained rise can make your ovulation pattern easier to spot."
    if phase == "menstrual":
        return "Keep logging consistently during your period so the next temperature shift is easier to compare."

    return "Keep logging your temperature at the same time each morning so your cycle pattern becomes easier to understand."


def _to_pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True, default=str)


def _clean_simple_response(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        filtered = [ln for ln in lines if not ln.startswith("```")]
        text = "\n".join(filtered).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return " ".join(text.split())

    if isinstance(parsed, dict):
        for key in ("message", "response", "summary", "text"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())
        return ""

    if isinstance(parsed, str):
        return " ".join(parsed.split())

    return ""
