import base64
import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from ai.config import settings
from ai.models.skin_scan_models import (
    SkinRecommendation,
    SkinScanMetrics,
    SkinScanResponse,
    TodaysRecommendations,
)
from ai.utils.claude_llm import ClaudeLLM
from ai.utils.llm_response_parser import LLMResponseParser


RETRYABLE_LLM_STATUS_CODES = {429, 500, 502, 503, 529}
LLM_RETRY_DELAYS_SECONDS = (1.0, 2.0)
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
MAX_CONTEXT_CHARS = 6000


SKIN_SCAN_SYSTEM_PROMPT = """You are an expert cosmetic skin image analysis assistant for a wellness app.

CRITICAL RULES:
- ACTUALLY ANALYZE the provided skin images - look at texture, tone, hydration, pores, redness, elasticity
- Each user's skin is UNIQUE - never return generic or similar scores for different users
- Base ALL scores on VISIBLE skin characteristics in the images
- Do NOT diagnose medical conditions or make clinical claims
- Return ONLY valid JSON - no markdown, code fences, or commentary

ANALYSIS REQUIREMENTS:
- Study skin texture: smooth vs rough, fine lines, wrinkles
- Assess hydration: dry patches, flaking, plumpness
- Check redness: inflammation, irritation, even tone
- Examine pores: visibility, size, congestion
- Evaluate glow: radiance, dullness, vitality
- Consider elasticity: firmness, sagging

SCORES (0-100):
- 0-40: Poor/Needs attention
- 41-60: Fair/Below average  
- 61-75: Good/Average
- 76-90: Very good/Above average
- 91-100: Excellent/Optimal

STATUS MAPPING:
- For hydration/texture/glow/pore_health/elasticity: Low (0-40), Fair (41-60), Good (61-75), High (76-100)
- For redness: Low (0-30 = good), Moderate (31-60), High (61-100 = needs attention)"""


def analyze_skin_scan() -> SkinScanResponse:
    record, image_bytes, content_type = fetch_backend_skin_scan()
    metrics = _generate_skin_metrics(image_bytes, content_type)

    return SkinScanResponse(
        id=_optional_int(record.get("id")),
        user_id=_optional_int(record.get("user_id")),
        image_path=str(record["image_path"]),
        created_at=_optional_str(record.get("created_at")),
        updated_at=_optional_str(record.get("updated_at")),
        **metrics.model_dump(),
    )


def analyze_live_skin_scan(
    image_bytes: bytes,
    content_type: str = "image/jpeg",
    context: dict[str, Any] | None = None,
) -> SkinScanMetrics:
    if not image_bytes:
        raise ValueError("Live skin scan image data is required")
    return _generate_skin_metrics(image_bytes, content_type, context)


def analyze_live_skin_scan_session(
    frames: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
    max_frames: int = 10,
) -> SkinScanMetrics:
    """Analyze all collected live frames together into one overall result."""
    if not frames:
        raise ValueError("At least one skin scan frame is required before finalize")

    selected = _select_session_frames(frames, max_frames=max_frames)
    user_id = extract_skin_scan_user_id(context)
    
    # OPTIMIZED: Single AI call for both metrics AND recommendations
    prompt = _build_skin_scan_session_prompt(len(frames), len(selected), context, user_id)
    response_text = _call_skin_scan_session_llm(selected, prompt)
    
    # Parse metrics - NO FALLBACK, must succeed or raise error
    parsed = _parse_skin_metrics(response_text)
    if not parsed:
        print(f"[ERROR] AI analysis failed for user {user_id}. Raw response: {response_text[:500]}")
        raise ValueError(
            "Skin scan analysis failed. Please ensure good lighting and retake the scan. "
            "If the issue persists, contact support."
        )
    
    return parsed


