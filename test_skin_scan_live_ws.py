import base64
import json
import mimetypes
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from main import app


DEFAULT_WS_PATH = "/api/skin-scan/live"
DEFAULT_FRAME_COUNT = 5


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python test_skin_scan_live_ws.py path/to/demo-image.jpg [frame_count] [--finalize]")
        raise SystemExit(1)

    image_path = Path(sys.argv[1])
    if not image_path.exists():
        print(f"Image not found: {image_path}")
        raise SystemExit(1)

    send_finalize = "--finalize" in sys.argv[2:]
    frame_count = DEFAULT_FRAME_COUNT
    for arg in sys.argv[2:]:
        if arg.isdigit():
            frame_count = int(arg)
            break

    content_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    image_base64 = base64.b64encode(image_path.read_bytes()).decode("ascii")

    with TestClient(app).websocket_connect(DEFAULT_WS_PATH) as websocket:
        ready = websocket.receive_json()
        print("READY:")
        print(json.dumps(ready, indent=2))

        # Stream several frames to simulate a live camera session.
        for index in range(1, frame_count + 1):
            websocket.send_json(
                {
                    "frame_id": f"{image_path.stem}-{index}",
                    "content_type": content_type,
                    "image_base64": image_base64,
                }
            )
            ack = websocket.receive_json()
            print(f"\nFRAME {index} ACK:")
            print(json.dumps(ack, indent=2))

        # Optionally stop early; otherwise the server auto-stops after its
        # capture window and analyzes all frames together.
        if send_finalize:
            print("\nSending finalize to stop early...")
            websocket.send_json({"type": "finalize"})
        else:
            print("\nWaiting for server capture window to elapse (auto-stop)...")

        # Drain messages until the final scan result (or an error) arrives.
        while True:
            message = websocket.receive_json()
            msg_type = message.get("type")
            print(f"\n{str(msg_type).upper()}:")
            print(json.dumps(message, indent=2))
            if msg_type in {"skin_scan_result", "skin_scan_error"}:
                break


if __name__ == "__main__":
    main()