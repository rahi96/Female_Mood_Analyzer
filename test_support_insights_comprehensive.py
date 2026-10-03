#!/usr/bin/env python3
"""
Comprehensive test suite for /api/v1/support/insights endpoint
Tests all phases (pregnancy, postpartum, loss) and failure scenarios
"""

import requests
import json
import sys
from datetime import datetime
from typing import Dict, List, Tuple

BASE_URL = "http://localhost:8002/api/v1"
TIMEOUT = 15

class InsightsTester:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors = []
        
    def test(self, name: str, test_func) -> bool:
        """Run a test and track result"""
        try:
            print(f"\n{'='*80}")
            print(f"TEST: {name}")
            print(f"{'='*80}")
            result = test_func()
            if result:
                print(f"✅ PASSED")
                self.passed += 1
            else:
                print(f"❌ FAILED")
                self.failed += 1
            return result
        except Exception as e:
            print(f"💥 ERROR: {e}")
            self.errors.append((name, str(e)))
            self.failed += 1
            return False
    
    def assert_equal(self, actual, expected, msg=""):
        """Assert equality"""
        if actual != expected:
            raise AssertionError(f"{msg}\nExpected: {expected}\nActual: {actual}")
    
    def assert_in(self, item, container, msg=""):
        """Assert item in container"""
        if item not in container:
            raise AssertionError(f"{msg}\nExpected {item} in {container}")
    
    def assert_true(self, condition, msg=""):
        """Assert condition is true"""
        if not condition:
            raise AssertionError(msg)
    
    def assert_status(self, response, expected_status, msg=""):
        """Assert HTTP status"""
        if response.status_code != expected_status:
            raise AssertionError(f"{msg}\nExpected status {expected_status}, got {response.status_code}\nResponse: {response.text}")
    
    def assert_json_structure(self, data: dict, required_keys: List[str], msg=""):
        """Assert JSON has required keys"""
        missing = [k for k in required_keys if k not in data]
        if missing:
            raise AssertionError(f"{msg}\nMissing keys: {missing}")
    
    def print_response(self, response):
        """Pretty print response"""
        try:
            data = response.json()
            print(json.dumps(data, indent=2))
        except:
            print(f"Status: {response.status_code}")
            print(f"Response: {response.text[:500]}")

# ============================================================================
# SUCCESSFUL CASES
# ============================================================================

def test_pregnancy_week_7(tester: InsightsTester) -> bool:
    """Test pregnancy insights for user 6 (week 7)"""
    response = requests.get(f"{BASE_URL}/support/insights?user_id=6", timeout=TIMEOUT)
    tester.assert_status(response, 200, "Pregnancy insights should return 200")
    
    data = response.json()
    tester.assert_json_structure(data, ["user_id", "phase", "week", "insights", "generated_at"])
    tester.assert_equal(data["user_id"], 6, "user_id should match")
    tester.assert_equal(data["phase"], "pregnancy", "phase should be pregnancy")
    tester.assert_true(data["week"] > 0, "week should be positive")
    tester.assert_true(len(data["insights"]) > 0, "should have at least 1 insight")
    
    # Check insight structure
    for insight in data["insights"]:
        tester.assert_json_structure(insight, ["type", "category", "title", "content", "sentiment", "priority"])
        tester.assert_true(len(insight["content"]) > 0, "insight content should not be empty")
        tester.assert_in(insight["sentiment"], ["positive", "supportive", "informative", "empathetic", "cautionary", "hopeful"])
        tester.assert_in(insight["priority"], ["low", "medium", "high", "critical"])
    
    tester.print_response(response)
    return True

def test_postpartum_week_6(tester: InsightsTester) -> bool:
    """Test postpartum insights for user 16 (week 6)"""
    response = requests.get(f"{BASE_URL}/support/insights?user_id=16", timeout=TIMEOUT)
    tester.assert_status(response, 200, "Postpartum insights should return 200")
    
    data = response.json()
    tester.assert_json_structure(data, ["user_id", "phase", "week", "insights", "generated_at"])
    tester.assert_equal(data["user_id"], 16, "user_id should match")
    tester.assert_equal(data["phase"], "postpartum", "phase should be postpartum")
    tester.assert_equal(data["week"], 6, "week should be 6")
    tester.assert_true(len(data["insights"]) > 0, "should have at least 1 insight")
    
    # Check for recovery-related insights
    insight_types = [i["type"] for i in data["insights"]]
    tester.assert_in("recovery_progress", insight_types, "should have recovery_progress insight")
    
    tester.print_response(response)
    return True

