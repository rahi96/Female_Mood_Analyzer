#!/usr/bin/env python3
"""
COMPREHENSIVE LIFELONG THRIVING API FAILURE TEST SUITE
========================================================
This script performs exhaustive testing of the Reminders API, covering:
- All valid user scenarios
- All invalid user scenarios
- Edge cases and boundary conditions
- Data validation and type checking
- Business logic verification
- Performance metrics
- Error handling and recovery
- Response structure validation
- Status code validation
"""

import requests
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Any, Optional
import statistics

# ============================================================================
# CONFIGURATION
# ============================================================================

API_BASE_URL = "http://localhost:8002"
REMINDERS_ENDPOINT = f"{API_BASE_URL}/api/v1/lifelong-thriving/reminders"
VITALITY_ENDPOINT = f"{API_BASE_URL}/api/v1/lifelong-thriving/vitality"
LIFE_ARC_ENDPOINT = f"{API_BASE_URL}/api/v1/lifelong-thriving/life-arc"
TIMEOUT = 10
VALID_USERS = [2, 6, 23, 3455]
INVALID_USERS = [
    -1,                          # Negative ID
    0,                           # Zero ID
    999999,                      # Non-existent user
    -999999,                     # Large negative
    2147483647,                  # Max int32
    -2147483648,                 # Min int32
]

# ============================================================================
# TEST RESULT TRACKING
# ============================================================================

class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.errors = []
        self.test_details = []
        self.response_times = []
        self.status_codes = {}

    def add_pass(self, test_name: str, details: str = ""):
        self.passed += 1
        self.test_details.append({"status": "PASS", "test": test_name, "details": details})
        print(f"[PASS] {test_name}" + (f" - {details}" if details else ""))

    def add_fail(self, test_name: str, reason: str):
        self.failed += 1
        self.test_details.append({"status": "FAIL", "test": test_name, "reason": reason})
        self.errors.append((test_name, reason))
        print(f"[FAIL] {test_name} - {reason}")

    def add_warning(self, test_name: str, message: str):
        self.warnings += 1
        self.test_details.append({"status": "WARN", "test": test_name, "message": message})
        print(f"[WARN] {test_name} - {message}")

    def add_response_time(self, time_ms: float):
        self.response_times.append(time_ms)

    def track_status_code(self, code: int):
        self.status_codes[code] = self.status_codes.get(code, 0) + 1

    def print_summary(self):
        total = self.passed + self.failed + self.warnings
        pass_rate = (self.passed / total * 100) if total > 0 else 0
        
        print("\n" + "="*80)
        print("TEST EXECUTION SUMMARY")
        print("="*80)
        print(f"Total Tests:        {total}")
        print(f"Passed:             {self.passed}")
        print(f"Failed:             {self.failed}")
        print(f"Warnings:           {self.warnings}")
        print(f"Pass Rate:          {pass_rate:.1f}%")
        print()
        
        if self.response_times:
            avg_time = statistics.mean(self.response_times)
            min_time = min(self.response_times)
            max_time = max(self.response_times)
            print(f"Response Times (ms):")
            print(f"  Average:          {avg_time:.2f}ms")
            print(f"  Min:              {min_time:.2f}ms")
            print(f"  Max:              {max_time:.2f}ms")
            print()
        
        if self.status_codes:
            print(f"Status Codes:")
            for code in sorted(self.status_codes.keys()):
                count = self.status_codes[code]
                print(f"  {code}:          {count}")
            print()
        
        if self.errors:
            print(f"Failures ({len(self.errors)}):")
            for test, reason in self.errors:
                print(f"  - {test}: {reason}")
            print()
        
        print("="*80)

# ============================================================================
# TEST SUITES
# ============================================================================

