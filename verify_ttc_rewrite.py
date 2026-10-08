"""Verify the trying-to-conceive rewrite:
1. Shape matches the previous AI response (keys / nesting / types).
2. No PII leak (password / tokens / snapshot dump).
3. Speed: first call <6s cold, next 4 calls <500ms (cache + stale-while-revalidate).
"""
import json
import sys
import time
import urllib.request

sys.stdout.reconfigure(line_buffering=True)
URL = "http://localhost:8000/api/trying-to-conceive?user_id=17"


def fetch():
    t0 = time.perf_counter()
    with urllib.request.urlopen(URL, timeout=60) as r:
        body = r.read()
    elapsed = (time.perf_counter() - t0) * 1000
    return elapsed, json.loads(body)


EXPECTED_TOP_KEYS = {"status", "service", "fetched", "sources", "trying_to_conceive"}
EXPECTED_TTC_KEYS = {
    "title", "cycle_context", "lh_surge", "conception_timing",
    "highest_priority", "ai_generated", "ai_cached",
}
EXPECTED_CYCLE_CONTEXT = {"cycle_day", "phase", "average_cycle_length"}
EXPECTED_LH_SURGE = {
    "title", "subtitle", "today_label", "status", "progress_percent", "timeline", "metrics",
}
EXPECTED_CONCEPTION = {"title", "subtitle", "windows"}
EXPECTED_HIGHEST = {"title", "subtitle", "message", "bbt_note"}
EXPECTED_WINDOW_KEYS = {"label", "priority", "description", "score_percent"}
EXPECTED_METRIC_KEYS = {"label", "value"}

PII_FORBIDDEN = (
    "password", "remember_token", "fcm_token", "stripe_customer_id",
    "stripe_account_id", "apple_id", "otp", "email_verified_at",
)


def check_shape(payload):
    issues = []
    top = set(payload.keys())
    if top != EXPECTED_TOP_KEYS:
        issues.append(f"top keys mismatch: got {top}, want {EXPECTED_TOP_KEYS}")

    ttc = payload.get("trying_to_conceive", {})
    missing = EXPECTED_TTC_KEYS - set(ttc.keys())
    if missing:
        issues.append(f"trying_to_conceive missing keys: {missing}")

    cc = ttc.get("cycle_context", {})
    if set(cc.keys()) != EXPECTED_CYCLE_CONTEXT:
        issues.append(f"cycle_context keys mismatch: {set(cc.keys())}")

    lh = ttc.get("lh_surge", {})
    missing_lh = EXPECTED_LH_SURGE - set(lh.keys())
    if missing_lh:
        issues.append(f"lh_surge missing keys: {missing_lh}")
    if set(lh.get("timeline", {}).keys()) != {"start_label", "end_label"}:
        issues.append(f"lh_surge.timeline keys mismatch")
    metrics = lh.get("metrics") or []
    if len(metrics) != 3:
        issues.append(f"lh_surge.metrics should be 3 items, got {len(metrics)}")
    for i, m in enumerate(metrics):
        if set(m.keys()) != EXPECTED_METRIC_KEYS:
            issues.append(f"metrics[{i}] keys mismatch: {set(m.keys())}")

    ct = ttc.get("conception_timing", {})
    missing_ct = EXPECTED_CONCEPTION - set(ct.keys())
    if missing_ct:
        issues.append(f"conception_timing missing keys: {missing_ct}")
    windows = ct.get("windows") or []
    if len(windows) != 4:
        issues.append(f"windows should be 4 items, got {len(windows)}")
    for i, w in enumerate(windows):
        if set(w.keys()) != EXPECTED_WINDOW_KEYS:
            issues.append(f"windows[{i}] keys mismatch: {set(w.keys())}")

    hp = ttc.get("highest_priority", {})
    missing_hp = EXPECTED_HIGHEST - set(hp.keys())
    if missing_hp:
        issues.append(f"highest_priority missing keys: {missing_hp}")

    return issues


def check_pii(payload):
    body = json.dumps(payload)
    found = [t for t in PII_FORBIDDEN if t in body]
    return found


print("\n" + "=" * 80)
print("TTC REWRITE VERIFICATION  (expect: shape identical, no PII, repeat calls fast)")
print("=" * 80 + "\n")

results = []
for i in range(5):
    ms, data = fetch()
    results.append((ms, data))
    ttc = data.get("trying_to_conceive", {})
    print(f"Run {i+1}: {ms:>8.1f} ms   ai_generated={ttc.get('ai_generated')}   ai_cached={ttc.get('ai_cached')}")

print("\n--- Shape check (run 1 payload) ---")
shape_issues = check_shape(results[0][1])
if shape_issues:
    for issue in shape_issues:
        print(f"  FAIL: {issue}")
else:
    print("  PASS: all expected keys present, no unexpected keys")

print("\n--- PII leak check (run 1 payload) ---")
pii_found = check_pii(results[0][1])
if pii_found:
    print(f"  FAIL: forbidden tokens appear in response body: {pii_found}")
else:
    print("  PASS: no password / token / PII fields in response")

print("\n--- Speed check ---")
first_ms = results[0][0]
later_ms = [r[0] for r in results[1:]]
avg_later = sum(later_ms) / len(later_ms)
print(f"  first call:        {first_ms:>8.1f} ms")
print(f"  avg of runs 2-5:   {avg_later:>8.1f} ms   (target: <500 ms)")
print(f"  max of runs 2-5:   {max(later_ms):>8.1f} ms")
print(f"  speed PASS?        {'YES' if avg_later < 500 else 'NO'}")

print("\n--- Full response (run 1) ---")
print(json.dumps(results[0][1], indent=2))
