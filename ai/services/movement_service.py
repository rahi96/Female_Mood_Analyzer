import json
import time
from typing import Any

from ai.utils.llm_call import llm_call
from ai.models.bbt_models import (
    MovementRecommendationRequest,
    MovementRecommendationResponse,
)
from ai.services.cycle_service import fetch_backend_data, fetch_cycle_temperature_report


RETRYABLE_LLM_STATUS_CODES = {429, 500, 502, 503, 529}
LLM_RETRY_DELAYS_SECONDS = (1.0, 2.0)


MOVEMENT_SYSTEM_PROMPT = """You are a cycle-synced fitness and movement expert.

You analyze a woman's BBT (Basal Body Temperature) data and health profile to generate
personalized, phase-specific workout recommendations.

Rules:
- Analyze the user's temperature data and health profile provided.
- Generate output as valid JSON with exactly these keys:
  "description": a 1-2 sentence insight about this specific cycle phase and what the body is doing,
  "recommended_workouts": a list of 3-4 short workout recommendations (each 5-10 words),
  "mfy_examples": a list of 2-3 short example workout names or routines (each 3-8 words)
- Tailor recommendations to the user's data when possible (e.g. temperature patterns, onboarding info).
- Keep language warm, supportive, and non-medical.
- Do not add markdown, code fences, or extra keys.
"""


PHASE_CONTEXTS = {
    "follicular": {
        "phase_name": "Follicular Phase",
        "day_range": "Day 1-13",
        "guidance": (
            "The follicular phase is the power phase. Estrogen is rising, energy is climbing, "
            "and the body is primed for strength-building and pushing limits. "
            "Recommend high-intensity workouts, strength training, and challenging group classes."
        ),
        "fallback_description": (
            "Your energy is climbing, mood is high — this is your power phase for "
            "building strength and pushing limits."
        ),
        "fallback_workouts": [
            "Strength training with progressive overloads",
            "Running or high-cardio fitness classes",
            "Try new challenging group fitness classes (boxing!)",
        ],
        "fallback_mfy_examples": [
            "Global Bootcamp",
            "Hot in HIIT",
            "Full power day easy",
        ],
    },
    "ovulation": {
        "phase_name": "Ovulation Phase",
        "day_range": "Day 14-16",
        "guidance": (
            "The ovulation phase is peak performance. Testosterone and estrogen peak together, "
            "making this the strongest point physically and mentally. "
            "Recommend max-effort lifts, PRs, competitive workouts, and intense cardio."
        ),
        "fallback_description": (
            "Testosterone and estrogen peak together — you're at your strongest "
            "physically and mentally."
        ),
        "fallback_workouts": [
            "Max effort lifts, go for PRs!",
            "Conditioning and challenging interval runs",
            "Team sports or competitive workouts",
        ],
        "fallback_mfy_examples": [
            "All out HIIT",
            "Run It Back intervals",
            "Detailed full body",
        ],
    },
    "luteal": {
        "phase_name": "Luteal Phase",
        "day_range": "Day 17-28",
        "guidance": (
            "The luteal phase means progesterone rises and energy dips. The body signals "
            "to honor rest and adjust intensity downward. "
            "Recommend gentle yoga, pilates, walking, low-impact circuits, and slower runs."
        ),
        "fallback_description": (
            "Progesterone rises, energy dips — this is your body's signal to honor "
            "rest and adjust intensity."
        ),
        "fallback_workouts": [
            "Gentle yoga or pilates",
            "Walking or low-impact circuits",
            "Slow runs (push, not crush)",
        ],
        "fallback_mfy_examples": [
            "Easy yoga flow",
            "Gentle pilates session",
            "Down tempo mid lift",
        ],
    },
    "menstrual": {
        "phase_name": "Menstrual Phase",
        "day_range": "Day 1-5",
        "guidance": (
            "The menstrual phase is when the body is resetting. Gentle movement or complete "
            "rest is what it needs. "
            "Recommend restorative yoga, stretching, light walks, and full rest days."
        ),
        "fallback_description": (
            "Between your low body is resting — gentle movement or complete "
            "rest when it needs it."
        ),
        "fallback_workouts": [
            "Restorative yoga or stretching",
            "Light walks, nothing intense",
            "Full rest days if needed",
        ],
        "fallback_mfy_examples": [
            "Walk it out day",
            "10 min stretch and learn",
            "Stretch and chill",
        ],
    },
}