def test_response_structure(results: TestResults, user_id: int, response: Dict) -> bool:
    """Validate API response structure"""
    print(f"\n--- TEST SUITE: Response Structure (User {user_id}) ---")
    
    required_fields = ["reminders", "mobility_stress_reminders", "summary", "last_updated"]
    all_present = True
    
    for field in required_fields:
        if field in response:
            results.add_pass(f"Field '{field}' present", f"User {user_id}")
        else:
            results.add_fail(f"Field '{field}' missing", f"User {user_id}")
            all_present = False
    
    # Validate reminders structure
    if "reminders" in response and isinstance(response["reminders"], list):
        results.add_pass("Reminders is array", f"Count: {len(response['reminders'])}")
        
        if len(response["reminders"]) > 0:
            reminder = response["reminders"][0]
            reminder_fields = ["id", "type", "status", "priority", "last_done", "due_date",
                             "days_overdue", "days_until_due", "guideline", "recommendation",
                             "status_label", "status_color"]
            for field in reminder_fields:
                if field in reminder:
                    results.add_pass(f"Reminder field '{field}'", f"User {user_id}")
                else:
                    results.add_fail(f"Reminder field '{field}' missing", f"User {user_id}")
                    all_present = False
    
    # Validate mobility_stress_reminders structure
    if "mobility_stress_reminders" in response and isinstance(response["mobility_stress_reminders"], list):
        results.add_pass("Mobility metrics is array", f"Count: {len(response['mobility_stress_reminders'])}")
        
        if len(response["mobility_stress_reminders"]) > 0:
            metric = response["mobility_stress_reminders"][0]
            metric_fields = ["area", "score", "status", "last_measured"]
            for field in metric_fields:
                if field in metric:
                    results.add_pass(f"Metric field '{field}'", f"User {user_id}")
                else:
                    results.add_fail(f"Metric field '{field}' missing", f"User {user_id}")
                    all_present = False
    
    # Validate summary structure
    if "summary" in response:
        summary_fields = ["total_reminders", "not_started", "overdue", "due_soon",
                         "scheduled", "up_to_date", "not_applicable"]
        for field in summary_fields:
            if field in response["summary"]:
                results.add_pass(f"Summary field '{field}'", f"Value: {response['summary'][field]}")
            else:
                results.add_fail(f"Summary field '{field}' missing", f"User {user_id}")
                all_present = False
    
    return all_present

