import json
import time
from datetime import date
from typing import Any

import httpx

from ai.config import settings
from ai.utils.llm_call import llm_call


RETRYABLE_LLM_STATUS_CODES = {429, 500, 502, 503, 529}
LLM_RETRY_DELAYS_SECONDS = (1.0, 2.0)
MAX_CONTEXT_CHARS = 10000


DAILY_SCRIPTURE_SYSTEM_PROMPT = """You are a careful daily scripture selection assistant.

Rules:
- Use only the user profile and health logs JSON provided as wellbeing context.
- Select one appropriate Bible scripture for the requested date.
- Do not diagnose, prescribe, or claim medical certainty.
- Keep the output UI-ready for a small daily scripture card.
- Prefer short, public-domain-style wording suitable for display.
- Return valid JSON only. Do not add markdown, code fences, or extra commentary.
"""


SCRIPTURE_FALLBACKS = [
    {
        "badge": "Peace",
        "verse_text": "Thou wilt keep him in perfect peace, whose mind is stayed on thee: because he trusteth in thee.",
        "reference": "Isaiah 26:3",
        "translation": "KJV",
    },
    {
        "badge": "Strength",
        "verse_text": "I can do all things through Christ which strengtheneth me.",
        "reference": "Philippians 4:13",
        "translation": "KJV",
    },
    {
        "badge": "Hope",
        "verse_text": "Now faith is the substance of things hoped for, the evidence of things not seen.",
        "reference": "Hebrews 11:1",
        "translation": "KJV",
    },
    {
        "badge": "Rest",
        "verse_text": "Come unto me, all ye that labour and are heavy laden, and I will give you rest.",
        "reference": "Matthew 11:28",
        "translation": "KJV",
    },
    {
        "badge": "Courage",
        "verse_text": "Be strong and of a good courage; be not afraid, neither be thou dismayed.",
        "reference": "Joshua 1:9",
        "translation": "KJV",
    },
    {
        "badge": "Joy",
        "verse_text": "The joy of the Lord is your strength.",
        "reference": "Nehemiah 8:10",
        "translation": "KJV",
    },
    {
        "badge": "Guidance",
        "verse_text": "Thy word is a lamp unto my feet, and a light unto my path.",
        "reference": "Psalm 119:105",
        "translation": "KJV",
    },
]


def fetch_daily_scripture_data() -> dict[str, Any]:
    today = date.today().isoformat()
    user_profile, profile_error = _try_get_backend_json(settings.CYCLE_ENGINE_PROFILE_URL)
    health_logs, health_logs_error = _try_get_backend_json(settings.HEALTH_TRENDS_HEALTH_LOGS_URL)
    backend_errors = {}
    if profile_error:
        backend_errors["user_profile"] = profile_error
    if health_logs_error:
        backend_errors["health_logs"] = health_logs_error

    daily_scripture = _generate_daily_scripture(today, user_profile, health_logs)

    return {
        "status": "ready",
        "service": "daily_scripture",
        "fetched": not backend_errors,
        "sources": {
            "user_profile": settings.CYCLE_ENGINE_PROFILE_URL,
            "health_logs": settings.HEALTH_TRENDS_HEALTH_LOGS_URL,
        },
        "backend_errors": backend_errors,
        "daily_scripture": daily_scripture,
        "user_profile": user_profile,
        "health_logs": health_logs,
    }


def _generate_daily_scripture(today: str, user_profile: Any, health_logs: Any) -> dict[str, Any]:
    prompt = _build_daily_scripture_prompt(today, user_profile, health_logs)
    response_text = _call_daily_scripture_llm(prompt)
    parsed = _parse_daily_scripture_response(response_text, today)
    if parsed:
        return parsed
    return _fallback_daily_scripture(today)


def _build_daily_scripture_prompt(today: str, user_profile: Any, health_logs: Any) -> str:
    context = json.dumps(
        {
            "date": today,
            "user_profile": user_profile,
            "health_logs": health_logs,
        },
        ensure_ascii=False,
        default=str,
    )[:MAX_CONTEXT_CHARS]

    return f"""Generate one Daily Scripture card for this date: {today}.

Backend context JSON:
{context}

Return JSON with exactly this structure:
{{
  "title": "Daily Scripture",
  "date": "{today}",
  "badge": "Peace",
  "verse_text": "Do not be anxious about anything, but in every situation present your requests to God. And the peace of God will guard your hearts.",
  "reference": "Philippians 4:6-7",
  "translation": "public-domain-style",
  "reason": "Chosen to support calm and emotional steadiness today."
}}

Requirements:
- Generate exactly one verse for the day.
- Use the health logs to choose a helpful theme such as Peace, Rest, Strength, Hope, Courage, Joy, or Guidance.
- The same date should lead to the same kind of daily card.
- Keep verse_text concise enough for a compact mobile card.
- Do not include medical advice.
"""


def _call_daily_scripture_llm(prompt: str) -> str:
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1

    for attempt in range(attempts):
        try:
            return llm_call(
                prompt=prompt,
                system=DAILY_SCRIPTURE_SYSTEM_PROMPT,
                max_tokens=700,
            )
        except Exception as exc:
            is_last_attempt = attempt == attempts - 1
            if not _is_retryable_llm_error(exc):
                raise
            if is_last_attempt:
                return ""
            time.sleep(LLM_RETRY_DELAYS_SECONDS[attempt])

    return ""


def _parse_daily_scripture_response(text: str, today: str) -> dict[str, Any] | None:
    payload = _parse_json_object(text)
    if payload is None:
        return None

    try:
        return _coerce_daily_scripture_payload(payload, today)
    except Exception:
        return None


def _coerce_daily_scripture_payload(payload: Any, today: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _fallback_daily_scripture(today)

    fallback = _fallback_daily_scripture(today)
    return {
        "title": str(payload.get("title") or fallback["title"]),
        "date": str(payload.get("date") or today),
        "badge": str(payload.get("badge") or fallback["badge"]),
        "verse_text": str(payload.get("verse_text") or fallback["verse_text"]),
        "reference": str(payload.get("reference") or fallback["reference"]),
        "translation": str(payload.get("translation") or fallback["translation"]),
        "reason": str(payload.get("reason") or fallback["reason"]),
    }


def _fallback_daily_scripture(today: str) -> dict[str, Any]:
    selected = SCRIPTURE_FALLBACKS[date.fromisoformat(today).toordinal() % len(SCRIPTURE_FALLBACKS)]
    return {
        "title": "Daily Scripture",
        "date": today,
        "badge": selected["badge"],
        "verse_text": selected["verse_text"],
        "reference": selected["reference"],
        "translation": selected["translation"],
        "reason": "Chosen as a steady daily encouragement based on today's wellbeing context.",
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
