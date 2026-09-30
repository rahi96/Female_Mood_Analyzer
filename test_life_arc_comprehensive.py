#!/usr/bin/env python3
"""
COMPREHENSIVE LIFE-ARC ENDPOINT TEST SUITE
============================================
GET /api/v1/lifelong-thriving/life-arc

Covers:
- Invalid/malformed input (validation failures -> 422)
- Nonexistent / ineligible users (empty milestones)
- Response schema & type validation (Milestone, TimelineSummary)
- Business logic invariants (date ordering, significance filtering, counts)
- All 9 milestone types (cycle_start, phase_transition, health_achievement,
  symptom_resolution, cycle_anomaly, health_goal, lab_result, life_stage,
  health_insight)
- Query parameter edge cases (include_ai_insights variants)
- Performance / timeout / concurrency
- HTTP method / content-type misuse
"""

import requests
import json
import time
import statistics
import concurrent.futures
from datetime import datetime, date
from typing import Dict, List, Any, Optional

# ============================================================================
# CONFIGURATION
# ============================================================================

API_BASE_URL = "http://localhost:8002"
LIFE_ARC_ENDPOINT = f"{API_BASE_URL}/api/v1/lifelong-thriving/life-arc"
TIMEOUT = 15

# Adjust these to real users in your DB before running
VALID_ELIGIBLE_USERS = [1, 2, 4, 6, 9]          # Have >=1 menstrual cycle
LIKELY_INELIGIBLE_USERS = [999998]              # Exists but no cycle data
NONEXISTENT_USERS = [999999999]                 # Does not exist at all

INVALID_USER_IDS = [
    -1,            # negative
    0,             # zero (gt=0 constraint violated)
    -999999,       # large negative
    2147483648,    # over int32 (may or may not be rejected depending on DB col type)
]

MALFORMED_USER_IDS = [
    "abc",         # non-numeric
    "1.5",         # float string
    "1e5",         # scientific notation
    "",            # empty
    "null",
    "1;DROP TABLE users;--",  # SQL injection attempt
    "<script>alert(1)</script>",  # XSS attempt
    "1 OR 1=1",
]

VALID_MILESTONE_TYPES = {
    "cycle_start", "phase_transition", "health_achievement",
    "symptom_resolution", "cycle_anomaly", "health_goal",
    "lab_result", "life_stage", "health_insight",
}

REQUIRED_MILESTONE_FIELDS = ["date", "type", "title", "description", "significance", "icon"]


# ============================================================================
# RESULT TRACKING
# ============================================================================

class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.errors: List[tuple] = []
        self.response_times: List[float] = []
        self.status_codes: Dict[int, int] = {}

    def add_pass(self, name: str, details: str = ""):
        self.passed += 1
        print(f"[PASS] {name}" + (f" - {details}" if details else ""))

    def add_fail(self, name: str, reason: str):
        self.failed += 1
        self.errors.append((name, reason))
        print(f"[FAIL] {name} - {reason}")

    def add_warning(self, name: str, message: str):
        self.warnings += 1
        print(f"[WARN] {name} - {message}")

    def track(self, code: int, elapsed_ms: float):
        self.status_codes[code] = self.status_codes.get(code, 0) + 1
        self.response_times.append(elapsed_ms)

    def print_summary(self):
        total = self.passed + self.failed + self.warnings
        rate = (self.passed / total * 100) if total else 0
        print("\n" + "=" * 80)
        print("TEST EXECUTION SUMMARY")
        print("=" * 80)
        print(f"Total Tests:  {total}")
        print(f"Passed:       {self.passed}")
        print(f"Failed:       {self.failed}")
        print(f"Warnings:     {self.warnings}")
        print(f"Pass Rate:    {rate:.1f}%")
        if self.response_times:
            print(f"\nResponse Times (ms): avg={statistics.mean(self.response_times):.1f} "
                  f"min={min(self.response_times):.1f} max={max(self.response_times):.1f}")
        if self.status_codes:
            print("\nStatus Codes:")
            for code in sorted(self.status_codes):
                print(f"  {code}: {self.status_codes[code]}")
        if self.errors:
            print(f"\nFailures ({len(self.errors)}):")
            for name, reason in self.errors:
                print(f"  - {name}: {reason}")
        print("=" * 80)