def test_data_types(results: TestResults, user_id: int, response: Dict) -> bool:
    """Validate data types of all fields"""
    print(f"\n--- TEST SUITE: Data Type Validation (User {user_id}) ---")
    
    all_valid = True
    
    # Summary counts must be integers
    if "summary" in response:
        for field in ["total_reminders", "not_started", "overdue", "due_soon",
                     "scheduled", "up_to_date", "not_applicable"]:
            if field in response["summary"]:
                value = response["summary"][field]
                if isinstance(value, int) and value >= 0:
                    results.add_pass(f"Summary '{field}' is non-negative int", f"Value: {value}")
                else:
                    results.add_fail(f"Summary '{field}' invalid", f"Got {type(value).__name__}: {value}")
                    all_valid = False
    
    # Reminder fields validation
    if "reminders" in response:
        for reminder in response["reminders"]:
            # Check ID
            if not isinstance(reminder.get("id"), int):
                results.add_fail(f"Reminder ID must be int", f"Got {type(reminder.get('id')).__name__}")
                all_valid = False
            
            # Check type is string
            if not isinstance(reminder.get("type"), str) or not reminder.get("type"):
                results.add_fail(f"Reminder type must be non-empty string", f"Got {reminder.get('type')}")
                all_valid = False
            
            # Check status is valid enum
            valid_statuses = ["not_started", "overdue", "due_soon", "scheduled", "up_to_date", "not_applicable"]
            if reminder.get("status") not in valid_statuses:
                results.add_fail(f"Reminder status invalid", 
                               f"Got '{reminder.get('status')}', expected one of {valid_statuses}")
                all_valid = False
            
            # Check priority is valid
            valid_priorities = ["critical", "high", "medium", "low"]
            if reminder.get("priority") not in valid_priorities:
                results.add_warning(f"Reminder priority unusual", 
                                  f"Got '{reminder.get('priority')}', expected one of {valid_priorities}")
            
            # Check scores are in range
            if "days_overdue" in reminder and reminder["days_overdue"] is not None:
                if not isinstance(reminder["days_overdue"], (int, float)) or reminder["days_overdue"] < 0:
                    results.add_fail(f"days_overdue must be non-negative number",
                                   f"Got {reminder['days_overdue']}")
                    all_valid = False
            
            if "days_until_due" in reminder and reminder["days_until_due"] is not None:
                if not isinstance(reminder["days_until_due"], (int, float)) or reminder["days_until_due"] < 0:
                    results.add_fail(f"days_until_due must be non-negative number",
                                   f"Got {reminder['days_until_due']}")
                    all_valid = False
    
    # Mobility metrics validation
    if "mobility_stress_reminders" in response:
        for metric in response["mobility_stress_reminders"]:
            # Check area is string
            if not isinstance(metric.get("area"), str) or not metric.get("area"):
                results.add_fail(f"Metric area must be non-empty string", f"Got {metric.get('area')}")
                all_valid = False
            
            # Check score is in 0-100 range
            score = metric.get("score")
            if not isinstance(score, (int, float)) or not (0 <= score <= 100):
                results.add_fail(f"Metric score must be 0-100", f"Got {score}")
                all_valid = False
            else:
                results.add_pass(f"Metric '{metric.get('area')}' score valid", f"Value: {score}")
            
            # Check status is valid
            valid_statuses = ["excellent", "good", "fair", "poor"]
            if metric.get("status") not in valid_statuses:
                results.add_warning(f"Metric status unusual",
                                  f"Got '{metric.get('status')}', expected one of {valid_statuses}")
    
    return all_valid

def test_business_logic(results: TestResults, user_id: int, response: Dict) -> bool:
    """Validate business logic correctness"""
    print(f"\n--- TEST SUITE: Business Logic (User {user_id}) ---")
    
    all_valid = True
    
    if "summary" in response and "reminders" in response:
        # Summary count must match reminders count
        total = response["summary"].get("total_reminders", 0)
        actual_count = len(response["reminders"])
        
        if total == actual_count:
            results.add_pass(f"Summary total_reminders matches actual count", f"{total} = {actual_count}")
        else:
            results.add_fail(f"Summary count mismatch", f"Total: {total}, Actual: {actual_count}")
            all_valid = False
        
        # Sum of status counts must equal total
        status_sum = sum([
            response["summary"].get("not_started", 0),
            response["summary"].get("overdue", 0),
            response["summary"].get("due_soon", 0),
            response["summary"].get("scheduled", 0),
            response["summary"].get("up_to_date", 0),
            response["summary"].get("not_applicable", 0),
        ])
        
        if status_sum == total:
            results.add_pass(f"Status counts sum correctly", f"Sum: {status_sum}, Total: {total}")
        else:
            results.add_fail(f"Status counts don't sum correctly", f"Sum: {status_sum}, Total: {total}")
            all_valid = False
        
        # Validate status-to-count consistency
        status_counts = {}
        for reminder in response["reminders"]:
            status = reminder.get("status")
            status_counts[status] = status_counts.get(status, 0) + 1
        
        for status, expected_count in status_counts.items():
            actual_count = response["summary"].get(status, 0)
            if expected_count == actual_count:
                results.add_pass(f"Status '{status}' count correct", f"{expected_count}")
            else:
                results.add_fail(f"Status '{status}' count mismatch", 
                               f"Expected: {expected_count}, Got: {actual_count}")
                all_valid = False
        
        # NOT_STARTED reminders must have days_overdue = None
        for reminder in response["reminders"]:
            if reminder.get("status") == "not_started":
                if reminder.get("days_overdue") is None:
                    results.add_pass(f"NOT_STARTED reminder has days_overdue=None", 
                                   f"Type: {reminder.get('type')}")
                else:
                    results.add_fail(f"NOT_STARTED reminder has days_overdue value",
                                   f"Type: {reminder.get('type')}, Value: {reminder.get('days_overdue')}")
                    all_valid = False
        
        # OVERDUE reminders must have days_overdue > 0
        for reminder in response["reminders"]:
            if reminder.get("status") == "overdue":
                if reminder.get("days_overdue", 0) > 0:
                    results.add_pass(f"OVERDUE reminder has positive days_overdue",
                                   f"Type: {reminder.get('type')}, Value: {reminder.get('days_overdue')}")
                else:
                    results.add_fail(f"OVERDUE reminder has invalid days_overdue",
                                   f"Type: {reminder.get('type')}, Value: {reminder.get('days_overdue')}")
                    all_valid = False
    
    # Mobility metrics count should be consistent
    if "mobility_stress_reminders" in response:
        metrics_count = len(response["mobility_stress_reminders"])
        if metrics_count == 4:
            results.add_pass(f"Exactly 4 mobility metrics present", f"Count: {metrics_count}")
        else:
            results.add_fail(f"Expected 4 mobility metrics", f"Got: {metrics_count}")
            all_valid = False
        
        # Check for duplicate metric areas
        areas = [m.get("area") for m in response["mobility_stress_reminders"]]
        if len(areas) == len(set(areas)):
            results.add_pass(f"All metric areas are unique", f"Areas: {areas}")
        else:
            results.add_fail(f"Duplicate metric areas found", f"Areas: {areas}")
            all_valid = False
    
    return all_valid

