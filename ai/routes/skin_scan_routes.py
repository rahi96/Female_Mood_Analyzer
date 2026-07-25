import base64
import binascii
import json
import re
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from ai.models.skin_scan_models import SkinScanResponse
from ai.services.skin_scan_service import analyze_live_skin_scan, analyze_skin_scan


router = APIRouter()


@router.post("/skin-scan", response_model=SkinScanResponse)
async def skin_scan_endpoint():
    try:
        return analyze_skin_scan()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Skin scan analysis failed: {exc}")


@router.websocket("/skin-scan/live")
async def skin_scan_live_websocket(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_json(
        {
            "type": "skin_scan_ready",
            "success": True,
            "message": "Send a camera frame as binary image data or JSON with image_base64/image/data.",
        }
    )

    while True:
        try:
            message = await websocket.receive()
        except WebSocketDisconnect:
            break

        if message.get("type") == "websocket.disconnect":
            break

        try:
            if _is_ping_message(message):
                await websocket.send_json({"type": "pong", "success": True})
                continue

            image_bytes, content_type, frame_id = _extract_live_image_message(message)
            metrics = analyze_live_skin_scan(image_bytes, content_type)
            await websocket.send_json(
                {
                    "type": "skin_scan_result",
                    "success": True,
                    "frame_id": frame_id,
                    "content_type": content_type,
                    "metrics": metrics.model_dump(),
                }
            )
        except WebSocketDisconnect:
            break
        except Exception as exc:
            await websocket.send_json(
                {
                    "type": "skin_scan_error",
                    "success": False,
                    "detail": str(exc),
                }
            )


def _is_ping_message(message: dict[str, Any]) -> bool:
    text = message.get("text")
    if not isinstance(text, str):
        return False

    cleaned = text.strip()
    if cleaned.lower() == "ping":
        return True

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return False

    return isinstance(payload, dict) and str(payload.get("type", "")).lower() == "ping"


def _extract_live_image_message(message: dict[str, Any]) -> tuple[bytes, str, str | None]:
    binary = message.get("bytes")
    if binary:
        return binary, _detect_image_content_type(binary, "image/jpeg"), None

    text = message.get("text")
    if not text:
        raise ValueError("Send image bytes or a JSON/base64 image payload")

    payload = _parse_text_payload(text)
    if isinstance(payload, dict):
        image_value = (
            payload.get("image_base64")
            or payload.get("image")
            or payload.get("frame")
            or payload.get("data")
        )
        content_type = str(payload.get("content_type") or payload.get("mime_type") or "image/jpeg")
        frame_id = _optional_str(payload.get("frame_id") or payload.get("id"))
        if not isinstance(image_value, str):
            raise ValueError("JSON payload must include image_base64, image, frame, or data")
        return _decode_base64_image(image_value, content_type, frame_id)

    return _decode_base64_image(str(payload), "image/jpeg", None)


def _parse_text_payload(text: str) -> Any:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("Image payload is empty")

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return cleaned


def _decode_base64_image(value: str, content_type: str, frame_id: str | None) -> tuple[bytes, str, str | None]:
    image_value = value.strip().strip('"')
    detected_content_type = content_type

    if image_value.startswith(("blob:", "http://", "https://")):
        raise ValueError(
            "Send the actual JPEG bytes or base64/data URL content, not a blob URL, file path, or remote URL"
        )

    if image_value.startswith("data:") or ("," in image_value and "base64" in image_value.split(",", 1)[0].lower()):
        header, _, encoded = image_value.partition(",")
        if not encoded:
            raise ValueError("Data URL image payload is missing base64 data")
        detected_content_type = _content_type_from_data_url(header) or content_type
        image_value = encoded

    compact_value = re.sub(r"\s+", "", image_value)
    padded_value = compact_value + ("=" * (-len(compact_value) % 4))

    try:
        image_bytes = base64.b64decode(padded_value, validate=True)
    except (binascii.Error, ValueError):
        try:
            image_bytes = base64.urlsafe_b64decode(padded_value)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(
                "Image payload must be valid base64. Send JPEG as a binary WebSocket frame or as image_base64/data URL."
            ) from exc

    if not image_bytes:
        raise ValueError("Decoded image payload is empty")
    if not _looks_like_supported_image(image_bytes):
        raise ValueError("Decoded image payload is not a supported JPEG, PNG, WebP, or GIF image")

    return image_bytes, _detect_image_content_type(image_bytes, detected_content_type), frame_id


def _detect_image_content_type(image_bytes: bytes, fallback: str) -> str:
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG"):
        return "image/png"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    if image_bytes.startswith(b"GIF"):
        return "image/gif"
    return _safe_image_content_type(fallback)


def _looks_like_supported_image(image_bytes: bytes) -> bool:
    return _detect_image_content_type(image_bytes, "") in {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _content_type_from_data_url(header: str) -> str | None:
    prefix = "data:"
    if not header.startswith(prefix):
        return None
    media_type = header[len(prefix) :].split(";", 1)[0].strip().lower()
    return media_type or None


def _safe_image_content_type(content_type: str) -> str:
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        return normalized
    return "image/jpeg"


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