def call_endpoint(params: Dict[str, Any] = None, raw_url: str = None,
                   method: str = "GET", timeout: float = TIMEOUT) -> tuple:
    """Returns (status_code, json_or_none, elapsed_ms, raw_text, error)."""
    start = time.time()
    try:
        if raw_url:
            resp = requests.request(method, raw_url, timeout=timeout)
        else:
            resp = requests.request(method, LIFE_ARC_ENDPOINT, params=params, timeout=timeout)
        elapsed = (time.time() - start) * 1000
        try:
            body = resp.json()
        except ValueError:
            body = None
        return resp.status_code, body, elapsed, resp.text, None
    except requests.exceptions.Timeout:
        return None, None, (time.time() - start) * 1000, None, "TIMEOUT"
    except requests.exceptions.ConnectionError as e:
        return None, None, (time.time() - start) * 1000, None, f"CONNECTION_ERROR: {e}"
    except Exception as e:
        return None, None, (time.time() - start) * 1000, None, f"UNKNOWN_ERROR: {e}"


# ============================================================================
# TEST SUITE 1: INPUT VALIDATION FAILURES
# ============================================================================

def test_missing_user_id(r: TestResults):
    print("\n--- SUITE: Missing required user_id ---")
    code, body, elapsed, text, err = call_endpoint(params={})
    r.track(code or 0, elapsed)
    if code == 422:
        r.add_pass("Missing user_id returns 422", f"body={body}")
    else:
        r.add_fail("Missing user_id should return 422", f"Got {code}: {text}")


def test_invalid_user_ids(r: TestResults):
    print("\n--- SUITE: Invalid user_id values (schema gt=0) ---")
    for uid in INVALID_USER_IDS:
        code, body, elapsed, text, err = call_endpoint(params={"user_id": uid})
        r.track(code or 0, elapsed)
        if code == 422:
            r.add_pass(f"user_id={uid} rejected with 422")
        elif code == 200:
            r.add_fail(f"user_id={uid} should be rejected", f"Got 200: {body}")
        else:
            r.add_warning(f"user_id={uid} unexpected status", f"Got {code}: {text[:200] if text else err}")


def test_malformed_user_ids(r: TestResults):
    print("\n--- SUITE: Malformed / injection user_id values ---")
    for uid in MALFORMED_USER_IDS:
        code, body, elapsed, text, err = call_endpoint(params={"user_id": uid})
        r.track(code or 0, elapsed)
        if code == 422:
            r.add_pass(f"user_id={uid!r} rejected with 422")
        elif code == 500:
            r.add_fail(f"user_id={uid!r} caused 500 (injection/crash risk)", f"body={text[:300] if text else err}")
        elif code == 200:
            r.add_fail(f"user_id={uid!r} unexpectedly accepted", f"body={body}")
        else:
            r.add_warning(f"user_id={uid!r} unexpected status", f"Got {code}")


def test_include_ai_insights_variants(r: TestResults):
    print("\n--- SUITE: include_ai_insights query param edge cases ---")
    user_id = VALID_ELIGIBLE_USERS[0]
    variants = ["true", "false", "1", "0", "yes", "TRUE", "invalid_bool", ""]
    for v in variants:
        code, body, elapsed, text, err = call_endpoint(params={"user_id": user_id, "include_ai_insights": v})
        r.track(code or 0, elapsed)
        if v in ("true", "false", "1", "0", "TRUE"):
            if code == 200:
                r.add_pass(f"include_ai_insights={v!r} accepted")
            else:
                r.add_fail(f"include_ai_insights={v!r} should be accepted", f"Got {code}")
        elif v in ("yes", "invalid_bool", ""):
            if code in (200, 422):
                r.add_pass(f"include_ai_insights={v!r} handled gracefully", f"Got {code}")
            else:
                r.add_fail(f"include_ai_insights={v!r} caused unexpected error", f"Got {code}: {text[:200] if text else err}")


def test_extra_unknown_params(r: TestResults):
    print("\n--- SUITE: Unknown / extra query params ---")
    code, body, elapsed, text, err = call_endpoint(
        params={"user_id": VALID_ELIGIBLE_USERS[0], "foo": "bar", "months_back": 999}
    )
    r.track(code or 0, elapsed)
    if code == 200:
        r.add_pass("Extra unknown params ignored gracefully")
    else:
        r.add_fail("Extra unknown params should not break request", f"Got {code}: {text[:200] if text else err}")


# ============================================================================
# TEST SUITE 2: NONEXISTENT / INELIGIBLE USERS
# ============================================================================

def test_nonexistent_user(r: TestResults):
    print("\n--- SUITE: Nonexistent user_id ---")
    for uid in NONEXISTENT_USERS:
        code, body, elapsed, text, err = call_endpoint(params={"user_id": uid})
        r.track(code or 0, elapsed)
        if code == 200 and body:
            if body.get("milestones") == [] and body.get("timeline_summary", {}).get("total_milestones") == 0:
                r.add_pass(f"Nonexistent user_id={uid} returns empty milestones (no crash)")
            else:
                r.add_fail(f"Nonexistent user_id={uid} should return empty milestones",
                           f"Got: {json.dumps(body)[:300]}")
        elif code == 404:
            r.add_pass(f"Nonexistent user_id={uid} returns 404")
        else:
            r.add_fail(f"Nonexistent user_id={uid} unexpected behavior", f"Got {code}: {text[:300] if text else err}")