def test_edge_cases(results: TestResults, user_id: int, response: Dict) -> bool:
    """Test edge cases and boundary conditions"""
    print(f"\n--- TEST SUITE: Edge Cases (User {user_id}) ---")
    
    all_valid = True
    
    # Check for null/None values in required fields
    if "reminders" in response:
        for reminder in response["reminders"]:
            required_fields = ["id", "type", "status", "due_date"]
            for field in required_fields:
                if reminder.get(field) is None:
                    results.add_fail(f"Required field '{field}' is None", 
                                   f"Reminder: {reminder.get('type')}")
                    all_valid = False
    
    # Check for empty arrays when they shouldn't be
    if "reminders" in response and isinstance(response["reminders"], list):
        results.add_pass(f"Reminders is valid array", f"Length: {len(response['reminders'])}")
    else:
        results.add_fail(f"Reminders is not a valid array", f"Type: {type(response.get('reminders'))}")
        all_valid = False
    
    # Check last_updated timestamp is recent
    if "last_updated" in response:
        try:
            last_updated = datetime.fromisoformat(response["last_updated"].replace("Z", "+00:00"))
            now = datetime.now(last_updated.tzinfo)
            time_diff = (now - last_updated).total_seconds()
            
            if 0 <= time_diff <= 3600:  # Should be recent (within 1 hour)
                results.add_pass(f"last_updated is recent", f"{time_diff:.0f} seconds ago")
            else:
                results.add_warning(f"last_updated is old", f"{time_diff:.0f} seconds ago")
        except Exception as e:
            results.add_fail(f"last_updated format invalid", f"Error: {str(e)}")
            all_valid = False
    
    # Check date formats
    if "reminders" in response:
        for reminder in response["reminders"]:
            if "due_date" in reminder and reminder["due_date"] is not None:
                try:
                    datetime.fromisoformat(reminder["due_date"].replace("Z", "+00:00"))
                    results.add_pass(f"due_date format valid", f"Reminder: {reminder.get('type')}")
                except:
                    results.add_fail(f"due_date format invalid", 
                                   f"Value: {reminder.get('due_date')}")
                    all_valid = False
            
            if "last_done" in reminder and reminder["last_done"] is not None:
                try:
                    datetime.fromisoformat(reminder["last_done"].replace("Z", "+00:00"))
                    results.add_pass(f"last_done format valid", f"Reminder: {reminder.get('type')}")
                except:
                    results.add_fail(f"last_done format invalid",
                                   f"Value: {reminder.get('last_done')}")
                    all_valid = False
    
    return all_valid

