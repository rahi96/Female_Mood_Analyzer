import base64
import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from ai.config import settings
from ai.models.skin_scan_models import SkinScanMetrics, SkinScanResponse
from ai.utils.claude_llm import ClaudeLLM
from ai.utils.llm_response_parser import LLMResponseParser


RETRYABLE_LLM_STATUS_CODES = {429, 500, 502, 503, 529}
LLM_RETRY_DELAYS_SECONDS = (1.0, 2.0)
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
MAX_CONTEXT_CHARS = 6000


SKIN_SCAN_SYSTEM_PROMPT = """You are a careful cosmetic skin image analysis assistant for a wellness app.

Rules:
- Analyze only visible, non-identifying skin appearance in the provided image.
- Do not diagnose medical conditions, identify a person, or make clinical claims.
- Estimate cosmetic/wellness scores from 0 to 100.
- Use short statuses such as Low, Fair, Good, High, or Needs attention.
- Do not invent wearable, sleep, water-intake, cycle, or health-log context unless it is explicitly included in the prompt.
- Return valid JSON only. Do not add markdown, code fences, or extra commentary.
"""


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
    prompt = _build_skin_scan_session_prompt(len(frames), len(selected), context)
    response_text = _call_skin_scan_session_llm(selected, prompt)
    parsed = _parse_skin_metrics(response_text)
    if parsed:
        return parsed
    return _fallback_skin_metrics()


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


def _generate_skin_metrics(
    image_bytes: bytes,
    content_type: str,
    context: dict[str, Any] | None = None,
) -> SkinScanMetrics:
    prompt = _build_skin_scan_prompt(context)
    response_text = _call_skin_scan_llm(image_bytes, _image_media_type(content_type), prompt)
    parsed = _parse_skin_metrics(response_text)
    if parsed:
        return parsed
    return _fallback_skin_metrics()


def _build_skin_scan_prompt(context: dict[str, Any] | None = None) -> str:
    context_json = _skin_scan_context_json(context)
    base_prompt = """Analyze this skin scan image and generate this exact JSON shape:
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
) -> str:
    context_json = _skin_scan_context_json(context)
    return f"""Analyze ALL of these live skin-scan frames together as one session.

You received {selected_frames} frame image(s) from a session that captured {total_frames} frame(s) total.
Produce one overall cosmetic/wellness assessment across the full set — not a separate score per frame.

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
- Return only the analysis fields above. Do not include id, user_id, image_path, created_at, or updated_at.
- All score fields must be integers from 0 to 100.
- Prefer patterns that appear across multiple frames; discount one-off lighting/angle artifacts.
- Make neumera_insight concise, practical, and non-medical.
- Use backend wellness context only when present in the JSON below.
- Do not invent wearable, sleep, water-intake, cycle, or lifestyle correlations unless those data are explicitly provided.

Backend wellness context JSON:
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


def _call_skin_scan_session_llm(frames: list[dict[str, Any]], prompt: str) -> str:
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
    return _chat_skin_scan(content)


def _chat_skin_scan(content: list[dict[str, Any]]) -> str:
    if not any(block.get("type") == "image" for block in content):
        return ""

    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1
    messages = [{"role": "user", "content": content}]

    for attempt in range(attempts):
        try:
            response = ClaudeLLM().chat(
                messages=messages,
                system=SKIN_SCAN_SYSTEM_PROMPT,
                max_tokens=1200,
            )
            return LLMResponseParser.extract_text(response)
        except Exception as exc:
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
    if not isinstance(payload, dict):
        payload = {}

    scores = {
        "overall_score": _score(payload.get("overall_score"), 75),
        "hydration_score": _score(payload.get("hydration_score"), 70),
        "redness_score": _score(payload.get("redness_score"), 25),
        "texture_score": _score(payload.get("texture_score"), 75),
        "glow_index": _score(payload.get("glow_index"), 70),
        "pore_health_score": _score(payload.get("pore_health_score"), 75),
        "elasticity_score": _score(payload.get("elasticity_score"), 75),
    }

    return {
        **scores,
        "hydration_status": _status(payload.get("hydration_status"), scores["hydration_score"]),
        "redness_status": _redness_status(payload.get("redness_status"), scores["redness_score"]),
        "texture_status": _status(payload.get("texture_status"), scores["texture_score"]),
        "glow_status": _status(payload.get("glow_status"), scores["glow_index"]),
        "pore_health_status": _status(payload.get("pore_health_status"), scores["pore_health_score"]),
        "elasticity_status": _status(payload.get("elasticity_status"), scores["elasticity_score"]),
        "neumera_insight": str(
            payload.get("neumera_insight")
            or "Skin appearance looks generally balanced in this image. Keep hydration, gentle cleansing, SPF, and consistent sleep as priorities, and retake scans in similar lighting for better trend tracking."
        ),
    }


def _fallback_skin_metrics() -> SkinScanMetrics:
    return SkinScanMetrics(
        overall_score=75,
        hydration_score=70,
        redness_score=25,
        texture_score=75,
        glow_index=70,
        pore_health_score=75,
        elasticity_score=75,
        hydration_status="Fair",
        redness_status="Low",
        texture_status="Fair",
        glow_status="Fair",
        pore_health_status="Fair",
        elasticity_status="Fair",
        neumera_insight=(
            "The skin scan image was received, but AI analysis could not be completed. "
            "Retake the scan in even natural light and keep hydration, gentle cleansing, and SPF consistent."
        ),
    )



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
