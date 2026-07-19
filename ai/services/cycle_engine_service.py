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


def fetch_cycle_engine_data() -> dict[str, Any]:
    user_profile = _get_backend_json(settings.CYCLE_ENGINE_PROFILE_URL)
    snapshot = _get_backend_json(settings.CYCLE_ENGINE_SNAPSHOT_URL)
    engine = _generate_engine_analysis(user_profile, snapshot)

    return {
        "status": "ready",
        "service": "cycle_engine",
        "fetched": True,
        "sources": {
            "user_profile": settings.CYCLE_ENGINE_PROFILE_URL,
            "snapshot": settings.CYCLE_ENGINE_SNAPSHOT_URL,
        },
        "engine": engine,
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