def test_valid_users(results: TestResults):
    """Test with valid user IDs"""
    print("\n" + "="*80)
    print("TEST SUITE 1: VALID USER IDS")
    print("="*80)
    
    for user_id in VALID_USERS:
        print(f"\n{'='*80}")
        print(f"Testing User ID: {user_id}")
        print(f"{'='*80}")
        
        try:
            start_time = time.time()
            response = requests.get(f"{REMINDERS_ENDPOINT}?user_id={user_id}", timeout=TIMEOUT)
            elapsed_ms = (time.time() - start_time) * 1000
            
            results.add_response_time(elapsed_ms)
            results.track_status_code(response.status_code)
            
            if response.status_code == 200:
                results.add_pass(f"HTTP 200 OK", f"User {user_id} ({elapsed_ms:.2f}ms)")
                
                data = response.json()
                test_response_structure(results, user_id, data)
                test_data_types(results, user_id, data)
                test_business_logic(results, user_id, data)
                test_edge_cases(results, user_id, data)
            else:
                results.add_fail(f"HTTP {response.status_code}", f"User {user_id}")
        
        except requests.Timeout:
            results.add_fail(f"Request timeout", f"User {user_id} (>{TIMEOUT}s)")
        except Exception as e:
            results.add_fail(f"Request failed", f"User {user_id}: {str(e)}")

def test_invalid_users(results: TestResults):
    """Test with invalid user IDs"""
    print("\n" + "="*80)
    print("TEST SUITE 2: INVALID USER IDS")
    print("="*80)
    
    for user_id in INVALID_USERS:
        print(f"\nTesting Invalid User ID: {user_id}")
        
        try:
            start_time = time.time()
            response = requests.get(f"{REMINDERS_ENDPOINT}?user_id={user_id}", timeout=TIMEOUT)
            elapsed_ms = (time.time() - start_time) * 1000
            
            results.add_response_time(elapsed_ms)
            results.track_status_code(response.status_code)
            
            # Invalid users should return 200 with graceful fallback or 404/400
            if response.status_code == 200:
                results.add_pass(f"HTTP 200 (graceful fallback)", f"User {user_id}")
                data = response.json()
                
                # Should still have valid structure
                if "reminders" in data and "summary" in data:
                    results.add_pass(f"Valid response structure returned", f"User {user_id}")
                    # Should have empty or default reminders
                    if len(data.get("reminders", [])) >= 0:
                        results.add_pass(f"Reminders array present", 
                                       f"User {user_id}, Count: {len(data.get('reminders', []))}")
                else:
                    results.add_fail(f"Invalid response structure", f"User {user_id}")
            
            elif response.status_code in [400, 404, 422]:
                results.add_pass(f"HTTP {response.status_code} (expected error)", f"User {user_id}")
                
                # Should have error message
                try:
                    data = response.json()
                    if "detail" in data or "message" in data:
                        results.add_pass(f"Error message provided", f"User {user_id}")
                    else:
                        results.add_warning(f"No error message in response", f"User {user_id}")
                except:
                    results.add_warning(f"Response not JSON", f"User {user_id}")
            
            else:
                results.add_warning(f"HTTP {response.status_code} (unexpected)", f"User {user_id}")
        
        except requests.Timeout:
            results.add_fail(f"Request timeout", f"User {user_id} (>{TIMEOUT}s)")
        except Exception as e:
            results.add_fail(f"Request failed", f"User {user_id}: {str(e)}")