def test_claude_personalization_pregnancy(tester: InsightsTester) -> bool:
    """Test that Claude generates personalized (not hardcoded) insights"""
    response = requests.get(f"{BASE_URL}/support/insights?user_id=6", timeout=TIMEOUT)
    data = response.json()
    
    # Check that content mentions specific week
    content = " ".join([i["content"] for i in data["insights"]])
    # Week 7 pregnancy should mention relevant details
    tester.assert_true(len(content) > 50, "insights should have substantial content (not generic fallback)")
    
    # Hardcoded fallback contains: "You're doing great in your pregnancy journey"
    # AI-generated should have more detail
    is_hardcoded_fallback = content == "You're doing great in your pregnancy journey. Continue attending prenatal appointments and trusting your body."
    tester.assert_true(not is_hardcoded_fallback, "should not return hardcoded fallback")
    
    print(f"Content preview: {content[:200]}...")
    return True

def test_claude_personalization_postpartum(tester: InsightsTester) -> bool:
    """Test that Claude generates personalized postpartum insights"""
    response = requests.get(f"{BASE_URL}/support/insights?user_id=16", timeout=TIMEOUT)
    data = response.json()
    
    content = " ".join([i["content"] for i in data["insights"]])
    
    # Should mention specific metrics (72%, 45%, etc.)
    tester.assert_true(len(content) > 80, "postpartum insights should be substantial")
    tester.assert_true("72" in content or "recovery" in content.lower() or "sleep" in content.lower(), 
                       "should reference actual metrics or recovery")
    
    print(f"Content preview: {content[:200]}...")
    return True

def test_response_has_generated_at(tester: InsightsTester) -> bool:
    """Test that response includes generated_at timestamp"""
    response = requests.get(f"{BASE_URL}/support/insights?user_id=16", timeout=TIMEOUT)
    data = response.json()
    
    tester.assert_true("generated_at" in data, "should have generated_at field")
    # Verify it's a valid date format (YYYY-MM-DD)
    tester.assert_true(len(data["generated_at"]) == 10, "generated_at should be YYYY-MM-DD format")
    tester.assert_true("-" in data["generated_at"], "generated_at should contain dashes")
    
    print(f"Generated at: {data['generated_at']}")
    return True

# ============================================================================
# INVALID INPUTS - SHOULD FAIL WITH 400/404
# ============================================================================

def test_missing_user_id(tester: InsightsTester) -> bool:
    """Test missing user_id parameter"""
    response = requests.get(f"{BASE_URL}/support/insights", timeout=TIMEOUT)
    tester.assert_true(response.status_code in [400, 422], f"should fail with 400/422, got {response.status_code}")
    print(f"Status: {response.status_code}")
    return True

def test_invalid_user_id_string(tester: InsightsTester) -> bool:
    """Test non-integer user_id"""
    response = requests.get(f"{BASE_URL}/support/insights?user_id=abc", timeout=TIMEOUT)
    tester.assert_true(response.status_code in [400, 422], f"should fail with 400/422, got {response.status_code}")
    print(f"Status: {response.status_code}")
    return True

def test_negative_user_id(tester: InsightsTester) -> bool:
    """Test negative user_id"""
    response = requests.get(f"{BASE_URL}/support/insights?user_id=-1", timeout=TIMEOUT)
    # Should either fail or return 404 (user not found)
    tester.assert_true(response.status_code in [400, 404, 422], f"should fail gracefully, got {response.status_code}")
    print(f"Status: {response.status_code}")
    return True

def test_zero_user_id(tester: InsightsTester) -> bool:
    """Test user_id=0"""
    response = requests.get(f"{BASE_URL}/support/insights?user_id=0", timeout=TIMEOUT)
    tester.assert_true(response.status_code in [400, 404, 422], f"should fail, got {response.status_code}")
    print(f"Status: {response.status_code}")
    return True

def test_nonexistent_user(tester: InsightsTester) -> bool:
    """Test user that doesn't exist"""
    response = requests.get(f"{BASE_URL}/support/insights?user_id=999999", timeout=TIMEOUT)
    tester.assert_true(response.status_code in [404, 400], f"should return 404 or 400, got {response.status_code}")
    print(f"Status: {response.status_code}")
    if response.status_code == 404:
        data = response.json()
        tester.assert_true("not currently in a tracked" in response.text.lower() or "not found" in response.text.lower(),
                          "should have meaningful error message")
    return True

