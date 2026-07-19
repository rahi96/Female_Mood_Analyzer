import base64
import json
import time
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


def _generate_skin_metrics(image_bytes: bytes, content_type: str) -> SkinScanMetrics:
    prompt = _build_skin_scan_prompt()
    response_text = _call_skin_scan_llm(image_bytes, _image_media_type(content_type), prompt)
    parsed = _parse_skin_metrics(response_text)
    if parsed:
        return parsed
    return _fallback_skin_metrics()


def _build_skin_scan_prompt() -> str:
    return """Analyze this skin scan image and generate this exact JSON shape:
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
- Do not claim exact sleep, water, wearable, cycle, or lifestyle correlations unless those data are explicitly provided.
"""


def _call_skin_scan_llm(image_bytes: bytes, media_type: str, prompt: str) -> str:
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1
    image_data = base64.b64encode(image_bytes).decode("ascii")
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_data,
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }
    ]

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

    if settings.BACKEND_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {settings.BACKEND_ACCESS_TOKEN}"
        headers["access-token"] = settings.BACKEND_ACCESS_TOKEN
        headers["x-access-token"] = settings.BACKEND_ACCESS_TOKEN

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
    if url == settings.SKIN_SCANS_URL:
        return True

    parsed = urlparse(url)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc in {_origin_netloc(settings.SKIN_SCANS_URL), _origin_netloc(settings.BACKEND_URL)}
        and (parsed.path.startswith("/storage/") or parsed.path.startswith(urlparse(settings.BACKEND_URL).path))
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
