import json
import time
import hashlib
import httpx
from datetime import date
from typing import Any

from ai.utils.llm_call import llm_call
from ai.models.bbt_models import (
    CycleInsightsRequest,
    CycleInsightsResponse,
    DailyTipRequest,
    DailyTipResponse,
    DailyVerseRequest,
    DailyVerseResponse,
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


DAILY_TIP_SYSTEM_PROMPT = """You are a women's health and BBT tracking expert.

Rules:
- Based on the user's health data, generate ONE short, practical daily tip.
- The tip must be 1-2 sentences, written in a warm but professional tone.
- Focus on actionable advice related to their temperature patterns, cycle phase, or general reproductive health tracking.
- If data is limited, give a general BBT tracking best-practice tip.
- Do not return JSON, markdown, bullets, a title, or a heading.
- Do not include medical disclaimers in the tip itself.
"""


def generate_daily_tip(request: DailyTipRequest) -> DailyTipResponse:
    user_data = fetch_backend_data(request.user_id)

    prompt = f"""Based on this user's health data, generate one short daily tip.

User health data:
{_to_pretty_json(user_data)}

Generate only one short, practical daily tip for the user."""

    tip_text = _generate_daily_tip_text(prompt)

    return DailyTipResponse(
        title="Daily Tip",
        tip=tip_text or _fallback_daily_tip(),
    )


def _generate_daily_tip_text(prompt: str) -> str:
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1

    for attempt in range(attempts):
        try:
            response_text = llm_call(
                prompt=prompt,
                system=DAILY_TIP_SYSTEM_PROMPT,
                max_tokens=150,
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


def _fallback_daily_tip() -> str:
    return (
        "Track your basal body temperature first thing in the morning "
        "for the most accurate ovulation predictions."
    )


_verse_cache: dict[str, DailyVerseResponse] = {}


DAILY_VERSE_SYSTEM_PROMPT = """You are a spiritual guide who shares uplifting Bible verses.

Rules:
- Return exactly ONE verse from the Bible (Psalms, Proverbs, Isaiah, Jeremiah, Matthew, etc.).
- The verse must be encouraging, uplifting, and related to hope, strength, healing, or gratitude.
- Format your response as exactly two lines:
  Line 1: The verse text (in quotation marks)
  Line 2: The reference (e.g. Psalm 139:14, Jeremiah 29:11)
- Do not add commentary, explanation, markdown, or any extra text.
- Each unique seed number should produce a different verse.
"""


def generate_daily_verse(request: DailyVerseRequest) -> DailyVerseResponse:
    today = date.today().isoformat()
    cache_key = f"{today}:{request.user_id}"

    if cache_key in _verse_cache:
        return _verse_cache[cache_key]

    seed = int(hashlib.md5(cache_key.encode()).hexdigest()[:8], 16)

    prompt = f"""Generate one uplifting Bible verse for today.

Seed number: {seed}

Return the verse in quotation marks on the first line, and the scripture reference on the second line."""

    verse_response = _generate_verse_text(prompt)

    if not verse_response:
        verse_response = _fallback_daily_verse(seed)

    _verse_cache[cache_key] = verse_response

    return verse_response


def _generate_verse_text(prompt: str) -> DailyVerseResponse | None:
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1

    for attempt in range(attempts):
        try:
            response_text = llm_call(
                prompt=prompt,
                system=DAILY_VERSE_SYSTEM_PROMPT,
                max_tokens=200,
            )
            return _parse_verse_response(response_text)
        except Exception as exc:
            is_last_attempt = attempt == attempts - 1
            if not _is_retryable_llm_error(exc):
                raise
            if is_last_attempt:
                return None
            time.sleep(LLM_RETRY_DELAYS_SECONDS[attempt])

    return None


def _parse_verse_response(text: str) -> DailyVerseResponse | None:
    text = text.strip()
    if not text:
        return None

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    if len(lines) >= 2:
        verse = lines[0].strip('"\u201c\u201d')
        reference = lines[-1].lstrip("\u2014- ").strip()
        return DailyVerseResponse(verse=verse, reference=reference)

    return None


_FALLBACK_VERSES = [
    DailyVerseResponse(
        verse="I praise you because I am fearfully and wonderfully made; your works are wonderful, I know that full well.",
        reference="Psalm 139:14",
    ),
    DailyVerseResponse(
        verse="For I know the plans I have for you, declares the LORD, plans to prosper you and not to harm you, plans to give you hope and a future.",
        reference="Jeremiah 29:11",
    ),
    DailyVerseResponse(
        verse="The LORD is my shepherd; I shall not want. He makes me lie down in green pastures. He leads me beside still waters. He restores my soul.",
        reference="Psalm 23:1-3",
    ),
    DailyVerseResponse(
        verse="So do not fear, for I am with you; do not be dismayed, for I am your God. I will strengthen you and help you.",
        reference="Isaiah 41:10",
    ),
    DailyVerseResponse(
        verse="Come to me, all you who are weary and burdened, and I will give you rest.",
        reference="Matthew 11:28",
    ),
    DailyVerseResponse(
        verse="He heals the brokenhearted and binds up their wounds.",
        reference="Psalm 147:3",
    ),
    DailyVerseResponse(
        verse="Trust in the LORD with all your heart and lean not on your own understanding; in all your ways submit to him, and he will make your paths straight.",
        reference="Proverbs 3:5-6",
    ),
]


def _fallback_daily_verse(seed: int) -> DailyVerseResponse:
    return _FALLBACK_VERSES[seed % len(_FALLBACK_VERSES)]