def test_ineligible_user(r: TestResults):
    print("\n--- SUITE: Ineligible user (no menstrual cycle data) ---")
    for uid in LIKELY_INELIGIBLE_USERS:
        code, body, elapsed, text, err = call_endpoint(params={"user_id": uid})
        r.track(code or 0, elapsed)
        if code == 200 and body:
            milestones = body.get("milestones", [])
            summary = body.get("timeline_summary", {})
            if milestones == [] and summary.get("total_milestones") == 0:
                r.add_pass(f"Ineligible user_id={uid} returns empty milestones")
            else:
                r.add_warning(f"user_id={uid} had data (may actually be eligible)",
                              f"{len(milestones)} milestones found")
        else:
            r.add_fail(f"Ineligible user_id={uid} request failed", f"Got {code}: {text[:200] if text else err}")


# ============================================================================
# TEST SUITE 3: RESPONSE SCHEMA VALIDATION
# ============================================================================

def test_response_schema(r: TestResults, user_id: int):
    print(f"\n--- SUITE: Response schema validation (User {user_id}) ---")
    code, body, elapsed, text, err = call_endpoint(params={"user_id": user_id})
    r.track(code or 0, elapsed)

    if code != 200 or body is None:
        r.add_fail(f"Schema test setup failed for user {user_id}", f"Got {code}: {err}")
        return None

    # Top-level fields
    for field in ["milestones", "timeline_summary"]:
        if field in body:
            r.add_pass(f"Top-level field '{field}' present")
        else:
            r.add_fail(f"Top-level field '{field}' missing", f"user_id={user_id}")

    # Reject legacy/incorrect field names
    for legacy_field in ["milestone_date", "milestone_type", "eligibility_status", "last_updated"]:
        if legacy_field in body:
            r.add_fail(f"Unexpected legacy field '{legacy_field}' present", "Schema drift detected")
        else:
            r.add_pass(f"Legacy field '{legacy_field}' correctly absent")

    milestones = body.get("milestones", [])
    if isinstance(milestones, list):
        r.add_pass("milestones is a list", f"count={len(milestones)}")
    else:
        r.add_fail("milestones is not a list", f"type={type(milestones)}")
        return body

    for i, m in enumerate(milestones):
        for field in REQUIRED_MILESTONE_FIELDS:
            if field not in m:
                r.add_fail(f"Milestone[{i}] missing field '{field}'", f"milestone={m}")

        # Explicitly verify correct external field names (not date_/type_)
        if "date_" in m or "type_" in m:
            r.add_fail(f"Milestone[{i}] leaking internal field name (date_/type_)", f"keys={list(m.keys())}")

        mtype = m.get("type")
        if mtype not in VALID_MILESTONE_TYPES:
            r.add_fail(f"Milestone[{i}] has invalid type", f"Got '{mtype}'")

        sig = m.get("significance")
        if not isinstance(sig, (int, float)) or not (0 <= sig <= 1):
            r.add_fail(f"Milestone[{i}] significance out of range", f"Got {sig}")
        elif sig < 0.3:
            r.add_fail(f"Milestone[{i}] significance below filter threshold (0.3)", f"Got {sig} (should've been filtered)")

        try:
            datetime.strptime(m.get("date", ""), "%Y-%m-%d")
        except (ValueError, TypeError):
            r.add_fail(f"Milestone[{i}] date not in YYYY-MM-DD format", f"Got '{m.get('date')}'")

        if not isinstance(m.get("title"), str) or not m.get("title"):
            r.add_fail(f"Milestone[{i}] title invalid", f"Got {m.get('title')!r}")

        if not isinstance(m.get("icon"), str) or not m.get("icon"):
            r.add_fail(f"Milestone[{i}] icon invalid", f"Got {m.get('icon')!r}")

        hc = m.get("health_context")
        if hc is not None and not isinstance(hc, dict):
            r.add_fail(f"Milestone[{i}] health_context wrong type", f"Got {type(hc)}")

    # timeline_summary validation
    summary = body.get("timeline_summary", {})
    for field in ["total_milestones", "major_events", "avg_monthly_milestones", "date_range"]:
        if field not in summary:
            r.add_fail(f"timeline_summary missing '{field}'", f"summary={summary}")

    if summary.get("total_milestones") != len(milestones):
        r.add_fail("timeline_summary.total_milestones mismatch",
                   f"summary says {summary.get('total_milestones')}, actual list has {len(milestones)}")
    else:
        r.add_pass("timeline_summary.total_milestones matches milestones array length")

    major_expected = sum(1 for m in milestones if m.get("significance", 0) >= 0.7)
    if summary.get("major_events") == major_expected:
        r.add_pass("timeline_summary.major_events count correct")
    else:
        r.add_fail("timeline_summary.major_events count incorrect",
                   f"Expected {major_expected}, got {summary.get('major_events')}")

    date_range = summary.get("date_range", {})
    if "start" in date_range and "end" in date_range:
        r.add_pass("date_range has start/end")
        try:
            start_d = datetime.strptime(date_range["start"], "%Y-%m-%d").date()
            end_d = datetime.strptime(date_range["end"], "%Y-%m-%d").date()
            if start_d <= end_d:
                r.add_pass("date_range.start <= date_range.end")
            else:
                r.add_fail("date_range.start > date_range.end", f"{date_range}")
        except (ValueError, TypeError):
            r.add_fail("date_range values not valid dates", f"{date_range}")
    else:
        r.add_fail("date_range missing start/end", f"{date_range}")

    return body


