import json
import httpx
from ai.utils.llm_call import llm_call
from ai.models.bbt_models import (
    CycleInsightsRequest,
    CycleInsightsResponse,
)
from ai.config import settings


SYSTEM_PROMPT = """You are a BBT (Basal Body Temperature) cycle analysis expert. Analyze the provided temperature data and generate a brief, friendly summary for the user.

Rules:
- Write ONE short paragraph (2-4 sentences max) in a warm, natural tone.
- Mention what the temperature pattern indicates (e.g., ovulation detected, stable follicular phase, luteal phase health, etc.).
- If data is limited or missing, say so gently and suggest collecting more readings.
- Do NOT use bullet points, lists, or JSON. Just plain, conversational text.
- Do NOT include a title or heading.

You must respond ONLY with a valid JSON object matching this exact structure:
{
  "cycle_phase": "string (e.g., Menstrual, Follicular, Ovulatory, Luteal, or Unknown)",
  "message": "Your BBT shows... [short paragraph summary]"
}
"""


def _fetch_user_data(user_id: str) -> dict:
    headers = {}

    if settings.BACKEND_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {settings.BACKEND_ACCESS_TOKEN}"
        headers["x-access-token"] = settings.BACKEND_ACCESS_TOKEN

    url = f"{settings.BACKEND_URL}/user/onboarding-log-temperature-for-ai/{user_id}"

    response = httpx.get(url, headers=headers, timeout=30.0)
    response.raise_for_status()
    return response.json()


def analyze_cycle(request: CycleInsightsRequest) -> CycleInsightsResponse:
    payload = _fetch_user_data(request.user_id)

    inner_data = payload.get("data", {}).get("data", {})
    last30 = inner_data.get("last30DaysReport", [])

    prompt = f"""Analyze this BBT cycle data:

Backend Data:
- Current Phase: {inner_data.get('currentPhase', 'Unknown')}
- Average Temperature: {inner_data.get('averageTemperature', 'N/A')}
- Highest Temperature: {inner_data.get('heightTemperature', 'N/A')}
- Lowest Temperature: {inner_data.get('lowestTemperature', 'N/A')}
- Last 30 Days Readings Count: {len(last30)}

Temperature Readings (last 30 days):
{json.dumps(last30, indent=2) if last30 else "No data available"}

Generate the JSON response as instructed."""

    response_text = llm_call(
        prompt=prompt,
        system=SYSTEM_PROMPT,
        max_tokens=2048,
    )

    raw = _safe_json_parse(response_text)

    return CycleInsightsResponse(
        cycle_phase=raw.get("cycle_phase", inner_data.get("currentPhase", "Unknown")),
        message=raw.get("message", "Unable to generate insights from current data."),
    )


def _safe_json_parse(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        filtered = [ln for ln in lines if not ln.startswith("```")]
        text = "\n".join(filtered).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}