def test_malformed_requests(results: TestResults):
    """Test with malformed requests"""
    print("\n" + "="*80)
    print("TEST SUITE 3: MALFORMED REQUESTS")
    print("="*80)
    
    malformed_requests = [
        ("", "Empty user ID"),
        ("abc", "Non-numeric user ID"),
        ("12.5", "Decimal user ID"),
        ("12 34", "User ID with space"),
        ("12\n34", "User ID with newline"),
        ("../admin", "Path traversal attempt"),
        ("'; DROP TABLE;", "SQL injection attempt"),
        ("<script>alert(1)</script>", "XSS attempt"),
    ]
    
    for user_id, description in malformed_requests:
        print(f"\nTesting: {description}")
        
        try:
            start_time = time.time()
            response = requests.get(f"{REMINDERS_ENDPOINT}?user_id={user_id}", timeout=TIMEOUT)
            elapsed_ms = (time.time() - start_time) * 1000
            
            results.add_response_time(elapsed_ms)
            results.track_status_code(response.status_code)
            
            if response.status_code in [400, 404, 422]:
                results.add_pass(f"Rejected malformed request", 
                               f"{description} - HTTP {response.status_code}")
            elif response.status_code == 200:
                results.add_warning(f"Accepted malformed request", 
                                  f"{description} - HTTP 200 (graceful fallback)")
            else:
                results.add_warning(f"Unexpected status code", 
                                  f"{description} - HTTP {response.status_code}")
        
        except Exception as e:
            results.add_pass(f"Request handled gracefully", f"{description}: {type(e).__name__}")

def test_performance(results: TestResults):
    """Test API performance under load"""
    print("\n" + "="*80)
    print("TEST SUITE 4: PERFORMANCE TESTING")
    print("="*80)
    
    print("\nPerforming sequential requests on valid users...")
    
    test_user = VALID_USERS[0]
    sequential_times = []
    
    for i in range(10):
        try:
            start_time = time.time()
            response = requests.get(f"{REMINDERS_ENDPOINT}?user_id={test_user}", timeout=TIMEOUT)
            elapsed_ms = (time.time() - start_time) * 1000
            sequential_times.append(elapsed_ms)
            results.add_response_time(elapsed_ms)
            
            if response.status_code == 200:
                results.add_pass(f"Request {i+1}/10 completed", f"{elapsed_ms:.2f}ms")
            else:
                results.add_fail(f"Request {i+1}/10 failed", f"HTTP {response.status_code}")
        
        except Exception as e:
            results.add_fail(f"Request {i+1}/10 failed", str(e))
    
    if sequential_times:
        avg = statistics.mean(sequential_times)
        p95 = sorted(sequential_times)[int(len(sequential_times)*0.95)]
        p99 = sorted(sequential_times)[int(len(sequential_times)*0.99)]
        
        print(f"\nPerformance Summary (User {test_user}):")
        print(f"  Average:        {avg:.2f}ms")
        print(f"  P95:            {p95:.2f}ms")
        print(f"  P99:            {p99:.2f}ms")
        
        if avg < 100:
            results.add_pass(f"Response time excellent", f"Average: {avg:.2f}ms")
        elif avg < 500:
            results.add_pass(f"Response time good", f"Average: {avg:.2f}ms")
        elif avg < 2000:
            results.add_warning(f"Response time acceptable", f"Average: {avg:.2f}ms")
        else:
            results.add_fail(f"Response time slow", f"Average: {avg:.2f}ms")