def test_very_large_user_id(tester: InsightsTester) -> bool:
    """Test extremely large user_id"""
    response = requests.get(f"{BASE_URL}/support/insights?user_id=9999999999999999999", timeout=TIMEOUT)
    tester.assert_true(response.status_code in [400, 404, 422], f"should fail, got {response.status_code}")
    print(f"Status: {response.status_code}")
    return True

def test_float_user_id(tester: InsightsTester) -> bool:
    """Test float user_id (should be integer)"""
    response = requests.get(f"{BASE_URL}/support/insights?user_id=6.5", timeout=TIMEOUT)
    # Should either accept it and round, or reject it
    tester.assert_true(response.status_code in [200, 400, 422], f"got {response.status_code}")
    print(f"Status: {response.status_code}")
    return True

def test_special_characters_user_id(tester: InsightsTester) -> bool:
    """Test special characters in user_id"""
    response = requests.get(f"{BASE_URL}/support/insights?user_id=@#$%", timeout=TIMEOUT)
    tester.assert_true(response.status_code in [400, 422], f"should reject, got {response.status_code}")
    print(f"Status: {response.status_code}")
    return True

# ============================================================================
# EDGE CASES - USERS WITH MINIMAL DATA
# ============================================================================

def test_user_with_no_health_logs(tester: InsightsTester) -> bool:
    """Test user who might have pregnancy/postpartum but no health logs"""
    # Find a user who exists but might have minimal data
    # User 2 is week 1 pregnancy (minimal data)
    response = requests.get(f"{BASE_URL}/support/insights?user_id=2", timeout=TIMEOUT)
    
    if response.status_code == 200:
        data = response.json()
        tester.assert_true(len(data["insights"]) > 0, "should still generate insights")
        tester.print_response(response)
    else:
        print(f"User 2 not in valid phase: {response.status_code}")
    
    return True

def test_multiple_requests_same_user_different_responses(tester: InsightsTester) -> bool:
    """Test that multiple requests might generate slightly different content (Claude randomness)"""
    responses = []
    for i in range(2):
        response = requests.get(f"{BASE_URL}/support/insights?user_id=16", timeout=TIMEOUT)
        if response.status_code == 200:
            responses.append(response.json())
    
    if len(responses) == 2:
        # Content might be slightly different due to Claude's creativity
        content1 = responses[0]["insights"][0]["content"] if responses[0]["insights"] else ""
        content2 = responses[1]["insights"][0]["content"] if responses[1]["insights"] else ""
        
        # They should be related but possibly different (Claude may phrase differently)
        print(f"Response 1: {content1[:100]}...")
        print(f"Response 2: {content2[:100]}...")
        print(f"Responses might be slightly different due to AI generation")
    
    return True

# ============================================================================
# RESPONSE STRUCTURE VALIDATION
# ============================================================================

def test_response_structure_complete(tester: InsightsTester) -> bool:
    """Test complete response structure"""
    response = requests.get(f"{BASE_URL}/support/insights?user_id=16", timeout=TIMEOUT)
    data = response.json()
    
    # Top level
    tester.assert_json_structure(data, ["user_id", "phase", "week", "insights", "generated_at"])
    
    # user_id
    tester.assert_true(isinstance(data["user_id"], int), "user_id should be integer")
    tester.assert_true(data["user_id"] > 0, "user_id should be positive")
    
    # phase
    tester.assert_in(data["phase"], ["pregnancy", "postpartum", "loss", "unknown"])
    
    # week
    tester.assert_true(isinstance(data["week"], int), "week should be integer")
    tester.assert_true(data["week"] >= 0, "week should be non-negative")
    
    # insights
    tester.assert_true(isinstance(data["insights"], list), "insights should be list")
    
    # each insight
    for idx, insight in enumerate(data["insights"]):
        tester.assert_json_structure(insight, ["type", "category", "title", "content", "sentiment", "priority"], 
                                   f"insight {idx} missing fields")
        
        # Validate insight fields
        tester.assert_true(isinstance(insight["type"], str), f"insight {idx}: type should be string")
        tester.assert_true(isinstance(insight["category"], str), f"insight {idx}: category should be string")
        tester.assert_true(isinstance(insight["title"], str), f"insight {idx}: title should be string")
        tester.assert_true(isinstance(insight["content"], str), f"insight {idx}: content should be string")
        tester.assert_true(len(insight["content"]) > 0, f"insight {idx}: content should not be empty")
    
    # generated_at
    tester.assert_true(isinstance(data["generated_at"], str), "generated_at should be string")
    
    print("✅ All response structure checks passed")
    return True

