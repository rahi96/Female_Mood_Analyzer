import json
import time
from datetime import date, datetime, timedelta
from typing import Any, Optional

import httpx

from ai.config import settings
from ai.utils.db import get_user_profile, get_connection
from ai.utils.llm_call import llm_call


RETRYABLE_LLM_STATUS_CODES = {429, 500, 502, 503, 529}
LLM_RETRY_DELAYS_SECONDS = (1.0, 2.0)
MAX_CONTEXT_CHARS = 8000


# Cycle phase definitions with themes
CYCLE_PHASES = {
    "menstrual": {
        "days": (1, 5),
        "theme": "rest_recovery",
        "priority": "medium",
        "energy": "low",
    },
    "follicular": {
        "days": (6, 11),
        "theme": "rising_energy",
        "priority": "medium",
        "energy": "building",
    },
    "ovulation": {
        "days": (12, 16),
        "theme": "peak_energy",
        "priority": "high",
        "energy": "peak",
    },
    "luteal": {
        "days": (17, 28),
        "theme": "winding_down",
        "priority": "medium",
        "energy": "declining",
    },
}


NUMERA_INSIGHT_SYSTEM_PROMPT = """You are a careful wellness insight assistant for a cycle health app.

Rules:
- Use only the user data provided (cycle day, HRV, phase, profile).
- Do not diagnose, prescribe, or claim medical certainty.
- Generate one concise UI-ready Numera/Neumera insight card.
- Keep the tone calm, practical, and personalized.
- If user name is available, use it naturally in the headline.
- Return valid JSON only. Do not add markdown, code fences, or extra commentary.
"""


def fetch_numera_insight_data(user_id: int) -> dict[str, Any]:
    user_profile = _serialize(get_user_profile(user_id))
    
    # Check if user has profile data
    if not user_profile or not user_profile.get("id"):
        return {
            "status": "empty",
            "service": "numera_insight",
            "fetched": True,
            "sources": {"database": "mysql"},
            "user_id": user_id,
            "message": "No profile data yet",
            "description": "Complete your profile to see personalized Numera insights.",
        }
    
    # Fetch real user data
    cycle_data = _get_user_cycle_data(user_id)
    hrv_data = _get_user_hrv_data(user_id)
    
    # Generate personalized insight
    numera_insight = _generate_numera_insight(user_profile, cycle_data, hrv_data)

    return {
        "status": "ready",
        "service": "numera_insight",
        "fetched": True,
        "sources": {"database": "mysql"},
        "numera_insight": numera_insight,
        "user_profile": user_profile,
    }


def _serialize(data: Any) -> Any:
    """Convert DB rows (dates, decimals) to JSON-safe values."""
    return json.loads(json.dumps(data, default=str)) if data is not None else None


