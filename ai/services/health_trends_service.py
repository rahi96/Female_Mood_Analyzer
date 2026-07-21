import json
import time
from typing import Any

import httpx

from ai.config import settings
from ai.utils.llm_call import llm_call


RETRYABLE_LLM_STATUS_CODES = {429, 500, 502, 503, 529}
LLM_RETRY_DELAYS_SECONDS = (1.0, 2.0)
MAX_CONTEXT_CHARS = 12000


HEALTH_TRENDS_SYSTEM_PROMPT = """You are a careful health trends analysis assistant.

Rules:
- Use only the user profile and user health logs JSON provided.
- Do not diagnose, prescribe, or claim medical certainty.
- Generate a UI-ready Health Trends section.
- Focus on sleep vs energy correlation chart, sleep vs energy correlation diagram, and hormones x mood.
- If exact sleep, energy, hormone, or mood data is missing, create cautious estimates from available context and avoid clinical certainty.
- Return valid JSON only. Do not add markdown, code fences, or extra commentary.
"""


def fetch_health_trends_data() -> dict[str, Any]:
    user_profile = _get_backend_json(settings.CYCLE_ENGINE_PROFILE_URL)
    health_logs = _get_backend_json(settings.HEALTH_TRENDS_HEALTH_LOGS_URL)
    health_trends = _generate_health_trends_analysis(user_profile, health_logs)

    return {
        "status": "ready",
        "service": "health_trends",
        "fetched": True,
        "sources": {
            "user_profile": settings.CYCLE_ENGINE_PROFILE_URL,
            "health_logs": settings.HEALTH_TRENDS_HEALTH_LOGS_URL,
        },
        "health_trends": health_trends,
        "user_profile": user_profile,
        "health_logs": health_logs,
    }


def _generate_health_trends_analysis(user_profile: Any, health_logs: Any) -> dict[str, Any]:
    prompt = _build_health_trends_prompt(user_profile, health_logs)
    response_text = _call_health_trends_llm(prompt)
    parsed = _parse_health_trends_response(response_text)
    if parsed:
        return parsed
    return _fallback_health_trends_analysis()


def _build_health_trends_prompt(user_profile: Any, health_logs: Any) -> str:
    context = json.dumps(
        {
            "user_profile": user_profile,
            "health_logs": health_logs,
        },
        ensure_ascii=False,
        default=str,
    )[:MAX_CONTEXT_CHARS]

    return f"""Generate only the Health Trends section for a mobile UI.

Backend context JSON:
{context}

Return JSON with exactly this structure:
{{
  "title": "Health Trends",
  "range_options": [
    {{"label": "7d", "selected": true}},
    {{"label": "30d", "selected": false}}
  ],
  "sleep_energy_correlation_chart": {{
    "title": "Sleep vs. Energy Correlation",
    "period": "7d",
    "unit": "score",
    "points": [
      {{"day": "Mon", "sleep_hours": 7.0, "energy_score": 72}},
      {{"day": "Tue", "sleep_hours": 7.2, "energy_score": 74}},
      {{"day": "Wed", "sleep_hours": 6.6, "energy_score": 68}},
      {{"day": "Thu", "sleep_hours": 7.8, "energy_score": 80}},
      {{"day": "Fri", "sleep_hours": 7.1, "energy_score": 74}},
      {{"day": "Sat", "sleep_hours": 8.0, "energy_score": 85}},
      {{"day": "Sun", "sleep_hours": 7.5, "energy_score": 78}}
    ],
    "highlight": {{"day": "Tue", "label": "Tue", "sleep_label": "Sleep: 7.2"}},
    "insight": {{
      "message": "Sleep quality is strongly correlated with your energy score.",
      "correlation_label": "strong",
      "r_value": 0.82,
      "recommendation": "Prioritize 7.5h+ for optimal performance."
    }}
  }},
  "sleep_energy_correlation_diagram": {{
    "title": "Sleep vs. Energy Correlation",
    "bars": [
      {{"day": "Mon", "value": 74}},
      {{"day": "Tue", "value": 72}},
      {{"day": "Wed", "value": 65}},
      {{"day": "Thu", "value": 82}},
      {{"day": "Fri", "value": 78}},
      {{"day": "Sat", "value": 85}},
      {{"day": "Sun", "value": 80}}
    ],
    "metrics": [
      {{"label": "7-Day Avg", "value": "74", "trend": "neutral"}},
      {{"label": "Peak", "value": "85", "trend": "high"}},
      {{"label": "Trend", "value": "+6pts", "trend": "up"}}
    ]
  }},
  "hormone_mood": {{
    "title": "Hormones x Mood",
    "summary": "Follicular energy peaks consistently match your highest productivity scores.",
    "neumera_insight": "Plan cognitively demanding work for days 7-13 of your next cycle for a natural performance edge.",
    "signals": [
      {{"label": "Hormone phase", "value": "Follicular", "context": "energy rising"}},
      {{"label": "Mood trend", "value": "More focused", "context": "higher productivity"}}
    ]
  }}
}}

Requirements:
- Generate sleep_energy_correlation_chart for the top chart in the screen.
- Generate sleep_energy_correlation_diagram for the bar diagram and metrics in the screen.
- Generate hormone_mood using backend cycle, hormone, energy, mood, sleep, and wellness data when present.
- Use 7 days of data for chart points and bars.
- Keep labels exactly UI-ready and concise.
- If data is missing, use cautious estimates similar to the example and avoid claiming exact medical certainty.
"""