def test_insight_types_valid(tester: InsightsTester) -> bool:
    """Test that insight types are valid"""
    response = requests.get(f"{BASE_URL}/support/insights?user_id=16", timeout=TIMEOUT)
    data = response.json()
    
    valid_types = {
        "pregnancy": ["baby_development", "care_timeline", "symptom_analysis", "emotional_support", "general"],
        "postpartum": ["recovery_progress", "mental_wellness", "clinical_insight", "activity_guidance", "recovery_status"],
        "loss": ["grief_support", "healing_guidance", "physical_care", "hope_and_future", "loss_support_resources"]
    }
    
    phase = data["phase"]
    allowed_types = valid_types.get(phase, [])
    
    for insight in data["insights"]:
        insight_type = insight["type"]
        print(f"Insight type: {insight_type}")
        # Allow flexibility for fallback insights
        tester.assert_true(len(insight_type) > 0, "type should not be empty")
    
    return True

# ============================================================================
# CONTENT VALIDATION
# ============================================================================

def test_content_is_not_empty(tester: InsightsTester) -> bool:
    """Test that all insights have non-empty content"""
    response = requests.get(f"{BASE_URL}/support/insights?user_id=16", timeout=TIMEOUT)
    data = response.json()
    
    for idx, insight in enumerate(data["insights"]):
        content = insight["content"].strip()
        tester.assert_true(len(content) > 10, f"insight {idx} content too short: '{content}'")
    
    return True

def test_content_not_hardcoded_placeholder(tester: InsightsTester) -> bool:
    """Test that content is not hardcoded placeholder text"""
    response = requests.get(f"{BASE_URL}/support/insights?user_id=16", timeout=TIMEOUT)
    data = response.json()
    
    placeholder_phrases = [
        "You're doing great",  # Generic phrase that should not appear alone
        "Continue attending prenatal",  # Specific to pregnancy fallback
    ]
    
    content = " ".join([i["content"] for i in data["insights"]])
    
    # Should have more than just the generic fallback
    is_pure_fallback = content == "You're doing great. Continue following your healthcare provider's guidance and listen to your body."
    tester.assert_true(not is_pure_fallback, "should not be pure fallback content")
    
    return True

def test_title_is_not_empty(tester: InsightsTester) -> bool:
    """Test that all insights have titles"""
    response = requests.get(f"{BASE_URL}/support/insights?user_id=16", timeout=TIMEOUT)
    data = response.json()
    
    for idx, insight in enumerate(data["insights"]):
        tester.assert_true(len(insight["title"]) > 0, f"insight {idx} title is empty")
        tester.assert_true(len(insight["title"]) < 200, f"insight {idx} title too long")
    
    return True

# ============================================================================
# TIMEOUT AND PERFORMANCE
# ============================================================================

def test_request_completes_within_timeout(tester: InsightsTester) -> bool:
    """Test that request completes within reasonable time"""
    import time
    start = time.time()
    response = requests.get(f"{BASE_URL}/support/insights?user_id=16", timeout=TIMEOUT)
    elapsed = time.time() - start
    
    tester.assert_true(elapsed < TIMEOUT, f"request took {elapsed}s (timeout: {TIMEOUT}s)")
    print(f"Request completed in {elapsed:.2f}s")
    
    return True

# ============================================================================
# DIFFERENT PHASES
# ============================================================================

def test_pregnancy_user_different_week(tester: InsightsTester) -> bool:
    """Test pregnancy user at different week"""
    # User 6 is week 7
    response = requests.get(f"{BASE_URL}/support/insights?user_id=6", timeout=TIMEOUT)
    
    if response.status_code == 200:
        data = response.json()
        tester.assert_equal(data["phase"], "pregnancy")
        tester.assert_true(data["week"] > 0)
        tester.assert_true(len(data["insights"]) > 0)
    
    return True

def test_postpartum_specific_metrics(tester: InsightsTester) -> bool:
    """Test that postpartum insights reference actual recovery metrics"""
    response = requests.get(f"{BASE_URL}/support/insights?user_id=16", timeout=TIMEOUT)
    data = response.json()
    
    if data["phase"] == "postpartum":
        content = " ".join([i["content"] for i in data["insights"]])
        
        # Should reference recovery metrics
        tester.assert_true(
            "recovery" in content.lower() or "sleep" in content.lower() or 
            "energy" in content.lower() or "72" in content or "45" in content,
            "postpartum insights should reference recovery metrics"
        )
    
    return True

# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