def _get_user_cycle_data(user_id: int) -> dict[str, Any]:
    """Fetch real cycle day from menstrual_cycles table."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Get the most recent period start date
            cursor.execute("""
                SELECT period_start_date, period_end_date, cycle_length
                FROM menstrual_cycles
                WHERE user_id = %s AND period_start_date IS NOT NULL
                ORDER BY period_start_date DESC
                LIMIT 1
            """, (user_id,))
            row = cursor.fetchone()
            
            if not row or not row.get("period_start_date"):
                return {"cycle_day": None, "phase": None, "has_data": False}
            
            period_start = row["period_start_date"]
            if isinstance(period_start, str):
                period_start = datetime.fromisoformat(period_start).date()
            elif isinstance(period_start, datetime):
                period_start = period_start.date()
            
            # Calculate cycle day
            today = date.today()
            cycle_day = (today - period_start).days + 1
            
            # Handle cycle overflow (assume 28-day cycle if not specified)
            cycle_length = row.get("cycle_length") or 28
            if cycle_day > cycle_length:
                cycle_day = ((cycle_day - 1) % cycle_length) + 1
            
            # Determine phase
            phase = _get_cycle_phase(cycle_day)
            
            return {
                "cycle_day": cycle_day,
                "phase": phase,
                "cycle_length": cycle_length,
                "period_start_date": str(period_start),
                "has_data": True,
            }
    except Exception as e:
        print(f"[ERROR] _get_user_cycle_data failed: {e}")
        return {"cycle_day": None, "phase": None, "has_data": False}


def _get_user_hrv_data(user_id: int) -> dict[str, Any]:
    """Fetch real HRV from terra_activity_data."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Get most recent Terra data with HRV
            cursor.execute("""
                SELECT payload, type, created_at
                FROM terra_activity_data
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 5
            """, (user_id,))
            rows = cursor.fetchall()
            
            if not rows:
                return {"hrv": None, "has_data": False}
            
            # Extract HRV from payload
            for row in rows:
                try:
                    payload = row.get("payload")
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    
                    hrv = None
                    
                    # Try payload.hrv.value first
                    if payload.get("hrv", {}).get("value"):
                        hrv = float(payload["hrv"]["value"])
                    
                    # Fallback: payload.data[].heart_rate_data.summary.avg_hrv_rmssd
                    if hrv is None:
                        data_list = payload.get("data", [])
                        for item in data_list:
                            hrv_val = item.get("heart_rate_data", {}).get("summary", {}).get("avg_hrv_rmssd")
                            if hrv_val is not None:
                                hrv = float(hrv_val)
                                break
                    
                    if hrv is not None:
                        # Determine HRV status
                        hrv_status = _get_hrv_status(hrv)
                        return {
                            "hrv": round(hrv, 0),
                            "hrv_status": hrv_status,
                            "has_data": True,
                        }
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
            
            return {"hrv": None, "has_data": False}
    except Exception as e:
        print(f"[ERROR] _get_user_hrv_data failed: {e}")
        return {"hrv": None, "has_data": False}


def _get_cycle_phase(cycle_day: int) -> str:
    """Determine cycle phase from cycle day."""
    for phase_name, phase_info in CYCLE_PHASES.items():
        start, end = phase_info["days"]
        if start <= cycle_day <= end:
            return phase_name
    return "luteal"  # Default for days > 28


def _get_hrv_status(hrv: float) -> str:
    """Determine HRV status (elevated, normal, low)."""
    if hrv >= 60:
        return "elevated"
    elif hrv >= 40:
        return "normal"
    else:
        return "low"


def _generate_numera_insight(
    user_profile: Any, 
    cycle_data: dict[str, Any], 
    hrv_data: dict[str, Any]
) -> dict[str, Any]:
    """Generate personalized Numera insight based on real user data."""
    
    cycle_day = cycle_data.get("cycle_day")
    phase = cycle_data.get("phase")
    hrv = hrv_data.get("hrv")
    hrv_status = hrv_data.get("hrv_status")
    user_name = user_profile.get("full_name", "").split()[0] if user_profile.get("full_name") else None
    
    # Build prompt with real data
    prompt = _build_numera_insight_prompt(user_profile, cycle_data, hrv_data)
    response_text = _call_numera_insight_llm(prompt)
    parsed = _parse_numera_insight_response(response_text, cycle_data, hrv_data)
    
    if parsed:
        return parsed
    
    # Fallback with real data if LLM fails
    return _fallback_numera_insight(cycle_day, phase, hrv, hrv_status, user_name)


def _build_numera_insight_prompt(
    user_profile: Any, 
    cycle_data: dict[str, Any], 
    hrv_data: dict[str, Any]
) -> str:
    """Build personalized prompt based on real user data."""
    
    cycle_day = cycle_data.get("cycle_day")
    phase = cycle_data.get("phase")
    hrv = hrv_data.get("hrv")
    hrv_status = hrv_data.get("hrv_status")
    user_name = user_profile.get("full_name", "").split()[0] if user_profile.get("full_name") else None
    
    # Build context with real data
    context = {
        "user_name": user_name,
        "cycle_day": cycle_day,
        "phase": phase,
        "hrv": hrv,
        "hrv_status": hrv_status,
        "has_cycle_data": cycle_data.get("has_data", False),
        "has_hrv_data": hrv_data.get("has_data", False),
    }
    
    # Phase-specific guidance for LLM
    phase_guidance = _get_phase_guidance(phase, cycle_day, hrv, hrv_status)
    
    return f"""Generate one personalized Numera Insight card based on the user's REAL data.

User Data:
{json.dumps(context, indent=2)}

Phase Guidance:
{phase_guidance}

Return JSON with exactly this structure:
{{
  "title": "Neumera Insight",
  "tag": "Cycle Day {cycle_day or 'N/A'}",
  "eyebrow": "NEUMERA INSIGHT · CYCLE DAY {cycle_day or 'N/A'}",
  "headline": "<personalized headline based on phase and HRV>",
  "description": "<supportive description with HRV context if available>",
  "cycle_day": {cycle_day or 'null'},
  "theme": "{phase_guidance.get('theme', 'general_wellness') if isinstance(phase_guidance, dict) else 'general_wellness'}",
  "priority": "high"
}}

Requirements:
- Use the user's ACTUAL cycle day: {cycle_day}
- Use the user's ACTUAL HRV: {hrv}ms (status: {hrv_status})
- If user_name exists, include it naturally in headline: "{user_name}"
- Headline should be 1-2 sentences maximum based on their current phase.
- Description should mention HRV if available, or encourage wearable connection if not.
- Keep all fields UI-ready.
- Do NOT use hardcoded values like "Day 14" or "58ms" unless that's the real data.
"""