def generate_skin_recommendations(
    metrics: SkinScanMetrics,
    context: dict[str, Any] | None = None,
) -> TodaysRecommendations:
    """Generate personalized recommendations based on actual skin analysis.
    
    OPTIMIZED: This is called separately only if needed. 
    Prefer using the combined analysis in analyze_live_skin_scan_session_with_recommendations().
    """
    user_id = extract_skin_scan_user_id(context)
    prompt = _build_recommendations_prompt(metrics, context, user_id)
    
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1
    messages = [{"role": "user", "content": prompt}]
    
    for attempt in range(attempts):
        try:
            response = ClaudeLLM().chat(
                messages=messages,
                system="You are a wellness assistant generating personalized skincare recommendations. Return ONLY valid JSON.",
                max_tokens=800,
            )
            response_text = LLMResponseParser.extract_text(response)
            parsed = _parse_recommendations(response_text)
            if parsed:
                return parsed
        except Exception as exc:
            is_last_attempt = attempt == attempts - 1
            if not _is_retryable_llm_error(exc):
                break
            if is_last_attempt:
                break
            time.sleep(LLM_RETRY_DELAYS_SECONDS[attempt])
    
    # If AI fails, return minimal recommendations based on scores
    print(f"[WARNING] Recommendations generation failed for user {user_id}, using score-based fallback")
    return _generate_basic_recommendations(metrics)


def analyze_live_skin_scan_session_with_recommendations(
    frames: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
    max_frames: int = 10,
) -> tuple[SkinScanMetrics, TodaysRecommendations]:
    """OPTIMIZED: Single AI call for both metrics and recommendations.
    
    This is the preferred method as it makes ONE AI call instead of two.
    """
    if not frames:
        raise ValueError("At least one skin scan frame is required before finalize")

    selected = _select_session_frames(frames, max_frames=max_frames)
    user_id = extract_skin_scan_user_id(context)
    
    # Single optimized prompt for both analysis and recommendations
    prompt = _build_combined_analysis_prompt(len(frames), len(selected), context, user_id)
    response_text = _call_skin_scan_session_llm(selected, prompt)
    
    print(f"[DEBUG] AI Response for user {user_id}: {response_text[:500]}...")
    
    # Parse combined response
    parsed_data = _parse_combined_response(response_text, user_id)
    if not parsed_data:
        print(f"[ERROR] Failed to parse AI response for user {user_id}")
        print(f"[ERROR] Full AI response: {response_text}")
        raise ValueError(
            f"AI analysis failed for user {user_id}. Please ensure good lighting and retake the scan."
        )
    
    return parsed_data["metrics"], parsed_data["recommendations"]


def persist_skin_scan(
    frames: list[dict[str, Any]],
    metrics: SkinScanMetrics,
    context: dict[str, Any] | None = None,
) -> SkinScanResponse:
    """Save a completed live session to the backend and return the stored record.

    Best-effort: attempts to POST the representative frame image plus the AI
    metrics to the configured skin-scans endpoint. If the backend does not
    accept the upload (or returns no usable record), the analysis is still
    returned to the client with ``id=None`` and a local ``image_path`` so a
    scan is never lost just because persistence failed.
    """
    user_id = extract_skin_scan_user_id(context)
    timestamp = skin_scan_timestamp()
    representative = frames[-1] if frames else {}
    fallback_image_path = str(
        representative.get("source_path")
        or representative.get("frame_id")
        or "live-session"
    )

    record = _save_skin_scan_to_backend(representative, metrics, user_id)
    if record:
        return SkinScanResponse(
            id=_optional_int(record.get("id")),
            user_id=_optional_int(record.get("user_id")) or user_id,
            image_path=str(record.get("image_path") or fallback_image_path),
            created_at=_optional_str(record.get("created_at")) or timestamp,
            updated_at=_optional_str(record.get("updated_at")) or timestamp,
            **metrics.model_dump(),
        )

    return SkinScanResponse(
        user_id=user_id,
        image_path=fallback_image_path,
        created_at=timestamp,
        updated_at=timestamp,
        **metrics.model_dump(),
    )