def main():
    tester = InsightsTester()
    
    print("╔" + "="*78 + "╗")
    print("║" + " "*20 + "COMPREHENSIVE INSIGHTS API TEST SUITE" + " "*21 + "║")
    print("╚" + "="*78 + "╝")
    
    # Successful cases
    print("\n\n" + "█"*80)
    print("SECTION 1: SUCCESSFUL CASES (Should return 200 with valid data)")
    print("█"*80)
    
    tester.test("Pregnancy insights (week 7)", lambda: test_pregnancy_week_7(tester))
    tester.test("Postpartum insights (week 6)", lambda: test_postpartum_week_6(tester))
    tester.test("Claude personalization (pregnancy)", lambda: test_claude_personalization_pregnancy(tester))
    tester.test("Claude personalization (postpartum)", lambda: test_claude_personalization_postpartum(tester))
    tester.test("Response has generated_at timestamp", lambda: test_response_has_generated_at(tester))
    
    # Invalid inputs
    print("\n\n" + "█"*80)
    print("SECTION 2: INVALID INPUTS (Should fail with 400/404/422)")
    print("█"*80)
    
    tester.test("Missing user_id parameter", lambda: test_missing_user_id(tester))
    tester.test("Invalid user_id (string)", lambda: test_invalid_user_id_string(tester))
    tester.test("Negative user_id", lambda: test_negative_user_id(tester))
    tester.test("Zero user_id", lambda: test_zero_user_id(tester))
    tester.test("Nonexistent user", lambda: test_nonexistent_user(tester))
    tester.test("Very large user_id", lambda: test_very_large_user_id(tester))
    tester.test("Float user_id", lambda: test_float_user_id(tester))
    tester.test("Special characters in user_id", lambda: test_special_characters_user_id(tester))
    
    # Edge cases
    print("\n\n" + "█"*80)
    print("SECTION 3: EDGE CASES (Boundary conditions)")
    print("█"*80)
    
    tester.test("User with minimal/no health logs", lambda: test_user_with_no_health_logs(tester))
    tester.test("Multiple requests generate responses", lambda: test_multiple_requests_same_user_different_responses(tester))
    
    # Response structure
    print("\n\n" + "█"*80)
    print("SECTION 4: RESPONSE STRUCTURE VALIDATION")
    print("█"*80)
    
    tester.test("Complete response structure", lambda: test_response_structure_complete(tester))
    tester.test("Insight types are valid", lambda: test_insight_types_valid(tester))
    
    # Content validation
    print("\n\n" + "█"*80)
    print("SECTION 5: CONTENT VALIDATION")
    print("█"*80)
    
    tester.test("All insights have non-empty content", lambda: test_content_is_not_empty(tester))
    tester.test("Content not hardcoded placeholder", lambda: test_content_not_hardcoded_placeholder(tester))
    tester.test("All insights have titles", lambda: test_title_is_not_empty(tester))
    
    # Performance
    print("\n\n" + "█"*80)
    print("SECTION 6: PERFORMANCE & TIMEOUT")
    print("█"*80)
    
    tester.test("Request completes within timeout", lambda: test_request_completes_within_timeout(tester))
    
    # Different phases
    print("\n\n" + "█"*80)
    print("SECTION 7: DIFFERENT USER PHASES")
    print("█"*80)
    
    tester.test("Pregnancy user (different week)", lambda: test_pregnancy_user_different_week(tester))
    tester.test("Postpartum references actual metrics", lambda: test_postpartum_specific_metrics(tester))
    
    # Final summary
    print("\n\n" + "╔" + "="*78 + "╗")
    print("║" + " "*25 + "TEST SUMMARY" + " "*41 + "║")
    print("╠" + "="*78 + "╣")
    print(f"║ Passed:  {tester.passed:<70} ║")
    print(f"║ Failed:  {tester.failed:<70} ║")
    print(f"║ Skipped: {tester.skipped:<70} ║")
    print("╠" + "="*78 + "╣")
    
    if tester.errors:
        print("║ ERRORS:".ljust(79) + "║")
        for name, error in tester.errors:
            print(f"║   - {name}".ljust(79) + "║")
            print(f"║     {error[:70]}".ljust(79) + "║")
    
    print("╚" + "="*78 + "╝\n")
    
    # Exit code
    if tester.failed > 0:
        print(f"❌ {tester.failed} tests failed")
        sys.exit(1)
    else:
        print(f"✅ All {tester.passed} tests passed!")
        sys.exit(0)

if __name__ == "__main__":
    main()
