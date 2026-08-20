import json
import time
from typing import Any

import httpx

from ai.config import settings, snapshot_url_for, user_id_from_profile
from ai.utils.db import get_snapshot, get_user_profile
from ai.utils.llm_call import llm_call


RETRYABLE_LLM_STATUS_CODES = {429, 500, 502, 503, 529}
LLM_RETRY_DELAYS_SECONDS = (1.0, 2.0)
MAX_CONTEXT_CHARS = 12000


CYCLE_AWARENESS_SYSTEM_PROMPT = """You are a careful cycle-awareness analysis assistant.

Rules:
- Use only the user profile and health snapshot JSON provided.
- Do not diagnose, prescribe, or claim medical certainty.
- Generate a UI-ready Cycle Awareness section for the cycle engine.
- The screen should focus on luteal phase awareness, hormone levels, what to know, and the 4-phase cycle.
- If detailed cycle or hormone data is missing, create cautious estimates and clearly avoid clinical certainty.
- Return valid JSON only. Do not add markdown, code fences, or extra commentary.
"""


def fetch_cycle_awareness_data(user_id: int) -> dict[str, Any]:
    user_profile = _serialize(get_user_profile(user_id))
    snapshot = _serialize(get_snapshot(user_id))
    
    # Check if user has any cycle data
    has_data = _has_cycle_data(snapshot)
    if not has_data:
        return {
            "status": "empty",
            "service": "cycle_awareness",
            "fetched": True,
            "sources": {"database": "mysql"},
            "user_id": user_id,
            "message": "No cycle data yet",
            "description": "Start logging your period data to see personalized cycle awareness insights.",
            "user_profile": user_profile,
        }
    
    cycle_awareness = _generate_cycle_awareness_analysis(user_profile, snapshot)

    return {
        "status": "ready",
        "service": "cycle_awareness",
        "fetched": True,
        "sources": {"database": "mysql"},
        "cycle_awareness": cycle_awareness,
        "user_profile": user_profile,
        "snapshot": snapshot,
    }


def _has_cycle_data(snapshot: Any) -> bool:
    """Check if snapshot contains any real cycle data."""
    if not snapshot:
        return False
    has_cycles = snapshot.get("current_cycle") or snapshot.get("period_logs")
    has_bbt = snapshot.get("bbt_logs") and len(snapshot.get("bbt_logs", [])) > 0
    has_opk = snapshot.get("opk_logs") and len(snapshot.get("opk_logs", [])) > 0
    return bool(has_cycles or has_bbt or has_opk)


def _serialize(data: Any) -> Any:
    """Convert DB rows (dates, decimals) to JSON-safe values."""
    return json.loads(json.dumps(data, default=str)) if data is not None else None


def _generate_cycle_awareness_analysis(user_profile: Any, snapshot: Any) -> dict[str, Any]:
    prompt = _build_cycle_awareness_prompt(user_profile, snapshot)
    response_text = _call_cycle_awareness_llm(prompt)
    parsed = _parse_cycle_awareness_response(response_text)
    if parsed:
        return parsed
    return _fallback_cycle_awareness_analysis()


