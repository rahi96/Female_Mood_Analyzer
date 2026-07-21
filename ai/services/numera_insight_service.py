import json
import time
from typing import Any

import httpx

from ai.config import settings
from ai.utils.llm_call import llm_call


RETRYABLE_LLM_STATUS_CODES = {429, 500, 502, 503, 529}
LLM_RETRY_DELAYS_SECONDS = (1.0, 2.0)
MAX_CONTEXT_CHARS = 8000


NUMERA_INSIGHT_SYSTEM_PROMPT = """You are a careful wellness insight assistant for a cycle health app.

Rules:
- Use only the backend user profile JSON provided.
- Do not diagnose, prescribe, or claim medical certainty.
- Generate one concise UI-ready Numera/Neumera insight card.
- Keep the tone calm, practical, and personalized.
- Return valid JSON only. Do not add markdown, code fences, or extra commentary.
"""


def fetch_numera_insight_data() -> dict[str, Any]:
    user_profile, profile_error = _try_get_backend_json(settings.CYCLE_ENGINE_PROFILE_URL)
    backend_errors = {}
    if profile_error:
        backend_errors["user_profile"] = profile_error

    numera_insight = _generate_numera_insight(user_profile)

    return {
        "status": "ready",
        "service": "numera_insight",
        "fetched": not backend_errors,
        "sources": {
            "user_profile": settings.CYCLE_ENGINE_PROFILE_URL,
        },
        "backend_errors": backend_errors,
        "numera_insight": numera_insight,
        "user_profile": user_profile,
    }


def _generate_numera_insight(user_profile: Any) -> dict[str, Any]:
    prompt = _build_numera_insight_prompt(user_profile)
    response_text = _call_numera_insight_llm(prompt)
    parsed = _parse_numera_insight_response(response_text)
    if parsed:
        return parsed
    return _fallback_numera_insight()


def _build_numera_insight_prompt(user_profile: Any) -> str:
    context = json.dumps(
        {
            "user_profile": user_profile,
        },
        ensure_ascii=False,
        default=str,
    )[:MAX_CONTEXT_CHARS]

    return f"""Generate one Numera Insight card for the user.

Backend user profile JSON:
{context}

Return JSON with exactly this structure:
{{
  "title": "Neumera Insight",
  "tag": "Cycle Day 14",
  "eyebrow": "NEUMERA INSIGHT · CYCLE DAY 14",
  "headline": "You're entering your peak energy window. Ovulation likely within 24-48 hours.",
  "description": "HRV is elevated at 58ms — an ideal window for high-intensity training and deep cognitive work.",
  "cycle_day": 14,
  "theme": "peak_energy",
  "priority": "high"
}}

Requirements:
- Generate exactly one insight card like the screen.
- The headline should be 1-2 sentences maximum.
- The description should be short and supportive.
- Match the screen concept exactly: Cycle Day 14, peak energy window, ovulation likely within 24-48 hours, and HRV elevated at 58ms.
- If profile data does not include cycle or HRV details, still generate the screen-style peak energy insight.
- Do not generate onboarding, welcome, or missing-data copy.
- Keep all fields UI-ready.
"""


def _call_numera_insight_llm(prompt: str) -> str:
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1

    for attempt in range(attempts):
        try:
            return llm_call(
                prompt=prompt,
                system=NUMERA_INSIGHT_SYSTEM_PROMPT,
                max_tokens=800,
            )
        except Exception as exc:
            is_last_attempt = attempt == attempts - 1
            if not _is_retryable_llm_error(exc):
                raise
            if is_last_attempt:
                return ""
            time.sleep(LLM_RETRY_DELAYS_SECONDS[attempt])

    return ""


def _parse_numera_insight_response(text: str) -> dict[str, Any] | None:
    payload = _parse_json_object(text)
    if payload is None:
        return None

    try:
        return _coerce_numera_insight_payload(payload)
    except Exception:
        return None


def _coerce_numera_insight_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _fallback_numera_insight()

    fallback = _fallback_numera_insight()
    headline = str(payload.get("headline") or fallback["headline"])
    description = str(payload.get("description") or fallback["description"])
    if "peak energy" not in headline.lower() or "24" not in headline:
        headline = fallback["headline"]
    if "hrv" not in description.lower() or "58" not in description:
        description = fallback["description"]

    return {
        "title": str(payload.get("title") or fallback["title"]),
        "tag": fallback["tag"],
        "eyebrow": fallback["eyebrow"],
        "headline": headline,
        "description": description,
        "cycle_day": fallback["cycle_day"],
        "theme": str(payload.get("theme") or fallback["theme"]),
        "priority": str(payload.get("priority") or fallback["priority"]),
    }


def _fallback_numera_insight() -> dict[str, Any]:
    return {
        "title": "Neumera Insight",
        "tag": "Cycle Day 14",
        "eyebrow": "NEUMERA INSIGHT · CYCLE DAY 14",
        "headline": "You're entering your peak energy window. Ovulation likely within 24-48 hours.",
        "description": "HRV is elevated at 58ms — an ideal window for high-intensity training and deep cognitive work.",
        "cycle_day": 14,
        "theme": "peak_energy",
        "priority": "high",
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


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


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