# ============================================================================
# TEST SUITE 4: BUSINESS LOGIC / ORDERING
# ============================================================================

def test_chronological_ordering(r: TestResults, body: Optional[Dict]):
    print("\n--- SUITE: Chronological ordering (reverse chronological) ---")
    if not body:
        r.add_warning("Ordering test skipped", "no body available")
        return
    milestones = body.get("milestones", [])
    if len(milestones) < 2:
        r.add_warning("Ordering test skipped", "fewer than 2 milestones")
        return
    dates = [datetime.strptime(m["date"], "%Y-%m-%d").date() for m in milestones]
    is_descending = all(dates[i] >= dates[i + 1] for i in range(len(dates) - 1))
    if is_descending:
        r.add_pass("Milestones sorted reverse-chronologically (newest first)")
    else:
        r.add_fail("Milestones NOT sorted correctly", f"dates={dates}")


def test_significance_filter(r: TestResults, body: Optional[Dict]):
    print("\n--- SUITE: Significance filter (>= 0.3 only) ---")
    if not body:
        r.add_warning("Significance filter test skipped", "no body available")
        return
    milestones = body.get("milestones", [])
    low_sig = [m for m in milestones if m.get("significance", 1) < 0.3]
    if not low_sig:
        r.add_pass("No milestones below 0.3 significance threshold")
    else:
        r.add_fail("Found milestones below significance threshold", f"{low_sig}")


def test_milestone_type_coverage(r: TestResults, all_bodies: List[Dict]):
    print("\n--- SUITE: Milestone type coverage across sampled users ---")
    found_types = set()
    for body in all_bodies:
        if not body:
            continue
        for m in body.get("milestones", []):
            found_types.add(m.get("type"))

    for expected in VALID_MILESTONE_TYPES:
        if expected in found_types:
            r.add_pass(f"Milestone type '{expected}' observed")
        else:
            r.add_warning(f"Milestone type '{expected}' NOT observed in sample",
                          "May be correct if no users have that data")

    unexpected = found_types - VALID_MILESTONE_TYPES
    if unexpected:
        r.add_fail("Unexpected milestone type(s) found", f"{unexpected}")


# ============================================================================
# TEST SUITE 5: HTTP METHOD / TRANSPORT MISUSE
# ============================================================================

def test_wrong_http_methods(r: TestResults):
    print("\n--- SUITE: Wrong HTTP methods ---")
    user_id = VALID_ELIGIBLE_USERS[0]
    for method in ["POST", "PUT", "DELETE", "PATCH"]:
        code, body, elapsed, text, err = call_endpoint(params={"user_id": user_id}, method=method)
        r.track(code or 0, elapsed)
        if code == 405:
            r.add_pass(f"{method} correctly rejected with 405")
        else:
            r.add_fail(f"{method} should return 405", f"Got {code}")


def test_trailing_slash_and_case(r: TestResults):
    print("\n--- SUITE: URL variations (trailing slash / case sensitivity) ---")
    user_id = VALID_ELIGIBLE_USERS[0]
    variations = [
        f"{LIFE_ARC_ENDPOINT}/?user_id={user_id}",
        f"{API_BASE_URL}/api/v1/lifelong-thriving/Life-Arc?user_id={user_id}",
        f"{API_BASE_URL}/api/v1/lifelong-thriving/life-arc/?user_id={user_id}",
    ]
    for url in variations:
        code, body, elapsed, text, err = call_endpoint(raw_url=url)
        r.track(code or 0, elapsed)
        if code in (200, 404, 307, 308):
            r.add_pass(f"URL variant handled predictably: {url}", f"Got {code}")
        else:
            r.add_warning(f"URL variant unexpected status: {url}", f"Got {code}")