def _build_cycle_awareness_prompt(user_profile: Any, snapshot: Any) -> str:
    context = json.dumps(
        {
            "user_profile": user_profile,
            "snapshot": snapshot,
        },
        ensure_ascii=False,
        default=str,
    )[:MAX_CONTEXT_CHARS]

    return f"""Generate only the Cycle Awareness section for a cycle engine UI.

Backend context JSON:
{context}

STEP 1 - DETERMINE THE CURRENT PHASE (CRITICAL):
- First, read the actual cycle_day and phase from the backend context above.
- The user's CURRENT phase is one of: Menstrual, Follicular, Ovulatory, or Luteal.
- Typical day ranges (adjust to the user's average cycle length):
  * Menstrual: Days 1-5 (low energy, estrogen & progesterone low)
  * Follicular: Days 6-13 (rising energy, estrogen rising)
  * Ovulatory: Days 14-15 (peak energy, LH & estrogen peak)
  * Luteal: Days 16-28 (declining energy, progesterone high then dropping)

STEP 2 - GENERATE ALL SECTIONS FOR THE USER'S ACTUAL CURRENT PHASE:
- EVERY section (current_phase, phase_detail, hormone_levels, what_to_know) MUST describe
  the SAME phase you determined in Step 1. Do NOT mix phases.
- If the user is in the Follicular phase, ALL titles and content must say "Follicular phase"
  (NOT "Luteal phase"). The example below uses Luteal ONLY as a format sample — replace it
  with the user's real phase.

Return JSON with exactly this structure (replace all phase names/values with the user's ACTUAL current phase):
{{
  "title": "Cycle Awareness",
  "cycle_context": {{
    "cycle_day": <actual cycle day from context>,
    "phase": "<actual current phase> phase",
    "average_cycle_length": "<actual avg length>d"
  }},
  "current_phase": {{
    "label": "Currently in",
    "phase": "<actual current phase> Phase",
    "day_range": "Days <start>-<end> for this phase",
    "summary": "<short hormone summary for this phase>"
  }},
  "luteal_phase": {{
    "title": "<actual current phase> Phase",
    "subtitle": "Days <start>-<end> - <short hormone summary>",
    "cards": [
      {{"name": "Energy", "status": "<status for this phase>", "description": "<energy note for this phase>", "icon_key": "zap"}},
      {{"name": "Skin", "status": "<status for this phase>", "description": "<skin note for this phase>", "icon_key": "sparkles"}},
      {{"name": "Mood", "status": "<status for this phase>", "description": "<mood note for this phase>", "icon_key": "brain"}}
    ]
  }},
  "hormone_levels": {{
    "title": "Hormone levels - <actual current phase> phase",
    "hormones": [
      {{"name": "Estrogen", "description": "Mood, energy, skin", "level": "<level for this phase>", "value_percent": <0-100 for this phase>}},
      {{"name": "Progesterone", "description": "Temperature, calm", "level": "<level for this phase>", "value_percent": <0-100 for this phase>}},
      {{"name": "LH", "description": "Ovulation trigger", "level": "<level for this phase>", "value_percent": <0-100 for this phase>}}
    ]
  }},
  "what_to_know": {{
    "title": "What to know - <actual current phase> phase",
    "items": [
      {{"label": "BBT", "text": "<BBT note relevant to this phase>"}},
      {{"label": "Energy", "text": "<energy note relevant to this phase>"}},
      {{"label": "Hormones", "text": "<hormone note relevant to this phase>"}},
      {{"label": "Focus", "text": "<focus/productivity note relevant to this phase>"}}
    ]
  }},
  "four_phase_cycle": {{
    "title": "Your 4-phase cycle",
    "subtitle": "Tap any phase to understand it.",
    "phases": [
      {{"name": "Menstrual", "day_range": "D1-5", "energy": "Low", "state": "<past|current|upcoming>"}},
      {{"name": "Follicular", "day_range": "D6-13", "energy": "Rising", "state": "<past|current|upcoming>"}},
      {{"name": "Ovulatory", "day_range": "D14-15", "energy": "Peak", "state": "<past|current|upcoming>"}},
      {{"name": "Luteal", "day_range": "D16-28", "energy": "Falling", "state": "<past|current|upcoming>"}}
    ]
  }}
}}

Requirements:
- ALL sections (current_phase, luteal_phase card block, hormone_levels, what_to_know) MUST match
  the user's ACTUAL current phase — never default to Luteal unless the user is truly in Luteal.
- Hormone value_percent must reflect the current phase (e.g., Follicular: estrogen rising, progesterone low, LH low).
- In four_phase_cycle, set exactly ONE phase to "state":"current" (the user's actual phase),
  earlier phases to "past", and later phases to "upcoming".
- Keep the JSON key name "luteal_phase" as-is (it is the UI card container), but its title/subtitle/cards
  MUST describe the user's ACTUAL current phase.
- Use cycle day, phase, BBT, OPK/LH, mucus, symptoms, and health snapshot data from backend context when present.
- If exact values are missing, use cautious phase-appropriate estimates and avoid clinical certainty.
- Keep all text concise and mobile UI-ready.
"""


