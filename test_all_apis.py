import json
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

USER_ID = "283e9f9d-29a0-418e-af2d-4f2628e9064d"

def run_tests():
    print("--- Testing /health ---")
    response = client.get("/health")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}\n")

    print(f"--- Testing GET /api/backend-data/{USER_ID} ---")
    response = client.get(f"/api/backend-data/{USER_ID}")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text[:200]}...\n")

    endpoints = [
        ("/api/cycle-insights", {"user_id": USER_ID}),
        ("/api/daily-tip", {"user_id": USER_ID}),
        ("/api/daily-verse", {"user_id": USER_ID}),
        ("/api/cycle-movement/follicular", {"user_id": USER_ID}),
        ("/api/cycle-movement/ovulation", {"user_id": USER_ID}),
        ("/api/cycle-movement/luteal", {"user_id": USER_ID}),
        ("/api/cycle-movement/menstrual", {"user_id": USER_ID}),
    ]

    for endpoint, payload in endpoints:
        print(f"--- Testing POST {endpoint} ---")
        response = client.post(endpoint, json=payload)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            print(f"Response: {json.dumps(response.json(), indent=2)[:300]}...\n")
        else:
            print(f"Response: {response.text}\n")

    print("--- Testing POST /api/chat/response ---")
    chat_payload = {
        "user_id": USER_ID,
        "message": "Hello, how can I improve my health?",
        "session_id": "test-session-123"
    }
    response = client.post("/api/chat/response", json=chat_payload)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text[:300]}...\n")

if __name__ == "__main__":
    run_tests()