def _save_skin_scan_to_backend(
    frame: dict[str, Any],
    metrics: SkinScanMetrics,
    user_id: int | None,
) -> dict[str, Any] | None:
    image_bytes = frame.get("image_bytes") if isinstance(frame, dict) else None
    if not image_bytes:
        return None

    content_type = _image_media_type(str(frame.get("content_type") or "image/jpeg"))
    filename = f"skin_scan.{content_type.split('/')[-1]}"

    data: dict[str, Any] = {key: str(value) for key, value in metrics.model_dump().items()}
    if user_id is not None:
        data["user_id"] = str(user_id)

    try:
        response = httpx.post(
            settings.SKIN_SCANS_URL,
            headers=_backend_headers(),
            data=data,
            files={"image": (filename, image_bytes, content_type)},
            timeout=30.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        if "json" not in response.headers.get("content-type", "").lower():
            return None
        return _extract_saved_skin_scan_record(response.json())
    except Exception:
        return None


def _extract_saved_skin_scan_record(payload: Any) -> dict[str, Any] | None:
    for record in _walk_dicts(payload):
        if _optional_int(record.get("id")) is not None and (
            _image_path_from_record(record) or record.get("image_path")
        ):
            result = dict(record)
            image_path = _image_path_from_record(record) or record.get("image_path")
            if image_path:
                result["image_path"] = image_path
            return result
    return None


def _generate_skin_metrics(
    image_bytes: bytes,
    content_type: str,
    context: dict[str, Any] | None = None,
) -> SkinScanMetrics:
    user_id = extract_skin_scan_user_id(context)
    prompt = _build_skin_scan_prompt(context, user_id)
    response_text = _call_skin_scan_llm(image_bytes, _image_media_type(content_type), prompt)
    parsed = _parse_skin_metrics(response_text)
    if not parsed:
        print(f"[ERROR] AI analysis failed for user {user_id}. Raw response: {response_text[:500]}")
        raise ValueError(
            "Skin scan analysis failed. Please ensure good lighting and retake the scan."
        )
    return parsed


def fetch_skin_scan_context() -> tuple[dict[str, Any], dict[str, str]]:
    sources = {
        "user_profile": settings.CYCLE_ENGINE_PROFILE_URL,
        "health_logs": settings.HEALTH_TRENDS_HEALTH_LOGS_URL,
    }
    context: dict[str, Any] = {}
    errors: dict[str, str] = {}

    for name, url in sources.items():
        payload, error = _try_get_backend_json(url)
        context[name] = payload
        if error:
            errors[name] = error

    return context, errors


def extract_skin_scan_user_id(context: dict[str, Any] | None) -> int | None:
    if not context:
        return None

    user_profile = context.get("user_profile")
    for record in _walk_dicts(user_profile):
        user_id = _optional_int(record.get("user_id"))
        if user_id is not None:
            return user_id

        if any(key in record for key in ("full_name", "email", "user_type", "onboardingCompleted")):
            direct_id = _optional_int(record.get("id"))
            if direct_id is not None:
                return direct_id

        nested_user = record.get("user")
        if isinstance(nested_user, dict):
            nested_id = _optional_int(nested_user.get("id") or nested_user.get("user_id"))
            if nested_id is not None:
                return nested_id

    return None


def skin_scan_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def fetch_skin_scan_image_from_url(image_url: str) -> tuple[bytes, str]:
    response = _get_backend_response(image_url)
    content_type = response.headers.get("content-type", "application/octet-stream")
    if not _is_image_response(content_type, response.content):
        raise ValueError("Skin scan image URL did not return an image file")
    return response.content, content_type


def fetch_backend_skin_scan() -> tuple[dict[str, Any], bytes, str]:
    response = _get_backend_response(settings.SKIN_SCANS_URL)
    content_type = response.headers.get("content-type", "application/octet-stream")

    if _is_image_response(content_type, response.content):
        record = {"image_path": settings.SKIN_SCANS_URL}
        return record, response.content, content_type

    if "json" not in content_type.lower():
        raise ValueError("Backend skin scan route did not return JSON or an image file")

    record = _extract_skin_scan_record(response.json())
    image_path = str(record["image_path"])
    image_response = _get_backend_response(image_path)
    image_content_type = image_response.headers.get("content-type", "application/octet-stream")

    if not _is_image_response(image_content_type, image_response.content):
        raise ValueError("Backend skin scan image link did not return an image file")

    return record, image_response.content, image_content_type


def _build_skin_scan_prompt(context: dict[str, Any] | None = None, user_id: int | None = None) -> str:
    context_json = _skin_scan_context_json(context)
    user_context = f" for user_id={user_id}" if user_id else ""
    base_prompt = f"""CRITICAL: Actually analyze THIS specific user's skin{user_context}. Do NOT return generic scores.

Analyze this skin scan image and generate this exact JSON shape:
{
  "overall_score": 80,
  "hydration_score": 72,
  "redness_score": 22,
  "texture_score": 84,
  "glow_index": 68,
  "pore_health_score": 79,
  "elasticity_score": 81,
  "hydration_status": "Fair",
  "redness_status": "Low",
  "texture_status": "Good",
  "glow_status": "Fair",
  "pore_health_status": "Low",
  "elasticity_status": "Good",
  "neumera_insight": "..."
}

Requirements:
- Return only the analysis fields above. Do not include id, user_id, image_path, created_at, or updated_at.
- All score fields must be integers from 0 to 100.
- Make neumera_insight concise, practical, and non-medical.
- If only the image is available, base neumera_insight only on visible skin appearance and general skincare habits.
- Use backend wellness context only when it is present in the JSON below.
- You may reference user profile or health-log context in neumera_insight, but keep it cautious and non-medical.
- Do not claim exact sleep, water, wearable, cycle, or lifestyle correlations unless those data are explicitly provided.

Backend wellness context JSON:
"""
    return f"{base_prompt}{context_json}"


def _build_skin_scan_session_prompt(
    total_frames: int,
    selected_frames: int,
    context: dict[str, Any] | None = None,
    user_id: int | None = None,
) -> str:
    context_json = _skin_scan_context_json(context)
    user_context = f" for user_id={user_id}" if user_id else ""
    return f"""CRITICAL: Actually analyze THIS specific user's skin{user_context}. Each person has UNIQUE skin - DO NOT return generic scores.

INSTRUCTIONS:
- You received {selected_frames} frame(s) from a session that captured {total_frames} frame(s) total
- CAREFULLY EXAMINE each image - look at texture, hydration, pores, redness, tone
- Compare patterns across frames to get accurate assessment
- Scores must reflect ACTUAL visible skin characteristics
- Each user gets DIFFERENT scores based on THEIR skin

Generate this exact JSON shape:
{{
  "overall_score": 80,
  "hydration_score": 72,
  "redness_score": 22,
  "texture_score": 84,
  "glow_index": 68,
  "pore_health_score": 79,
  "elasticity_score": 81,
  "hydration_status": "Fair",
  "redness_status": "Low",
  "texture_status": "Good",
  "glow_status": "Fair",
  "pore_health_status": "Low",
  "elasticity_status": "Good",
  "neumera_insight": "..."
}}

Requirements:
- Base scores on VISIBLE skin features in the images
- neumera_insight must describe what you ACTUALLY SEE in these images
- Mention specific observations (e.g., "visible fine lines", "even tone", "enlarged pores")
- Keep insight concise (2-3 sentences), practical, non-medical

User wellness context:
{context_json}
"""


def _build_combined_analysis_prompt(
    total_frames: int,
    selected_frames: int,
    context: dict[str, Any] | None = None,
    user_id: int | None = None,
) -> str:
    """OPTIMIZED: Single prompt for both metrics AND recommendations."""
    context_json = _skin_scan_context_json(context)
    user_context = f" for user_id={user_id}" if user_id else ""
    return f"""CRITICAL: Actually analyze THIS specific user's skin{user_context}. Each person has UNIQUE skin.

TASK: Analyze {selected_frames} frame(s) from {total_frames} total and provide:
1. Detailed skin metrics based on what you ACTUALLY SEE
2. Personalized recommendations based on the analysis

Generate this EXACT JSON structure:
{{
  "metrics": {{
    "overall_score": 75,
    "hydration_score": 68,
    "redness_score": 25,
    "texture_score": 72,
    "glow_index": 65,
    "pore_health_score": 70,
    "elasticity_score": 73,
    "hydration_status": "Fair",
    "redness_status": "Low",
    "texture_status": "Good",
    "glow_status": "Fair",
    "pore_health_status": "Fair",
    "elasticity_status": "Good",
    "neumera_insight": "Based on the images, your skin shows..."
  }},
  "recommendations": {{
    "analysis_summary": "Brief summary of why these recommendations",
    "recommendations": [
      {{
        "icon": "💧",
        "text": "Specific actionable recommendation",
        "priority": "high",
        "category": "hydration"
      }}
    ]
  }}
}}

SCORING RULES:
- Study VISIBLE skin characteristics in the images
- Hydration: look for dryness, flaking, plumpness (0=very dry, 100=well hydrated)
- Redness: inflammation, uneven tone (0=very red, 100=clear even tone)
- Texture: smoothness, fine lines, roughness (0=very rough, 100=very smooth)
- Glow: radiance, vitality vs dullness (0=very dull, 100=radiant)
- Pore health: visibility, size (0=very visible/large, 100=minimized)
- Elasticity: firmness (0=very loose, 100=very firm)

RECOMMENDATIONS RULES:
- Generate 3-5 specific, actionable recommendations
- Base on actual analysis (e.g., if hydration < 70, recommend water/moisturizer)
- Use appropriate icons: 💧 (water), 🌙 (sleep), 🧴 (skincare), 🥗 (nutrition)
- Priority: "high" for scores < 60, "medium" for 60-75, "low" for > 75
- Categories: "hydration", "sleep", "skincare", "nutrition"

User wellness context:
{context_json}
"""


def _select_session_frames(frames: list[dict[str, Any]], max_frames: int = 10) -> list[dict[str, Any]]:
    if len(frames) <= max_frames:
        return frames
    if max_frames <= 1:
        return [frames[-1]]
    # Evenly sample across the session so early/mid/late frames are represented.
    indexes = [
        round(index * (len(frames) - 1) / (max_frames - 1))
        for index in range(max_frames)
    ]
    selected: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index in indexes:
        if index in seen:
            continue
        seen.add(index)
        selected.append(frames[index])
    return selected


def _call_skin_scan_llm(image_bytes: bytes, media_type: str, prompt: str) -> str:
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(image_bytes).decode("ascii"),
            },
        },
        {"type": "text", "text": prompt},
    ]
    return _chat_skin_scan(content)