def _call_cycle_awareness_llm(prompt: str) -> str:
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1

    for attempt in range(attempts):
        try:
            return llm_call(
                prompt=prompt,
                system=CYCLE_AWARENESS_SYSTEM_PROMPT,
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


def _parse_cycle_awareness_response(text: str) -> dict[str, Any] | None:
    payload = _parse_json_object(text)
    if payload is None:
        return None

    try:
        return _coerce_cycle_awareness_payload(payload)
    except Exception:
        return None


def _coerce_cycle_awareness_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _fallback_cycle_awareness_analysis()

    fallback = _fallback_cycle_awareness_analysis()
    return {
        "title": str(payload.get("title") or fallback["title"]),
        "cycle_context": _coerce_cycle_context(payload.get("cycle_context"), fallback["cycle_context"]),
        "current_phase": _coerce_current_phase(payload.get("current_phase"), fallback["current_phase"]),
        "luteal_phase": _coerce_luteal_phase(payload.get("luteal_phase"), fallback["luteal_phase"]),
        "hormone_levels": _coerce_hormone_levels(payload.get("hormone_levels"), fallback["hormone_levels"]),
        "what_to_know": _coerce_what_to_know(payload.get("what_to_know"), fallback["what_to_know"]),
        "four_phase_cycle": _coerce_four_phase_cycle(payload.get("four_phase_cycle"), fallback["four_phase_cycle"]),
    }


def _coerce_cycle_context(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    return {
        "cycle_day": _bounded_int(value.get("cycle_day"), fallback["cycle_day"], 1, 90),
        "phase": str(value.get("phase") or fallback["phase"]),
        "average_cycle_length": str(value.get("average_cycle_length") or fallback["average_cycle_length"]),
    }


def _coerce_current_phase(value: Any, fallback: dict[str, str]) -> dict[str, str]:
    if not isinstance(value, dict):
        value = {}
    return {
        "label": str(value.get("label") or fallback["label"]),
        "phase": str(value.get("phase") or fallback["phase"]),
        "day_range": str(value.get("day_range") or fallback["day_range"]),
        "summary": str(value.get("summary") or fallback["summary"]),
    }


def _coerce_luteal_phase(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    cards = value.get("cards") if isinstance(value.get("cards"), list) else fallback["cards"]
    return {
        "title": str(value.get("title") or fallback["title"]),
        "subtitle": str(value.get("subtitle") or fallback["subtitle"]),
        "cards": _coerce_named_cards(cards, fallback["cards"], ["Energy", "Skin", "Mood"]),
    }


def _coerce_named_cards(items: list[Any], fallback: list[dict[str, str]], expected: list[str]) -> list[dict[str, str]]:
    ordered = []
    for index, name in enumerate(expected):
        match = _find_named_item(items, name)
        source = match or fallback[index]
        ordered.append(
            {
                "name": name,
                "status": str(source.get("status") or fallback[index]["status"]),
                "description": str(source.get("description") or fallback[index]["description"]),
                "icon_key": str(source.get("icon_key") or fallback[index]["icon_key"]),
            }
        )
    return ordered


def _coerce_hormone_levels(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    hormones = value.get("hormones") if isinstance(value.get("hormones"), list) else fallback["hormones"]
    return {
        "title": str(value.get("title") or fallback["title"]),
        "hormones": _coerce_hormones(hormones, fallback["hormones"]),
    }


def _coerce_hormones(items: list[Any], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expected = ["Estrogen", "Progesterone", "LH"]
    ordered = []
    for index, name in enumerate(expected):
        match = _find_named_item(items, name)
        source = match or fallback[index]
        ordered.append(
            {
                "name": name,
                "description": str(source.get("description") or fallback[index]["description"]),
                "level": str(source.get("level") or fallback[index]["level"]),
                "value_percent": _bounded_int(source.get("value_percent"), fallback[index]["value_percent"], 0, 100),
            }
        )
    return ordered


def _coerce_what_to_know(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    items = value.get("items") if isinstance(value.get("items"), list) else fallback["items"]
    return {
        "title": str(value.get("title") or fallback["title"]),
        "items": _coerce_label_text_items(items, fallback["items"], ["BBT", "Energy", "Hormones", "Focus"]),
    }


def _coerce_label_text_items(items: list[Any], fallback: list[dict[str, str]], expected: list[str]) -> list[dict[str, str]]:
    ordered = []
    for index, label in enumerate(expected):
        match = _find_label_item(items, label)
        source = match or fallback[index]
        ordered.append(
            {
                "label": label,
                "text": str(source.get("text") or fallback[index]["text"]),
            }
        )
    return ordered


def _coerce_four_phase_cycle(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    phases = value.get("phases") if isinstance(value.get("phases"), list) else fallback["phases"]
    return {
        "title": str(value.get("title") or fallback["title"]),
        "subtitle": str(value.get("subtitle") or fallback["subtitle"]),
        "phases": _coerce_phase_items(phases, fallback["phases"]),
    }


def _coerce_phase_items(items: list[Any], fallback: list[dict[str, str]]) -> list[dict[str, str]]:
    expected = ["Menstrual", "Follicular", "Ovulatory", "Luteal"]
    ordered = []
    for index, name in enumerate(expected):
        match = _find_named_item(items, name)
        source = match or fallback[index]
        ordered.append(
            {
                "name": name,
                "day_range": str(source.get("day_range") or fallback[index]["day_range"]),
                "energy": str(source.get("energy") or fallback[index]["energy"]),
                "state": str(source.get("state") or fallback[index]["state"]),
            }
        )
    return ordered


def _find_named_item(items: list[Any], expected_name: str) -> dict[str, Any] | None:
    expected_key = _normalize_key(expected_name)
    for item in items:
        if not isinstance(item, dict):
            continue
        if _normalize_key(str(item.get("name", ""))) == expected_key:
            return item
    return None


def _find_label_item(items: list[Any], expected_label: str) -> dict[str, Any] | None:
    expected_key = _normalize_key(expected_label)
    for item in items:
        if not isinstance(item, dict):
            continue
        if _normalize_key(str(item.get("label", ""))) == expected_key:
            return item
    return None


def _normalize_key(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


def _fallback_cycle_awareness_analysis() -> dict[str, Any]:
    return {
        "title": "Cycle Awareness",
        "cycle_context": {
            "cycle_day": 17,
            "phase": "Luteal phase",
            "average_cycle_length": "27.8d",
        },
        "current_phase": {
            "label": "Currently in",
            "phase": "Luteal Phase",
            "day_range": "Days 16-28",
            "summary": "Progesterone rising",
        },
        "luteal_phase": {
            "title": "Luteal Phase",
            "subtitle": "Days 16-28 - Progesterone rising",
            "cards": [
                {
                    "name": "Energy",
                    "status": "Declining",
                    "description": "Energy gradually lowers as the cycle moves toward the next phase.",
                    "icon_key": "zap",
                },
                {
                    "name": "Skin",
                    "status": "May breakout",
                    "description": "Skin may feel more reactive during the luteal phase.",
                    "icon_key": "sparkles",
                },
                {
                    "name": "Mood",
                    "status": "Inward",
                    "description": "Mood may turn more reflective or inward.",
                    "icon_key": "brain",
                },
            ],
        },
        "hormone_levels": {
            "title": "Hormone levels - Luteal phase",
            "hormones": [
                {"name": "Estrogen", "description": "Mood, energy, skin", "level": "Mild", "value_percent": 45},
                {"name": "Progesterone", "description": "Temperature, calm", "level": "High", "value_percent": 92},
                {"name": "LH", "description": "Ovulation trigger", "level": "Low", "value_percent": 18},
            ],
        },
        "what_to_know": {
            "title": "What to know - Luteal phase",
            "items": [
                {"label": "BBT", "text": "Body temp rises 0.4F after ovulation; BBT reflects this."},
                {"label": "Energy", "text": "Energy and mood gradually decline toward end of this phase."},
                {"label": "Hormones", "text": "PMS symptoms appear in second half as progesterone peaks then drops."},
                {"label": "Focus", "text": "Detail-oriented, analytical, and solo work suit this phase."},
            ],
        },
        "four_phase_cycle": {
            "title": "Your 4-phase cycle",
            "subtitle": "Tap any phase to understand it.",
            "phases": [
                {"name": "Menstrual", "day_range": "D1-5", "energy": "Low", "state": "past"},
                {"name": "Follicular", "day_range": "D6-13", "energy": "Rising", "state": "past"},
                {"name": "Ovulatory", "day_range": "D14-15", "energy": "Peak", "state": "past"},
                {"name": "Luteal", "day_range": "D16-28", "energy": "Falling", "state": "current"},
            ],
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