def _get_phase_guidance(phase: str, cycle_day: int, hrv: float, hrv_status: str) -> str:
    """Get phase-specific guidance for LLM."""
    
    if not phase or not cycle_day:
        # No cycle data
        if hrv:
            return f"""
Theme: hrv_focused
User has HRV data ({hrv}ms - {hrv_status}) but no cycle data.
Headline focus: HRV-based wellness insight
Description: Encourage logging cycle for deeper insights
"""
        else:
            return """
Theme: onboarding
User has no cycle or HRV data.
Headline focus: Welcome message, encourage data entry
Description: Mention benefits of tracking cycle and connecting wearable
"""
    
    # Has cycle data
    phase_info = CYCLE_PHASES.get(phase, CYCLE_PHASES["luteal"])
    theme = phase_info["theme"]
    energy = phase_info["energy"]
    
    hrv_context = ""
    if hrv:
        hrv_context = f"HRV is {hrv_status} at {hrv}ms. "
        if hrv_status == "elevated":
            hrv_context += "Good window for challenging activities."
        elif hrv_status == "low":
            hrv_context += "Consider gentler activities today."
    else:
        hrv_context = "No HRV data available - encourage wearable connection."
    
    if phase == "menstrual":
        return f"""
Theme: {theme}
Cycle Day {cycle_day} - Menstrual phase (Days 1-5)
Energy: {energy}
{hrv_context}
Headline focus: Rest and recovery, gentle self-care
Description: Honor your body's need for rest, light movement if desired
"""
    elif phase == "follicular":
        return f"""
Theme: {theme}
Cycle Day {cycle_day} - Follicular phase (Days 6-11)
Energy: {energy}
{hrv_context}
Headline focus: Rising energy, good time for new initiatives
Description: Great window for starting projects, increasing workout intensity
"""
    elif phase == "ovulation":
        return f"""
Theme: {theme}
Cycle Day {cycle_day} - Ovulation phase (Days 12-16)
Energy: {energy}
{hrv_context}
Headline focus: Peak energy window, ovulation likely
Description: Ideal for high-intensity training, important meetings, social activities
"""
    else:  # luteal
        return f"""
Theme: {theme}
Cycle Day {cycle_day} - Luteal phase (Days 17-28)
Energy: {energy}
{hrv_context}
Headline focus: Winding down, focus on completion not new starts
Description: Good for wrapping up projects, self-care, moderate exercise
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


def _parse_numera_insight_response(
    text: str, 
    cycle_data: dict[str, Any], 
    hrv_data: dict[str, Any]
) -> dict[str, Any] | None:
    payload = _parse_json_object(text)
    if payload is None:
        return None

    try:
        return _coerce_numera_insight_payload(payload, cycle_data, hrv_data)
    except Exception:
        return None


def _coerce_numera_insight_payload(
    payload: Any, 
    cycle_data: dict[str, Any], 
    hrv_data: dict[str, Any]
) -> dict[str, Any]:
    """Ensure numera insight uses REAL data, not LLM hallucinations."""
    if not isinstance(payload, dict):
        return _fallback_numera_insight(
            cycle_data.get("cycle_day"),
            cycle_data.get("phase"),
            hrv_data.get("hrv"),
            hrv_data.get("hrv_status"),
            None
        )

    cycle_day = cycle_data.get("cycle_day")
    phase = cycle_data.get("phase")
    
    # Build tag and eyebrow from REAL cycle day
    if cycle_day:
        tag = f"Cycle Day {cycle_day}"
        eyebrow = f"NEUMERA INSIGHT · CYCLE DAY {cycle_day}"
    else:
        tag = "Wellness Insight"
        eyebrow = "NEUMERA INSIGHT"
    
    # Determine theme from REAL phase
    theme = CYCLE_PHASES.get(phase, {}).get("theme", "general_wellness") if phase else "general_wellness"

    return {
        "title": str(payload.get("title") or "Neumera Insight"),
        "tag": tag,  # Use REAL cycle day
        "eyebrow": eyebrow,  # Use REAL cycle day
        "headline": str(payload.get("headline") or _generate_fallback_headline(cycle_day, phase, hrv_data)),
        "description": str(payload.get("description") or _generate_fallback_description(hrv_data)),
        "cycle_day": cycle_day,  # Use REAL cycle day (can be None)
        "theme": theme,  # Use REAL phase
        "priority": str(payload.get("priority") or "high"),
    }


def _fallback_numera_insight(
    cycle_day: int = None, 
    phase: str = None, 
    hrv: float = None, 
    hrv_status: str = None,
    user_name: str = None
) -> dict[str, Any]:
    """Generate fallback insight using REAL data when LLM fails."""
    
    # Build tag/eyebrow from real cycle day
    if cycle_day:
        tag = f"Cycle Day {cycle_day}"
        eyebrow = f"NEUMERA INSIGHT · CYCLE DAY {cycle_day}"
    else:
        tag = "Wellness Insight"
        eyebrow = "NEUMERA INSIGHT"
    
    # Generate headline based on real phase
    hrv_data = {"hrv": hrv, "hrv_status": hrv_status}
    headline = _generate_fallback_headline(cycle_day, phase, hrv_data, user_name)
    description = _generate_fallback_description(hrv_data)
    
    # Determine theme from real phase
    theme = CYCLE_PHASES.get(phase, {}).get("theme", "general_wellness") if phase else "general_wellness"
    
    return {
        "title": "Neumera Insight",
        "tag": tag,
        "eyebrow": eyebrow,
        "headline": headline,
        "description": description,
        "cycle_day": cycle_day,
        "theme": theme,
        "priority": "high",
    }


def _generate_fallback_headline(
    cycle_day: int = None, 
    phase: str = None, 
    hrv_data: dict = None,
    user_name: str = None
) -> str:
    """Generate personalized headline based on real data."""
    
    name_prefix = f"{user_name}, " if user_name else ""
    
    if not cycle_day:
        # No cycle data
        if hrv_data and hrv_data.get("hrv"):
            return f"{name_prefix}Your HRV is tracking well today."
        return f"{name_prefix}Start logging your cycle for personalized insights."
    
    # Phase-specific headlines
    if phase == "menstrual":
        return f"{name_prefix}Your body is in recovery mode. Honor the rest."
    elif phase == "follicular":
        return f"{name_prefix}Your energy is building. Great time for new initiatives."
    elif phase == "ovulation":
        return f"{name_prefix}You're entering your peak energy window. Ovulation likely within 24–48 hours."
    else:  # luteal
        return f"{name_prefix}Your energy is winding down. Focus on completion, not new starts."


def _generate_fallback_description(hrv_data: dict = None) -> str:
    """Generate description with HRV context."""
    
    if hrv_data and hrv_data.get("hrv"):
        hrv = hrv_data["hrv"]
        status = hrv_data.get("hrv_status", "normal")
        
        if status == "elevated":
            return f"HRV is elevated at {int(hrv)}ms — an ideal window for high-intensity training and deep cognitive work."
        elif status == "low":
            return f"HRV is at {int(hrv)}ms — consider gentler activities and prioritize recovery today."
        else:
            return f"HRV is at {int(hrv)}ms — a balanced day for moderate activity and focus."
    
    return "Connect your wearable device to see HRV-based insights."


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