def _call_skin_scan_session_llm(frames: list[dict[str, Any]], prompt: str, max_tokens: int = 2500) -> str:
    content: list[dict[str, Any]] = []
    for index, frame in enumerate(frames, start=1):
        image_bytes = frame.get("image_bytes") or b""
        if not image_bytes:
            continue
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": _image_media_type(str(frame.get("content_type") or "image/jpeg")),
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                },
            }
        )
        content.append({"type": "text", "text": f"Frame {index} of {len(frames)}"})
    content.append({"type": "text", "text": prompt})
    return _chat_skin_scan(content, max_tokens=max_tokens)


def _chat_skin_scan(content: list[dict[str, Any]], max_tokens: int = 1200) -> str:
    if not any(block.get("type") == "image" for block in content):
        print("[ERROR] _chat_skin_scan: No image blocks in content")
        return ""

    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1
    messages = [{"role": "user", "content": content}]

    for attempt in range(attempts):
        try:
            response = ClaudeLLM().chat(
                messages=messages,
                system=SKIN_SCAN_SYSTEM_PROMPT,
                max_tokens=max_tokens,
            )
            return LLMResponseParser.extract_text(response)
        except Exception as exc:
            print(f"[ERROR] _chat_skin_scan attempt {attempt+1} failed: {exc}")
            is_last_attempt = attempt == attempts - 1
            if not _is_retryable_llm_error(exc):
                raise
            if is_last_attempt:
                return ""
            time.sleep(LLM_RETRY_DELAYS_SECONDS[attempt])

    return ""