def _call_health_trends_llm(prompt: str) -> str:
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1

    for attempt in range(attempts):
        try:
            return llm_call(
                prompt=prompt,
                system=HEALTH_TRENDS_SYSTEM_PROMPT,
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


def _parse_health_trends_response(text: str) -> dict[str, Any] | None:
    payload = _parse_json_object(text)
    if payload is None:
        return None

    try:
        return _coerce_health_trends_payload(payload)
    except Exception:
        return None


def _coerce_health_trends_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _fallback_health_trends_analysis()

    fallback = _fallback_health_trends_analysis()
    return {
        "title": str(payload.get("title") or fallback["title"]),
        "range_options": _coerce_range_options(payload.get("range_options"), fallback["range_options"]),
        "sleep_energy_correlation_chart": _coerce_chart(
            payload.get("sleep_energy_correlation_chart"),
            fallback["sleep_energy_correlation_chart"],
        ),
        "sleep_energy_correlation_diagram": _coerce_diagram(
            payload.get("sleep_energy_correlation_diagram"),
            fallback["sleep_energy_correlation_diagram"],
        ),
        "hormone_mood": _coerce_hormone_mood(payload.get("hormone_mood"), fallback["hormone_mood"]),
    }


def _coerce_range_options(value: Any, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return fallback
    expected = ["7d", "30d"]
    options = []
    for index, label in enumerate(expected):
        match = _find_label_item(value, label)
        source = match or fallback[index]
        options.append({"label": label, "selected": bool(source.get("selected", index == 0))})
    return options


def _coerce_chart(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    points = value.get("points") if isinstance(value.get("points"), list) else fallback["points"]
    highlight = value.get("highlight") if isinstance(value.get("highlight"), dict) else {}
    insight = value.get("insight") if isinstance(value.get("insight"), dict) else {}
    return {
        "title": str(value.get("title") or fallback["title"]),
        "period": str(value.get("period") or fallback["period"]),
        "unit": str(value.get("unit") or fallback["unit"]),
        "points": _coerce_chart_points(points, fallback["points"]),
        "highlight": {
            "day": str(highlight.get("day") or fallback["highlight"]["day"]),
            "label": str(highlight.get("label") or fallback["highlight"]["label"]),
            "sleep_label": str(highlight.get("sleep_label") or fallback["highlight"]["sleep_label"]),
        },
        "insight": {
            "message": str(insight.get("message") or fallback["insight"]["message"]),
            "correlation_label": str(insight.get("correlation_label") or fallback["insight"]["correlation_label"]),
            "r_value": _bounded_float(insight.get("r_value"), fallback["insight"]["r_value"], -1.0, 1.0),
            "recommendation": str(insight.get("recommendation") or fallback["insight"]["recommendation"]),
        },
    }


def _coerce_chart_points(points: list[Any], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    coerced = []
    for index, item in enumerate(points):
        if not isinstance(item, dict):
            continue
        source_fallback = fallback[min(index, len(fallback) - 1)]
        coerced.append(
            {
                "day": str(item.get("day") or source_fallback["day"]),
                "sleep_hours": _bounded_float(item.get("sleep_hours"), source_fallback["sleep_hours"], 0.0, 24.0),
                "energy_score": _bounded_int(item.get("energy_score"), source_fallback["energy_score"], 0, 100),
            }
        )
    return _ensure_seven_items(coerced, fallback)


def _coerce_diagram(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    bars = value.get("bars") if isinstance(value.get("bars"), list) else fallback["bars"]
    metrics = value.get("metrics") if isinstance(value.get("metrics"), list) else fallback["metrics"]
    return {
        "title": str(value.get("title") or fallback["title"]),
        "bars": _coerce_bars(bars, fallback["bars"]),
        "metrics": _coerce_metrics(metrics, fallback["metrics"]),
    }


def _coerce_bars(bars: list[Any], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    coerced = []
    for index, item in enumerate(bars):
        if not isinstance(item, dict):
            continue
        source_fallback = fallback[min(index, len(fallback) - 1)]
        coerced.append(
            {
                "day": str(item.get("day") or source_fallback["day"]),
                "value": _bounded_int(item.get("value"), source_fallback["value"], 0, 100),
            }
        )
    return _ensure_seven_items(coerced, fallback)


def _coerce_metrics(metrics: list[Any], fallback: list[dict[str, str]]) -> list[dict[str, str]]:
    expected = ["7-Day Avg", "Peak", "Trend"]
    ordered = []
    for index, label in enumerate(expected):
        match = _find_label_item(metrics, label)
        source = match or fallback[index]
        ordered.append(
            {
                "label": label,
                "value": str(source.get("value") or fallback[index]["value"]),
                "trend": str(source.get("trend") or fallback[index]["trend"]),
            }
        )
    return ordered


def _coerce_hormone_mood(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    signals = value.get("signals") if isinstance(value.get("signals"), list) else fallback["signals"]
    return {
        "title": str(value.get("title") or fallback["title"]),
        "summary": str(value.get("summary") or fallback["summary"]),
        "neumera_insight": str(value.get("neumera_insight") or fallback["neumera_insight"]),
        "signals": _coerce_signals(signals, fallback["signals"]),
    }


def _coerce_signals(signals: list[Any], fallback: list[dict[str, str]]) -> list[dict[str, str]]:
    coerced = []
    for index, item in enumerate(signals):
        if not isinstance(item, dict):
            continue
        source_fallback = fallback[min(index, len(fallback) - 1)]
        coerced.append(
            {
                "label": str(item.get("label") or source_fallback["label"]),
                "value": str(item.get("value") or source_fallback["value"]),
                "context": str(item.get("context") or source_fallback["context"]),
            }
        )
    return coerced or fallback


def _find_label_item(items: list[Any], expected_label: str) -> dict[str, Any] | None:
    expected_key = _normalize_key(expected_label)
    for item in items:
        if not isinstance(item, dict):
            continue
        if _normalize_key(str(item.get("label", ""))) == expected_key:
            return item
    return None


def _ensure_seven_items(items: list[dict[str, Any]], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(items) >= 7:
        return items[:7]
    merged = items[:]
    for fallback_item in fallback[len(merged) :]:
        merged.append(fallback_item)
    return merged


def _fallback_health_trends_analysis() -> dict[str, Any]:
    return {
        "title": "Health Trends",
        "range_options": [
            {"label": "7d", "selected": True},
            {"label": "30d", "selected": False},
        ],
        "sleep_energy_correlation_chart": {
            "title": "Sleep vs. Energy Correlation",
            "period": "7d",
            "unit": "score",
            "points": [
                {"day": "Mon", "sleep_hours": 7.0, "energy_score": 72},
                {"day": "Tue", "sleep_hours": 7.2, "energy_score": 74},
                {"day": "Wed", "sleep_hours": 6.6, "energy_score": 68},
                {"day": "Thu", "sleep_hours": 7.8, "energy_score": 80},
                {"day": "Fri", "sleep_hours": 7.1, "energy_score": 74},
                {"day": "Sat", "sleep_hours": 8.0, "energy_score": 85},
                {"day": "Sun", "sleep_hours": 7.5, "energy_score": 78},
            ],
            "highlight": {"day": "Tue", "label": "Tue", "sleep_label": "Sleep: 7.2"},
            "insight": {
                "message": "Sleep quality is strongly correlated with your energy score.",
                "correlation_label": "strong",
                "r_value": 0.82,
                "recommendation": "Prioritize 7.5h+ for optimal performance.",
            },
        },
        "sleep_energy_correlation_diagram": {
            "title": "Sleep vs. Energy Correlation",
            "bars": [
                {"day": "Mon", "value": 74},
                {"day": "Tue", "value": 72},
                {"day": "Wed", "value": 65},
                {"day": "Thu", "value": 82},
                {"day": "Fri", "value": 78},
                {"day": "Sat", "value": 85},
                {"day": "Sun", "value": 80},
            ],
            "metrics": [
                {"label": "7-Day Avg", "value": "74", "trend": "neutral"},
                {"label": "Peak", "value": "85", "trend": "high"},
                {"label": "Trend", "value": "+6pts", "trend": "up"},
            ],
        },
        "hormone_mood": {
            "title": "Hormones x Mood",
            "summary": "Follicular energy peaks consistently match your highest productivity scores.",
            "neumera_insight": "Plan cognitively demanding work for days 7-13 of your next cycle for a natural performance edge.",
            "signals": [
                {"label": "Hormone phase", "value": "Follicular", "context": "energy rising"},
                {"label": "Mood trend", "value": "More focused", "context": "higher productivity"},
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


def _normalize_key(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, round(number, 2)))


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