# ============================================================================
# TEST SUITE 6: PERFORMANCE / CONCURRENCY / TIMEOUT
# ============================================================================

def test_response_time(r: TestResults):
    print("\n--- SUITE: Response time (single request) ---")
    user_id = VALID_ELIGIBLE_USERS[0]
    code, body, elapsed, text, err = call_endpoint(params={"user_id": user_id})
    r.track(code or 0, elapsed)
    if code == 200:
        if elapsed < 5000:
            r.add_pass(f"Response time acceptable", f"{elapsed:.0f}ms")
        else:
            r.add_warning(f"Response time slow", f"{elapsed:.0f}ms")
    else:
        r.add_fail("Response time test setup failed", f"Got {code}")


def test_concurrent_requests(r: TestResults):
    print("\n--- SUITE: Concurrent requests (race conditions / connection pool) ---")
    user_id = VALID_ELIGIBLE_USERS[0]

    def worker():
        return call_endpoint(params={"user_id": user_id})

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(worker) for _ in range(10)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    success_count = sum(1 for code, *_ in results if code == 200)
    for code, body, elapsed, text, err in results:
        r.track(code or 0, elapsed)

    if success_count == 10:
        r.add_pass("All 10 concurrent requests succeeded")
    else:
        r.add_fail("Some concurrent requests failed", f"{success_count}/10 succeeded")


def test_very_short_timeout(r: TestResults):
    print("\n--- SUITE: Client-side short timeout handling ---")
    user_id = VALID_ELIGIBLE_USERS[0]
    code, body, elapsed, text, err = call_endpoint(params={"user_id": user_id}, timeout=0.001)
    if err == "TIMEOUT":
        r.add_pass("Short client timeout raises TIMEOUT as expected (client-side, not a server bug)")
    else:
        r.add_warning("Short timeout didn't trigger (server responded very fast)", f"Got {code} in {elapsed:.2f}ms")


# ============================================================================
# TEST SUITE 7: IDEMPOTENCY / CONSISTENCY
# ============================================================================

def test_idempotency(r: TestResults):
    print("\n--- SUITE: Idempotency (repeated calls return consistent data) ---")
    user_id = VALID_ELIGIBLE_USERS[0]
    code1, body1, _, _, _ = call_endpoint(params={"user_id": user_id})
    time.sleep(0.5)
    code2, body2, _, _, _ = call_endpoint(params={"user_id": user_id})

    if code1 == 200 and code2 == 200:
        m1 = body1.get("milestones", [])
        m2 = body2.get("milestones", [])
        if len(m1) == len(m2):
            r.add_pass("Repeated calls return same milestone count", f"count={len(m1)}")
        else:
            r.add_fail("Repeated calls returned different milestone counts",
                       f"first={len(m1)}, second={len(m2)}")
    else:
        r.add_fail("Idempotency test setup failed", f"codes={code1},{code2}")


# ============================================================================
# MAIN RUNNER
# ============================================================================

def main():
    print("=" * 80)
    print("LIFE-ARC ENDPOINT COMPREHENSIVE FAILURE TEST SUITE")
    print(f"Target: {LIFE_ARC_ENDPOINT}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 80)

    r = TestResults()

    # Suite 1: Input validation
    test_missing_user_id(r)
    test_invalid_user_ids(r)
    test_malformed_user_ids(r)
    test_include_ai_insights_variants(r)
    test_extra_unknown_params(r)

    # Suite 2: Nonexistent / ineligible
    test_nonexistent_user(r)
    test_ineligible_user(r)

    # Suite 3 + 4: Schema & business logic (run against multiple valid users)
    bodies = []
    for uid in VALID_ELIGIBLE_USERS:
        body = test_response_schema(r, uid)
        bodies.append(body)
        test_chronological_ordering(r, body)
        test_significance_filter(r, body)

    test_milestone_type_coverage(r, bodies)

    # Suite 5: Transport misuse
    test_wrong_http_methods(r)
    test_trailing_slash_and_case(r)

    # Suite 6: Performance
    test_response_time(r)
    test_concurrent_requests(r)
    test_very_short_timeout(r)

    # Suite 7: Idempotency
    test_idempotency(r)

    r.print_summary()
    return 0 if r.failed == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
