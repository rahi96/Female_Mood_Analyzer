#!/usr/bin/env python3
"""
LIVE API INTEGRATION TEST - /api/v1/menopause/dashboard

Tests the REAL running server (not pure functions in isolation). This answers
the actual product question: "when a brand-new user enters the system, what
does she see, and does the system behave safely?"

Covers:
- Brand-new user (never seen before, zero rows anywhere) -> must not crash,
  must return an honest "no data yet" response, never a fake stage.
- Existing low-data user (1-2 health_logs, incomplete cycle) -> must show
  "insufficient_data", not a fabricated "perimenopause" claim.
- Invalid/malformed input -> must be rejected with 422, not 500.
- Response schema -> every field the UI depends on must be present and
  correctly typed for all three period windows (7d/30d/90d).
- clinical_export must not silently be null for valid users (regression test
  for the Pydantic ge=1 vasomotor_avg_severity crash we fixed).

Run against a running server: python test_perimenopause_live_api.py
Requires: pip install requests
"""

import sys
import time
import requests
from datetime import datetime

API_BASE_URL = "http://localhost:8002"
ENDPOINT = f"{API_BASE_URL}/api/v1/menopause/dashboard"
# This endpoint makes 3+ sequential DB round-trips per request (summary,
# insights, clinical export) against a remote RDS instance, so 15s can be
# too tight under cold-connection latency. 30s matches what succeeds in
# practice without masking a real regression.
TIMEOUT = 30

# A user_id that should not exist in the database at all - simulates a brand
# new signup with zero rows in users/profiles/health_logs/menstrual_cycles.
BRAND_NEW_USER_ID = 999999999

# Known low-data user from earlier investigation: 2 health_logs rows,
# 1 incomplete menstrual_cycles row -> should report "insufficient_data".
LOW_DATA_USER_ID = 9

PASS = 0
FAIL = 0
WARN = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name}" + (f" - {detail}" if detail else ""))


def warn(name: str, detail: str = ""):
    global WARN
    WARN += 1
    print(f"[WARN] {name}" + (f" - {detail}" if detail else ""))


def call(user_id, period="30d", timeout=TIMEOUT):
    """Returns (status_code, json_body_or_none, raw_text, error)."""
    try:
        resp = requests.get(ENDPOINT, params={"user_id": user_id, "period": period}, timeout=timeout)
        try:
            return resp.status_code, resp.json(), resp.text, None
        except ValueError:
            return resp.status_code, None, resp.text, None
    except requests.exceptions.ConnectionError as e:
        return None, None, None, f"CONNECTION_ERROR: {e}"
    except requests.exceptions.Timeout:
        return None, None, None, "TIMEOUT"


# ============================================================================
# 0. Server reachability check
# ============================================================================

print("=" * 80)
print("PERIMENOPAUSE DASHBOARD - LIVE API INTEGRATION TEST")
print(f"Target: {ENDPOINT}")
print(f"Timestamp: {datetime.now().isoformat()}")
print("=" * 80)

try:
    requests.get(f"{API_BASE_URL}/docs", timeout=5)
except requests.exceptions.ConnectionError:
    print("\n[FATAL] Server is not reachable at", API_BASE_URL)
    print("Start the container first: docker-compose up -d")
    sys.exit(2)


# ============================================================================
# 1. BRAND NEW USER - the actual "new user enters the system" scenario
# ============================================================================

print("\n--- SUITE: Brand-new user (user_id has zero rows anywhere) ---")
code, body, text, err = call(BRAND_NEW_USER_ID)

check(f"Request does not crash the server (no 500)", code != 500, f"Got {code}: {text[:300] if text else err}")
check(f"Request returns 200 (graceful empty state, not an error)", code == 200, f"Got {code}")

if body:
    stage = body.get("transition_stage_tracker", {}).get("menopause_stage")
    check(
        "New user does NOT get a fabricated 'perimenopause' stage",
        stage != "perimenopause",
        f"Got stage='{stage}' - this would be the exact bug we fixed if it reappears",
    )
    check(
        "New user gets an honest 'unknown' or 'insufficient_data' stage",
        stage in ("unknown", "insufficient_data"),
        f"Got stage='{stage}'",
    )
    check(
        "vasomotor_tracker.events is an empty list, not missing/null",
        body.get("vasomotor_tracker", {}).get("events") == [],
    )
    check(
        "gsm_health has all 4 fields, all 'not_reported'",
        all(
            body.get("gsm_health", {}).get(f, {}).get("level") == "not_reported"
            for f in ("vaginal_dryness", "urinary_frequency", "pelvic_discomfort", "libido_impact")
        ),
        str(body.get("gsm_health")),
    )
    check(
        "symptom_matrix.entries is empty for a user with no logs",
        body.get("symptom_matrix", {}).get("entries") == [],
    )