def _parse_skin_metrics(text: str) -> SkinScanMetrics | None:
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
        return SkinScanMetrics.model_validate(_coerce_skin_metrics(payload))
    except Exception:
        return None


def _coerce_skin_metrics(payload: Any) -> dict[str, Any]:
    """Coerce AI payload to valid skin metrics. Requires all score fields from AI."""
    if not isinstance(payload, dict):
        print("[ERROR] _coerce_skin_metrics: payload is not a dict")
        return {}

    # Extract all score fields (MUST be present)
    required_scores = [
        "overall_score", "hydration_score", "redness_score", 
        "texture_score", "glow_index", "pore_health_score", "elasticity_score"
    ]
    
    # Check if AI provided all scores
    scores = {}
    missing_fields = []
    for score_key in required_scores:
        value = payload.get(score_key)
        if value is None:
            missing_fields.append(score_key)
            continue
        
        score_value = _score(value, None)
        if score_value is None:
            print(f"[ERROR] Invalid score value for {score_key}: {value}")
            return {}
        scores[score_key] = score_value
    
    if missing_fields:
        print(f"[ERROR] _coerce_skin_metrics: Missing required fields: {missing_fields}")
        print(f"[ERROR] Payload keys: {list(payload.keys())}")
        return {}

    # Get statuses from AI or derive from scores
    return {
        **scores,
        "hydration_status": _status(payload.get("hydration_status"), scores["hydration_score"]),
        "redness_status": _redness_status(payload.get("redness_status"), scores["redness_score"]),
        "texture_status": _status(payload.get("texture_status"), scores["texture_score"]),
        "glow_status": _status(payload.get("glow_status"), scores["glow_index"]),
        "pore_health_status": _status(payload.get("pore_health_status"), scores["pore_health_score"]),
        "elasticity_status": _status(payload.get("elasticity_status"), scores["elasticity_score"]),
        "neumera_insight": str(payload.get("neumera_insight") or ""),
    }