def generate_movement_recommendation(
    request: MovementRecommendationRequest,
    phase_key: str,
) -> MovementRecommendationResponse:
    phase = PHASE_CONTEXTS[phase_key]

    user_data = fetch_backend_data(request.user_id)
    temp_report = _safe_fetch_temp_report(request.user_id)

    prompt = _build_prompt(phase, user_data, temp_report)
    raw_response = _call_movement_llm(prompt)
    parsed = _parse_movement_response(raw_response)

    if parsed:
        return MovementRecommendationResponse(
            phase_name=phase["phase_name"],
            day_range=phase["day_range"],
            description=parsed.get("description", phase["fallback_description"]),
            recommended_workouts=parsed.get("recommended_workouts", phase["fallback_workouts"]),
            mfy_examples=parsed.get("mfy_examples", phase["fallback_mfy_examples"]),
        )

    return MovementRecommendationResponse(
        phase_name=phase["phase_name"],
        day_range=phase["day_range"],
        description=phase["fallback_description"],
        recommended_workouts=phase["fallback_workouts"],
        mfy_examples=phase["fallback_mfy_examples"],
    )


def _build_prompt(phase: dict, user_data: dict, temp_report: dict | None) -> str:
    parts = [
        f"Phase: {phase['phase_name']} ({phase['day_range']})",
        f"\nPhase context:\n{phase['guidance']}",
        f"\nUser health data:\n{_to_pretty_json(user_data)}",
    ]

    if temp_report:
        parts.append(f"\nTemperature report:\n{_to_pretty_json(temp_report)}")

    parts.append(
        "\nGenerate a personalized JSON response with keys: "
        '"description", "recommended_workouts", "mfy_examples".'
    )

    return "\n".join(parts)


def _safe_fetch_temp_report(user_id: str) -> dict | None:
    try:
        return fetch_cycle_temperature_report(user_id)
    except Exception:
        return None


def _call_movement_llm(prompt: str) -> str:
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1

    for attempt in range(attempts):
        try:
            return llm_call(
                prompt=prompt,
                system=MOVEMENT_SYSTEM_PROMPT,
                max_tokens=400,
            )
        except Exception as exc:
            is_last_attempt = attempt == attempts - 1
            if not _is_retryable_llm_error(exc):
                raise
            if is_last_attempt:
                return ""
            time.sleep(LLM_RETRY_DELAYS_SECONDS[attempt])

    return ""


def _parse_movement_response(text: str) -> dict | None:
    if not text:
        return None

    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()
        filtered = [ln for ln in lines if not ln.startswith("```")]
        text = "\n".join(filtered).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return _extract_from_text(text)

    if not isinstance(parsed, dict):
        return None

    return _validate_parsed(parsed)


def _validate_parsed(parsed: dict) -> dict | None:
    description = parsed.get("description")
    workouts = parsed.get("recommended_workouts")
    examples = parsed.get("mfy_examples")

    if not isinstance(description, str) or not description.strip():
        return None
    if not isinstance(workouts, list) or not workouts:
        return None
    if not isinstance(examples, list) or not examples:
        return None

    return {
        "description": " ".join(description.split()),
        "recommended_workouts": [" ".join(str(w).split()) for w in workouts if w],
        "mfy_examples": [" ".join(str(e).split()) for e in examples if e],
    }


def _extract_from_text(text: str) -> dict | None:
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        return None

    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None

    if isinstance(parsed, dict):
        return _validate_parsed(parsed)

    return None


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


def _to_pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True, default=str)