# ============================================================================
# 2. KNOWN LOW-DATA USER (regression test for insufficient_data fix)
# ============================================================================

print(f"\n--- SUITE: Known low-data user (user_id={LOW_DATA_USER_ID}) ---")
code, body, text, err = call(LOW_DATA_USER_ID, period="90d")

check("Request returns 200", code == 200, f"Got {code}: {text[:300] if text else err}")

if body:
    stage = body.get("transition_stage_tracker", {}).get("menopause_stage")
    check(
        f"User {LOW_DATA_USER_ID} (1 incomplete cycle) reports 'insufficient_data', not fake 'perimenopause'",
        stage == "insufficient_data",
        f"Got stage='{stage}'",
    )
    check(
        "is_in_perimenopause is False when stage is insufficient_data",
        body.get("transition_stage_tracker", {}).get("is_in_perimenopause") is False,
    )

    # Regression test: clinical_export used to silently become null due to a
    # Pydantic ge=1 constraint crashing on vasomotor_avg_severity=0.
    check(
        "clinical_export is NOT null (regression test for the ge=1 severity crash)",
        body.get("clinical_export") is not None,
        "clinical_export came back null - the Pydantic validation bug may have regressed",
    )
    if body.get("clinical_export"):
        ce = body["clinical_export"]
        check("clinical_export.vasomotor_avg_severity is present and >= 0", ce.get("vasomotor_avg_severity", -1) >= 0)
        check(
            "clinical_export.primary_symptoms has no raw emoji leaking through",
            not any("🙂" in s or "😊" in s or "🙁" in s for s in ce.get("primary_symptoms", [])),
            str(ce.get("primary_symptoms")),
        )
        for bullet in ce.get("clinical_recommendations", []):
            if len(bullet.strip()) < 15:
                warn(
                    "clinical_recommendations contains a suspiciously short/truncated bullet",
                    repr(bullet),
                )


# ============================================================================
# 3. INPUT VALIDATION - malformed/invalid requests must not 500
# ============================================================================

print("\n--- SUITE: Input validation ---")

for bad_period in ["invalid", "365d", "", "7D"]:
    code, body, text, err = call(LOW_DATA_USER_ID, period=bad_period)
    check(f"period='{bad_period}' rejected with 422 (not 500)", code == 422, f"Got {code}")

for bad_user in [-1, 0, "abc"]:
    code, body, text, err = call(bad_user)
    check(f"user_id={bad_user!r} rejected with 422 (not 500)", code == 422, f"Got {code}")


# ============================================================================
# 4. SCHEMA CONSISTENCY ACROSS ALL PERIOD WINDOWS
# ============================================================================

print("\n--- SUITE: Response schema consistency across periods ---")
REQUIRED_TOP_LEVEL = {
    "transition_stage_tracker", "vasomotor_tracker", "gsm_health",
    "symptom_matrix", "clinical_export", "period_selected", "tabs",
}

for period in ["7d", "30d", "90d"]:
    code, body, text, err = call(LOW_DATA_USER_ID, period=period)
    if code == 200 and body:
        missing = REQUIRED_TOP_LEVEL - set(body.keys())
        check(f"period={period}: all required top-level fields present", not missing, f"Missing: {missing}")
        check(f"period={period}: period_selected matches request", body.get("period_selected") == period)
    else:
        check(f"period={period}: request succeeded", False, f"Got {code}")


# ============================================================================
# 5. CONCURRENT NEW-USER SIMULATION (multiple "first-time" requests at once)
# ============================================================================

print("\n--- SUITE: Concurrent new-user signups (race condition check) ---")
import concurrent.futures

fake_new_user_ids = [999999901, 999999902, 999999903, 999999904, 999999905]


def worker(uid):
    return call(uid)


with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
    results = list(pool.map(worker, fake_new_user_ids))

success_count = sum(1 for code, *_ in results if code == 200)
check(
    "All simulated new-user signups succeed concurrently without crashing",
    success_count == len(fake_new_user_ids),
    f"{success_count}/{len(fake_new_user_ids)} succeeded",
)


# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "=" * 80)
print("TEST EXECUTION SUMMARY")
print("=" * 80)
print(f"Passed:   {PASS}")
print(f"Failed:   {FAIL}")
print(f"Warnings: {WARN}")
print("=" * 80)

sys.exit(1 if FAIL > 0 else 0)