def _parse_recommendations(text: str) -> TodaysRecommendations | None:
    """Parse AI-generated recommendations from JSON response."""
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
        return TodaysRecommendations.model_validate(payload)
    except Exception:
        return None


def _parse_combined_response(text: str, user_id: int | None) -> dict[str, Any] | None:
    """Parse combined metrics + recommendations from single AI response."""
    if not text:
        print(f"[ERROR] Empty AI response for user {user_id}")
        return None

    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(line for line in lines if not line.startswith("```")).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        print(f"[ERROR] No JSON found in AI response for user {user_id}")
        print(f"[ERROR] Response text: {cleaned[:200]}")
        return None

    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON parse failed for user {user_id}: {e}")
        print(f"[ERROR] JSON text: {cleaned[start:end+1][:300]}")
        return None

    # Extract metrics and recommendations
    metrics_data = payload.get("metrics")
    recommendations_data = payload.get("recommendations")

    if not metrics_data:
        print(f"[ERROR] Missing 'metrics' in AI response for user {user_id}")
        print(f"[ERROR] Payload keys: {list(payload.keys())}")
        return None
    
    if not recommendations_data:
        print(f"[ERROR] Missing 'recommendations' in AI response for user {user_id}")
        print(f"[ERROR] Payload keys: {list(payload.keys())}")
        return None

    try:
        # Coerce metrics
        coerced_metrics = _coerce_skin_metrics(metrics_data)
        if not coerced_metrics:
            print(f"[ERROR] _coerce_skin_metrics returned empty dict for user {user_id}")
            return None
        
        metrics = SkinScanMetrics.model_validate(coerced_metrics)

        # Inject timestamp before validation so a missing field never fails validation
        if isinstance(recommendations_data, dict) and not recommendations_data.get("generated_at"):
            recommendations_data["generated_at"] = skin_scan_timestamp()
        recommendations = TodaysRecommendations.model_validate(recommendations_data)
        
        return {
            "metrics": metrics,
            "recommendations": recommendations,
        }
    except Exception as e:
        print(f"[ERROR] Failed to validate combined response for user {user_id}: {e}")
        print(f"[ERROR] Metrics data: {metrics_data}")
        print(f"[ERROR] Recommendations data: {recommendations_data}")
        return None


