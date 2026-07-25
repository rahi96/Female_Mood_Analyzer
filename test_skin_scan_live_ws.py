import base64
import json
import mimetypes
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from main import app


DEFAULT_WS_PATH = "/api/skin-scan/live"


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python test_skin_scan_live_ws.py path/to/demo-image.jpg")
        raise SystemExit(1)

    image_path = Path(sys.argv[1])
    if not image_path.exists():
        print(f"Image not found: {image_path}")
        raise SystemExit(1)

    content_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    image_base64 = base64.b64encode(image_path.read_bytes()).decode("ascii")

    payload = {
        "frame_id": image_path.stem,
        "content_type": content_type,
        "image_base64": image_base64,
    }

    with TestClient(app).websocket_connect(DEFAULT_WS_PATH) as websocket:
        ready = websocket.receive_json()
        print("READY:")
        print(json.dumps(ready, indent=2))

        websocket.send_json(payload)
        response = websocket.receive_json()
        print("\nSCAN RESPONSE:")
        print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()