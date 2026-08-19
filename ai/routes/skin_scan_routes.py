import asyncio
import base64
import binascii
import contextlib
import json
import re
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from ai.models.skin_scan_models import SkinScanResponse
from ai.services.skin_scan_service import (
    _optional_int,
    analyze_live_skin_scan,
    analyze_live_skin_scan_session,
    extract_skin_scan_user_id,
    fetch_skin_scan_context,
    fetch_skin_scan_image_from_url,
    persist_skin_scan,
    skin_scan_timestamp,
)


router = APIRouter()

# Seconds of live capture after the first frame arrives before the server
# automatically stops the scan and analyzes all collected frames together.
SKIN_SCAN_CAPTURE_WINDOW_SECONDS = 20.0


@router.post("/skin-scan", response_model=SkinScanResponse)
async def skin_scan_endpoint(
    request: Request,
    file: UploadFile | None = File(default=None),
    file_upper: UploadFile | None = File(default=None, alias="File"),
    image_url: str | None = Form(default=None),
    image_base64: str | None = Form(default=None),
    image: str | None = Form(default=None),
    content_type: str | None = Form(default=None),
):
    try:
        image_bytes, detected_content_type, source_path = await _extract_post_skin_scan_image(
            request=request,
            file=file or file_upper,
            image_url=image_url,
            image_base64=image_base64,
            image=image,
            content_type=content_type,
        )
        context, _ = fetch_skin_scan_context()
        metrics = analyze_live_skin_scan(image_bytes, detected_content_type, context=context)
        timestamp = skin_scan_timestamp()
        return SkinScanResponse(
            user_id=extract_skin_scan_user_id(context),
            image_path=source_path,
            created_at=timestamp,
            updated_at=timestamp,
            **metrics.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Skin scan analysis failed: {exc}")


async def _extract_post_skin_scan_image(
    request: Request,
    file: UploadFile | None,
    image_url: str | None,
    image_base64: str | None,
    image: str | None,
    content_type: str | None,
) -> tuple[bytes, str, str]:
    if file is not None:
        file_bytes = await file.read()
        if not file_bytes:
            raise ValueError("Uploaded skin scan file is empty")
        if not _looks_like_supported_image(file_bytes):
            raise ValueError("Uploaded file is not a supported JPEG, PNG, WebP, or GIF image")
        return file_bytes, _detect_image_content_type(file_bytes, file.content_type or content_type or "image/jpeg"), file.filename or "uploaded-file"

    json_payload = await _read_optional_json_payload(request)
    image_url = image_url or _optional_str(json_payload.get("image_url") or json_payload.get("image_path") or json_payload.get("url"))
    image_base64 = image_base64 or _optional_str(json_payload.get("image_base64"))
    image = image or _optional_str(json_payload.get("image") or json_payload.get("data") or json_payload.get("frame"))
    content_type = content_type or _optional_str(json_payload.get("content_type") or json_payload.get("mime_type"))

    payload: dict[str, Any] = {
        "image_url": image_url,
        "image_base64": image_base64,
        "image": image,
        "content_type": content_type or "image/jpeg",
    }

    normalized_url = _image_url_from_payload(payload)
    if normalized_url:
        image_bytes, fetched_content_type = fetch_skin_scan_image_from_url(normalized_url)
        return image_bytes, fetched_content_type, normalized_url

    image_value = image_base64 or image
    if isinstance(image_value, str) and image_value.strip():
        image_bytes, detected_content_type, _ = _decode_base64_image(
            image_value,
            content_type or "image/jpeg",
            None,
        )
        return image_bytes, detected_content_type, "uploaded-base64"

    raise ValueError("Send a skin image as form-data file, image_url, image_base64, or image data URL")


@router.websocket("/skin-scan-ws")
@router.websocket("/skin-scan/live")
async def skin_scan_live_websocket(websocket: WebSocket):
    await websocket.accept()
    session_frames: list[dict[str, Any]] = []
    # Guards a single finalize: whichever fires first (timer, finalize message,
    # or disconnect) wins, and the others become no-ops.
    finalized = False
    capture_timer: asyncio.Task | None = None

    await websocket.send_json(
        {
            "type": "skin_scan_ready",
            "success": True,
            "capture_window_seconds": SKIN_SCAN_CAPTURE_WINDOW_SECONDS,
            "message": (
                "Stream camera frames as image bytes, base64/data URL, or JSON with image_url. "
                f"Capture runs for {int(SKIN_SCAN_CAPTURE_WINDOW_SECONDS)}s after the first frame, then "
                "the server automatically analyzes all frames together. Send {\"type\":\"finalize\"} "
                "to stop early."
            ),
        }
    )

    async def run_finalize(reason: str) -> None:
        nonlocal finalized
        if finalized:
            return
        finalized = True
        if not session_frames:
            await _safe_send_json(
                websocket,
                {
                    "type": "skin_scan_error",
                    "success": False,
                    "detail": "No frames were received before the scan stopped.",
                    "reason": reason,
                },
            )
            return

        frame_count = len(session_frames)
        await _safe_send_json(
            websocket,
            {
                "type": "analyzing",
                "success": True,
                "reason": reason,
                "frame_count": frame_count,
                "message": "Capture complete. Analyzing all frames together...",
            },
        )

        try:
            # Fetch user context once
            context, _ = await run_in_threadpool(fetch_skin_scan_context)
            
            # OPTIMIZED: Single AI call for both metrics AND recommendations
            metrics, recommendations = await run_in_threadpool(
                analyze_live_skin_scan_session_with_recommendations, session_frames, context
            )
            
            # Persist scan results to backend
            scan_response = await run_in_threadpool(
                persist_skin_scan, session_frames, metrics, context
            )
        except Exception as exc:  # noqa: BLE001 - report failure to the client
            await _safe_send_json(
                websocket,
                {
                    "type": "skin_scan_error",
                    "success": False,
                    "detail": f"Skin scan analysis failed: {exc}",
                    "reason": reason,
                },
            )
            return

        frame_ids = [frame.get("frame_id") for frame in session_frames if frame.get("frame_id")]
        await _safe_send_json(
            websocket,
            {
                "type": "skin_scan_result",
                "success": True,
                "session": True,
                "reason": reason,
                "frame_count": frame_count,
                "frame_ids": frame_ids,
                "content_type": session_frames[-1].get("content_type"),
                "id": scan_response.id,
                "user_id": scan_response.user_id,
                "image_path": scan_response.image_path,
                "created_at": scan_response.created_at,
                "updated_at": scan_response.updated_at,
                "metrics": metrics.model_dump(),
                "scan": scan_response.model_dump(),
                "todays_recommendations": recommendations.model_dump(),
            },
        )

    async def capture_countdown() -> None:
        try:
            await asyncio.sleep(SKIN_SCAN_CAPTURE_WINDOW_SECONDS)
        except asyncio.CancelledError:
            return
        await run_finalize("capture_window_elapsed")

    try:
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

                if _is_finalize_message(message):
                    if capture_timer is not None:
                        capture_timer.cancel()
                    await run_finalize("client_finalize")
                    break

                if finalized:
                    # Capture already ended (timer fired); ignore late frames.
                    continue

                image_bytes, content_type, frame_id, source_path = _extract_live_image_message(message)
                session_frames.append(
                    {
                        "image_bytes": image_bytes,
                        "content_type": content_type,
                        "frame_id": frame_id,
                        "source_path": source_path,
                    }
                )

                # Start the capture window on the first accepted frame.
                if capture_timer is None:
                    capture_timer = asyncio.create_task(capture_countdown())

                await websocket.send_json(
                    {
                        "type": "frame_received",
                        "success": True,
                        "frame_id": frame_id,
                        "frame_count": len(session_frames),
                        "content_type": content_type,
                        "capture_window_seconds": SKIN_SCAN_CAPTURE_WINDOW_SECONDS,
                        "message": "Frame stored. Keep streaming; analysis runs automatically when capture ends.",
                    }
                )
            except WebSocketDisconnect:
                break
            except Exception as exc:  # noqa: BLE001 - surface frame errors to the client
                await _safe_send_json(
                    websocket,
                    {
                        "type": "skin_scan_error",
                        "success": False,
                        "detail": str(exc),
                    },
                )

        # Client disconnected or stopped sending: analyze whatever we captured.
        if capture_timer is not None:
            capture_timer.cancel()
        await run_finalize("client_disconnect")
    finally:
        if capture_timer is not None:
            capture_timer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await capture_timer


async def _safe_send_json(websocket: WebSocket, payload: dict[str, Any]) -> None:
    """Send JSON, swallowing errors if the socket has already closed."""
    with contextlib.suppress(Exception):
        await websocket.send_json(payload)


async def _read_optional_json_payload(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" not in content_type:
        return {}

    try:
        payload = await request.json()
    except Exception:
        return {}

    return payload if isinstance(payload, dict) else {}


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


def _is_finalize_message(message: dict[str, Any]) -> bool:
    text = message.get("text")
    if not isinstance(text, str):
        return False

    cleaned = text.strip()
    if cleaned.lower() in {"finalize", "end_scan", "end-scan", "done"}:
        return True

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return False

    if not isinstance(payload, dict):
        return False

    msg_type = str(payload.get("type") or payload.get("action") or "").lower()
    return msg_type in {"finalize", "end_scan", "end-scan", "done"}


def _extract_live_image_message(message: dict[str, Any]) -> tuple[bytes, str, str | None, str]:
    binary = message.get("bytes")
    if binary:
        return binary, _detect_image_content_type(binary, "image/jpeg"), None, "websocket-binary"

    text = message.get("text")
    if not text:
        raise ValueError("Send image bytes or a JSON/base64 image payload")

    payload = _parse_text_payload(text)
    if isinstance(payload, dict):
        content_type = str(payload.get("content_type") or payload.get("mime_type") or "image/jpeg")
        frame_id = _optional_str(payload.get("frame_id") or payload.get("id"))
        image_url = _image_url_from_payload(payload)
        if image_url:
            image_bytes, fetched_content_type = fetch_skin_scan_image_from_url(image_url)
            return image_bytes, fetched_content_type, frame_id, image_url

        image_value = (
            payload.get("image_base64")
            or payload.get("image")
            or payload.get("frame")
            or payload.get("data")
        )
        if not isinstance(image_value, str):
            raise ValueError("JSON payload must include image_url, image_base64, image, frame, or data")
        image_bytes, detected_content_type, _ = _decode_base64_image(image_value, content_type, frame_id)
        return image_bytes, detected_content_type, frame_id, frame_id or "websocket-base64"

    image_bytes, detected_content_type, _ = _decode_base64_image(str(payload), "image/jpeg", None)
    return image_bytes, detected_content_type, None, "websocket-base64"

def _image_url_from_payload(payload: dict[str, Any]) -> str | None:
    for key in ("image_url", "image_path", "url"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    image_value = payload.get("image")
    if isinstance(image_value, str) and image_value.strip().startswith(("http://", "https://", "/storage/")):
        return image_value.strip()

    return None


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
    return (
        image_bytes.startswith(b"\xff\xd8\xff")
        or image_bytes.startswith(b"\x89PNG")
        or (image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP")
        or image_bytes.startswith(b"GIF")
    )


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