def _generate_basic_recommendations(metrics: SkinScanMetrics) -> TodaysRecommendations:
    """Generate basic recommendations from scores when AI fails.
    This is a minimal fallback - AI should normally handle this.
    """
    recommendations: list[SkinRecommendation] = []
    issues = []

    if metrics.hydration_score < 70:
        recommendations.append(
            SkinRecommendation(
                icon="💧",
                text="Drink 500ml extra water before 3pm",
                priority="high" if metrics.hydration_score < 60 else "medium",
                category="hydration",
            )
        )
        issues.append("low hydration")

    if metrics.glow_index < 70:
        recommendations.append(
            SkinRecommendation(
                icon="🌙",
                text="Aim for 7h+ sleep — set 10pm wind-down",
                priority="medium",
                category="sleep",
            )
        )
        issues.append("reduced glow")

    if metrics.redness_score > 30 or metrics.texture_score < 70:
        recommendations.append(
            SkinRecommendation(
                icon="🧴",
                text="Apply SPF 30+ before going outside",
                priority="high",
                category="skincare",
            )
        )
        if metrics.redness_score > 30:
            issues.append("skin redness")

    if metrics.texture_score < 70 or metrics.elasticity_score < 70:
        recommendations.append(
            SkinRecommendation(
                icon="🥗",
                text="Add Vitamin C rich foods to your next meal",
                priority="medium",
                category="nutrition",
            )
        )

    if not recommendations:
        # Skin looks good, add maintenance tips
        recommendations.append(
            SkinRecommendation(
                icon="🧴",
                text="Maintain your current skincare routine",
                priority="low",
                category="skincare",
            )
        )

    summary = f"Based on your skin analysis showing {', '.join(issues)}" if issues else "Your skin looks good"

    return TodaysRecommendations(
        recommendations=recommendations,
        generated_at=skin_scan_timestamp(),
        analysis_summary=summary,
    )


def _build_recommendations_prompt(
    metrics: SkinScanMetrics,
    context: dict[str, Any] | None,
    user_id: int | None,
) -> str:
    """Build prompt for generating recommendations separately (less optimal than combined)."""
    context_json = _skin_scan_context_json(context)
    user_context = f" for user_id={user_id}" if user_id else ""
    
    return f"""Generate personalized skincare recommendations{user_context} based on this skin analysis:

Skin Metrics:
- Overall: {metrics.overall_score}/100
- Hydration: {metrics.hydration_score}/100 ({metrics.hydration_status})
- Redness: {metrics.redness_score}/100 ({metrics.redness_status})
- Texture: {metrics.texture_score}/100 ({metrics.texture_status})
- Glow: {metrics.glow_index}/100 ({metrics.glow_status})
- Pore Health: {metrics.pore_health_score}/100 ({metrics.pore_health_status})
- Elasticity: {metrics.elasticity_score}/100 ({metrics.elasticity_status})

Analysis: {metrics.neumera_insight}

Generate this EXACT JSON structure:
{{
  "analysis_summary": "Brief summary of key skin concerns",
  "recommendations": [
    {{
      "icon": "💧",
      "text": "Specific actionable recommendation",
      "priority": "high",
      "category": "hydration"
    }}
  ]
}}

RULES:
- Generate 3-5 specific, actionable recommendations
- Address the LOWEST scoring areas first
- Use icons: 💧 (water), 🌙 (sleep), 🧴 (skincare), 🥗 (nutrition)
- Priority: "high" (scores < 60), "medium" (60-75), "low" (> 75)
- Categories: "hydration", "sleep", "skincare", "nutrition"

User context:
{context_json}
"""


def _skin_scan_context_json(context: dict[str, Any] | None) -> str:
    if not context:
        return "{}"
    return json.dumps(context, ensure_ascii=False, default=str)[:MAX_CONTEXT_CHARS]


def _try_get_backend_json(url: str) -> tuple[Any | None, str | None]:
    try:
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
        return response.json(), None
    except Exception as exc:
        return None, str(exc)


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dicts(item)