def test_consistency(results: TestResults):
    """Test response consistency across multiple calls"""
    print("\n" + "="*80)
    print("TEST SUITE 5: RESPONSE CONSISTENCY")
    print("="*80)
    
    test_user = VALID_USERS[0]
    responses = []
    
    print(f"\nFetching same user ({test_user}) 5 times for consistency check...")
    
    for i in range(5):
        try:
            response = requests.get(f"{REMINDERS_ENDPOINT}?user_id={test_user}", timeout=TIMEOUT)
            if response.status_code == 200:
                responses.append(response.json())
                results.add_pass(f"Fetch {i+1}/5 successful", f"User {test_user}")
            else:
                results.add_fail(f"Fetch {i+1}/5 failed", f"HTTP {response.status_code}")
        except Exception as e:
            results.add_fail(f"Fetch {i+1}/5 failed", str(e))
    
    if len(responses) >= 2:
        # Compare responses
        first_response = responses[0]
        
        for i, response in enumerate(responses[1:], start=2):
            # Check reminders count consistency
            if len(response["reminders"]) == len(first_response["reminders"]):
                results.add_pass(f"Reminders count consistent (fetch {i})",
                               f"Count: {len(response['reminders'])}")
            else:
                results.add_warning(f"Reminders count changed (fetch {i})",
                                  f"Was {len(first_response['reminders'])}, now {len(response['reminders'])}")
            
            # Check summary consistency
            if response["summary"] == first_response["summary"]:
                results.add_pass(f"Summary consistent (fetch {i})", "All counts match")
            else:
                results.add_warning(f"Summary changed (fetch {i})",
                                  f"First: {first_response['summary']}, Now: {response['summary']}")
            
            # Check metrics count consistency
            if len(response["mobility_stress_reminders"]) == len(first_response["mobility_stress_reminders"]):
                results.add_pass(f"Metrics count consistent (fetch {i})",
                               f"Count: {len(response['mobility_stress_reminders'])}")
            else:
                results.add_fail(f"Metrics count changed (fetch {i})",
                               f"Was {len(first_response['mobility_stress_reminders'])}, now {len(response['mobility_stress_reminders'])}")

def test_error_handling(results: TestResults):
    """Test error handling and recovery"""
    print("\n" + "="*80)
    print("TEST SUITE 6: ERROR HANDLING & RECOVERY")
    print("="*80)
    
    print("\nTesting timeout behavior...")
    try:
        response = requests.get(f"{REMINDERS_ENDPOINT}?user_id={VALID_USERS[0]}", timeout=0.001)
        results.add_fail(f"Very short timeout should fail", "Unexpectedly succeeded")
    except requests.Timeout:
        results.add_pass(f"Timeout handled correctly", "0.001s timeout properly raised")
    except Exception as e:
        results.add_warning(f"Unexpected error on timeout", str(e))
    
    print("\nTesting connection errors...")
    try:
        bad_url = "http://localhost:9999/api/v1/lifelong-thriving/reminders/1"
        response = requests.get(bad_url, timeout=2)
        results.add_fail(f"Should fail on bad port", "Unexpectedly succeeded")
    except (requests.ConnectionError, requests.ConnectTimeout):
        results.add_pass(f"Connection error handled", "Bad port properly rejected")
    except Exception as e:
        results.add_pass(f"Error handled", f"{type(e).__name__}")

# ============================================================================
# MAIN TEST EXECUTION
# ============================================================================

def main():
    print("\n" + "="*80)
    print("LIFELONG THRIVING API - COMPREHENSIVE FAILURE TEST SUITE")
    print("="*80)
    print(f"Target API: {REMINDERS_ENDPOINT}")
    print(f"Timestamp:  {datetime.now().isoformat()}")
    print("="*80)
    
    results = TestResults()
    
    # Run all test suites
    test_valid_users(results)
    test_invalid_users(results)
    test_malformed_requests(results)
    test_performance(results)
    test_consistency(results)
    test_error_handling(results)
    
    # Print final summary
    results.print_summary()
    
    # Detailed failure report
    if results.failed > 0:
        print("\n" + "="*80)
        print("DETAILED FAILURE REPORT")
        print("="*80)
        for test, reason in results.errors:
            print(f"\n[FAIL] {test}")
            print(f"       Reason: {reason}")
    
    return 0 if results.failed == 0 else 1

if __name__ == "__main__":
    exit(main())