def _extract_skin_scan_record(payload: Any) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            image_path = _image_path_from_record(value)
            if image_path:
                record = dict(value)
                record["image_path"] = image_path
                candidates.append(record)

            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)

    if not candidates:
        raise ValueError("Backend skin scan response did not include an image link")

    return candidates[0]


def _image_path_from_record(record: dict[str, Any]) -> str | None:
    preferred_keys = ("image_path", "skin_scan", "skin_scan_image", "image", "photo", "picture")

    for key in preferred_keys:
        value = record.get(key)
        if isinstance(value, str) and _looks_like_image_path(value):
            return value

    for key, value in record.items():
        if not isinstance(value, str):
            continue
        key_name = str(key).lower()
        if any(marker in key_name for marker in ("image", "skin", "photo", "picture", "file", "url", "path")):
            if _looks_like_image_path(value):
                return value

    return None


def _looks_like_image_path(value: str) -> bool:
    lowered = value.lower().split("?")[0]
    return lowered.startswith(("http://", "https://", "/")) and lowered.endswith(IMAGE_EXTENSIONS)


def _get_backend_response(path: str) -> httpx.Response:
    url = _backend_url(path)
    response = httpx.get(url, headers=_backend_headers(), timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    return response


def _backend_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json, image/*",
        "ngrok-skip-browser-warning": "true",
    }

    token = settings.CYCLE_ENGINE_ACCESS_TOKEN or settings.BACKEND_ACCESS_TOKEN
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["access-token"] = token
        headers["x-access-token"] = token

    return headers


def _backend_url(path: str) -> str:
    cleaned = path.strip()
    if not cleaned:
        raise ValueError("Backend skin scan path is required")

    if cleaned.startswith(("http://", "https://")):
        parsed = urlparse(cleaned)
        if parsed.hostname in {"127.0.0.1", "localhost"} and parsed.path.startswith("/storage/"):
            return f"{_skin_scans_origin()}{parsed.path}"
        if not _is_allowed_backend_url(cleaned):
            raise ValueError("Full URLs are only allowed for configured skin scan resources")
        return cleaned

    normalized_path = cleaned if cleaned.startswith("/") else f"/{cleaned}"
    if normalized_path.startswith("/storage/"):
        return f"{_skin_scans_origin()}{normalized_path}"
    return f"{settings.BACKEND_URL.rstrip('/')}{normalized_path}"


def _is_allowed_backend_url(url: str) -> bool:
    configured_urls = (
        settings.SKIN_SCANS_URL,
        settings.BACKEND_URL,
        settings.LAB_REPORTS_URL,
        settings.CYCLE_ENGINE_PROFILE_URL,
        settings.CYCLE_ENGINE_SNAPSHOT_URL,
        settings.HEALTH_TRENDS_HEALTH_LOGS_URL,
    )
    if url in configured_urls:
        return True

    parsed = urlparse(url)
    allowed_netlocs = {_origin_netloc(configured_url) for configured_url in configured_urls if configured_url}
    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc in allowed_netlocs
        and (parsed.path.startswith("/storage/") or parsed.path.startswith("/api/"))
    )


def _skin_scans_origin() -> str:
    parsed = urlparse(settings.SKIN_SCANS_URL)
    return f"{parsed.scheme}://{parsed.netloc}"


def _origin_netloc(url: str) -> str:
    return urlparse(url).netloc


def _is_image_response(content_type: str, content: bytes) -> bool:
    lowered = content_type.lower()
    return lowered.startswith("image/") or content.startswith((b"\xff\xd8\xff", b"\x89PNG", b"RIFF", b"GIF"))


def _image_media_type(content_type: str) -> str:
    lowered = content_type.split(";")[0].strip().lower()
    if lowered in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        return lowered
    return "image/jpeg"


def _score(value: Any, default: int) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = default
    return max(0, min(100, number))


def _status(value: Any, score: int) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if score >= 80:
        return "Good"
    if score >= 60:
        return "Fair"
    return "Low"


def _redness_status(value: Any, score: int) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if score <= 25:
        return "Low"
    if score <= 55:
        return "Fair"
    return "High"


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


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
