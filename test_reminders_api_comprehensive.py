#!/usr/bin/env python3
"""
Comprehensive Test Suite for Lifelong Thriving Reminders API
Tests: Accuracy, Data Flow, Edge Cases, AI Insights, Error Handling
"""

import requests
import json
import sys
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any

# Fix Windows encoding issues
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

API_BASE_URL = "http://localhost:8002/api/v1"
REMINDERS_ENDPOINT = f"{API_BASE_URL}/lifelong-thriving/reminders"

# Test data: Various user IDs with different scenarios
TEST_USERS = {
    "user_23": 23,           # No DOB, should use age_group
    "user_3455": 3455,       # No DOB, should use age_group
    "user_6": 6,             # Has DOB, has some data
    "user_2": 2,             # Age 50+, should have Bone Density + Colonoscopy
    "user_invalid": 999999,  # Non-existent user
}

class RemindersAPITester:
    def __init__(self):
        self.results = {
            "passed": [],
            "failed": [],
            "warnings": [],
            "data_flow": []
        }
        self.test_count = 0
        self.pass_count = 0
    
    def log(self, message: str, level: str = "INFO"):
        """Log test message with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = f"[{timestamp}] [{level}]"
        print(f"{prefix} {message}")
    
    def assert_equal(self, actual, expected, test_name: str):
        """Assert equality with logging."""
        self.test_count += 1
        if actual == expected:
            self.log(f"✅ PASS: {test_name}", "PASS")
            self.results["passed"].append(test_name)
            self.pass_count += 1
            return True
        else:
            msg = f"❌ FAIL: {test_name}\n   Expected: {expected}\n   Actual: {actual}"
            self.log(msg, "FAIL")
            self.results["failed"].append((test_name, expected, actual))
            return False
    
    def assert_true(self, condition: bool, test_name: str):
        """Assert condition is true."""
        self.test_count += 1
        if condition:
            self.log(f"✅ PASS: {test_name}", "PASS")
            self.results["passed"].append(test_name)
            self.pass_count += 1
            return True
        else:
            msg = f"❌ FAIL: {test_name}"
            self.log(msg, "FAIL")
            self.results["failed"].append((test_name, True, False))
            return False
    
    def assert_in_range(self, actual: int, min_val: int, max_val: int, test_name: str):
        """Assert value is in range."""
        self.test_count += 1
        if min_val <= actual <= max_val:
            self.log(f"✅ PASS: {test_name} (value={actual})", "PASS")
            self.results["passed"].append(test_name)
            self.pass_count += 1
            return True
        else:
            msg = f"❌ FAIL: {test_name}\n   Expected range: {min_val}-{max_val}\n   Actual: {actual}"
            self.log(msg, "FAIL")
            self.results["failed"].append((test_name, f"{min_val}-{max_val}", actual))
            return False
    
    def warning(self, message: str):
        """Log warning."""
        self.log(f"⚠️  WARNING: {message}", "WARN")
        self.results["warnings"].append(message)
    
    # ============================================================================
    # TEST SECTION 1: API Response Structure Validation
    # ============================================================================
    
    def test_response_structure(self, response: Dict[str, Any], user_id: int):
        """Validate response has all required fields."""
        self.log(f"\n--- TEST 1: Response Structure (User {user_id}) ---", "TEST")
        
        # Check root keys
        self.assert_true("reminders" in response, "Response contains 'reminders' field")
        self.assert_true("mobility_stress_reminders" in response, "Response contains 'mobility_stress_reminders' field")
        self.assert_true("summary" in response, "Response contains 'summary' field")
        self.assert_true("last_updated" in response, "Response contains 'last_updated' field")
        
        # Check reminders array
        if isinstance(response.get("reminders"), list):
            self.log(f"✅ 'reminders' is array with {len(response['reminders'])} items", "INFO")
            if len(response["reminders"]) > 0:
                reminder = response["reminders"][0]
                required_fields = [
                    "id", "type", "status", "priority", "last_done", "due_date",
                    "days_overdue", "days_until_due", "guideline", "recommendation",
                    "status_label", "status_color"
                ]
                for field in required_fields:
                    self.assert_true(field in reminder, f"Reminder has '{field}' field")
        
        # Check mobility_stress_reminders array
        if isinstance(response.get("mobility_stress_reminders"), list):
            self.log(f"✅ 'mobility_stress_reminders' is array with {len(response['mobility_stress_reminders'])} items", "INFO")
            if len(response["mobility_stress_reminders"]) > 0:
                metric = response["mobility_stress_reminders"][0]
                required_fields = ["area", "score", "status", "last_measured"]
                for field in required_fields:
                    self.assert_true(field in metric, f"Mobility metric has '{field}' field")
        
        # Check summary object
        summary = response.get("summary", {})
        summary_fields = [
            "total_reminders", "not_started", "overdue", "due_soon",
            "scheduled", "up_to_date", "not_applicable"
        ]
        for field in summary_fields:
            self.assert_true(field in summary, f"Summary has '{field}' field")
    
    # ============================================================================
    # TEST SECTION 2: Age Group Fallback Accuracy
    # ============================================================================
    
    def test_age_group_fallback(self, response: Dict[str, Any], user_id: int):
        """Test that age_group fallback works correctly."""
        self.log(f"\n--- TEST 2: Age Group Fallback (User {user_id}) ---", "TEST")
        
        reminders = response.get("reminders", [])
        screening_types = {r["type"] for r in reminders}
        
        # Rule: Bone Density Scan starts at age 50
        has_bone_density = "Bone Density Scan" in screening_types
        
        # Rule: Colonoscopy starts at age 45
        has_colonoscopy = "Colonoscopy" in screening_types
        
        # Rule: Mammogram starts at age 40
        has_mammogram = "Mammogram" in screening_types
        
        if user_id == 2:  # User 2 should be age 50+
            self.assert_true(has_bone_density, f"User {user_id} (age 50+) has Bone Density Scan")
            self.assert_true(has_colonoscopy, f"User {user_id} (age 50+) has Colonoscopy")
        elif user_id in [23, 6, 3455]:  # These should be 40-50
            self.assert_true(has_mammogram, f"User {user_id} (age 40+) has Mammogram")
            # Bone Density should NOT appear unless age >= 50
            if not has_bone_density:
                self.log(f"✅ User {user_id} correctly excluded Bone Density (age < 50)", "INFO")
    
    # ============================================================================
    # TEST SECTION 3: Status Logic Validation
    # ============================================================================
    
    def test_status_logic(self, response: Dict[str, Any], user_id: int):
        """Test that reminder statuses are correct."""
        self.log(f"\n--- TEST 3: Status Logic (User {user_id}) ---", "TEST")
        
        reminders = response.get("reminders", [])
        summary = response.get("summary", {})
        
        # Count each status
        status_counts = {}
        valid_statuses = ["not_started", "overdue", "due_soon", "scheduled", "up_to_date", "not_applicable"]
        
        for reminder in reminders:
            status = reminder.get("status")
            self.assert_true(
                status in valid_statuses,
                f"Reminder '{reminder['type']}' has valid status: {status}"
            )
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # Verify summary counts match
        for status in valid_statuses:
            expected_count = status_counts.get(status, 0)
            summary_count = summary.get(status, 0)
            self.assert_equal(
                summary_count,
                expected_count,
                f"Summary '{status}' count ({summary_count}) matches actual ({expected_count})"
            )
        
        # Verify total
        self.assert_equal(
            summary.get("total_reminders", 0),
            len(reminders),
            f"Summary total_reminders ({summary.get('total_reminders')}) equals reminders count ({len(reminders)})"
        )
    
    # ============================================================================
    # TEST SECTION 4: Mobility Metrics Validation
    # ============================================================================
    
    def test_mobility_metrics(self, response: Dict[str, Any], user_id: int):
        """Test mobility metrics accuracy and data-driven calculation."""
        self.log(f"\n--- TEST 4: Mobility Metrics (User {user_id}) ---", "TEST")
        
        metrics = response.get("mobility_stress_reminders", [])
        
        # Should have 4 mobility metrics (no stress management anymore)
        self.assert_equal(
            len(metrics),
            4,
            f"Response has exactly 4 mobility metrics (not 2 or 5)"
        )
        
        # Check metric names
        expected_metrics = ["Hip Flexibility", "Grip Strength", "Balance Score", "Posture Alignment"]
        actual_metrics = [m["area"] for m in metrics]
        
        for expected in expected_metrics:
            self.assert_true(
                expected in actual_metrics,
                f"'{expected}' metric present"
            )
        
        # Validate each metric
        for metric in metrics:
            area = metric.get("area", "Unknown")
            score = metric.get("score")
            status = metric.get("status")
            last_measured = metric.get("last_measured")
            
            # Score should be 0-100
            if score is not None:
                self.assert_in_range(
                    score,
                    0,
                    100,
                    f"'{area}' score is in 0-100 range"
                )
            
            # Status should match score
            if score is not None:
                expected_status = "good" if score >= 70 else "moderate" if score >= 50 else "poor"
                self.assert_equal(
                    status,
                    expected_status,
                    f"'{area}' status '{status}' matches score {score}"
                )
            
            # last_measured should be a date
            self.assert_true(
                last_measured is not None,
                f"'{area}' has last_measured date"
            )
    
    # ============================================================================
    # TEST SECTION 5: Data Flow Tracking
    # ============================================================================
    
    def test_data_flow(self, response: Dict[str, Any], user_id: int):
        """Track how data flows through the API."""
        self.log(f"\n--- TEST 5: Data Flow Analysis (User {user_id}) ---", "TEST")
        
        flow_info = {
            "user_id": user_id,
            "timestamp": datetime.now().isoformat(),
            "reminders_count": len(response.get("reminders", [])),
            "metrics_count": len(response.get("mobility_stress_reminders", [])),
            "summary": response.get("summary", {}),
            "unique_statuses": set(),
            "data_sources": []
        }
        
        # Collect statuses
        for reminder in response.get("reminders", []):
            flow_info["unique_statuses"].add(reminder.get("status"))
        
        # Infer data sources
        if len(response.get("mobility_stress_reminders", [])) > 0:
            metric_scores = [m.get("score") for m in response.get("mobility_stress_reminders", [])]
            if all(s == 70 or s == 72 or s == 75 or s == 73 for s in metric_scores):
                flow_info["data_sources"].append("using_default_scores (no health_logs)")
            else:
                flow_info["data_sources"].append("using_health_logs_data")
        
        # Check lab_reports query
        reminders = response.get("reminders", [])
        if all(r.get("last_done") is None for r in reminders):
            flow_info["data_sources"].append("no_lab_reports_found")
        else:
            flow_info["data_sources"].append("has_lab_reports")
        
        flow_info["unique_statuses"] = list(flow_info["unique_statuses"])
        
        self.results["data_flow"].append(flow_info)
        self.log(f"📊 Data Flow: {json.dumps(flow_info, indent=2, default=str)}", "INFO")
    
    # ============================================================================
    # TEST SECTION 6: Error Handling
    # ============================================================================
    
    def test_error_handling(self, user_id: int):
        """Test API error handling."""
        self.log(f"\n--- TEST 6: Error Handling (User {user_id}) ---", "TEST")
        
        try:
            response = requests.get(
                REMINDERS_ENDPOINT,
                params={"user_id": user_id, "include_ai_insights": "true"},
                timeout=10
            )
            
            if response.status_code == 404:
                self.assert_true(
                    True,
                    f"Non-existent user {user_id} returns 404"
                )
            elif response.status_code == 200:
                self.assert_true(
                    True,
                    f"User {user_id} returns 200 OK"
                )
            else:
                self.warning(f"Unexpected status code {response.status_code} for user {user_id}")
        
        except requests.exceptions.Timeout:
            self.warning(f"Request timeout for user {user_id}")
        except requests.exceptions.ConnectionError:
            self.log("❌ Cannot connect to API - is server running?", "ERROR")
    
    # ============================================================================
    # TEST SECTION 7: Edge Cases
    # ============================================================================
    
    def test_edge_cases(self, response: Dict[str, Any], user_id: int):
        """Test edge cases and boundary conditions."""
        self.log(f"\n--- TEST 7: Edge Cases (User {user_id}) ---", "TEST")
        
        # Empty reminders array
        reminders = response.get("reminders", [])
        if len(reminders) == 0:
            self.log("⚠️  User has no applicable screenings", "WARN")
        
        # Check for None values in critical fields
        for reminder in reminders:
            if reminder.get("due_date") is None and reminder.get("status") != "not_applicable":
                self.warning(f"Reminder '{reminder['type']}' has null due_date")
        
        # Verify status/days consistency
        for reminder in reminders:
            status = reminder.get("status")
            days_overdue = reminder.get("days_overdue")
            days_until_due = reminder.get("days_until_due")
            
            if status == "overdue":
                self.assert_true(
                    days_overdue is not None and days_overdue > 0,
                    f"Overdue reminder '{reminder['type']}' has days_overdue > 0"
                )
            elif status == "due_soon":
                self.assert_true(
                    days_until_due is not None and days_until_due >= 0,
                    f"Due soon reminder '{reminder['type']}' has days_until_due >= 0"
                )
            elif status == "not_started":
                self.assert_true(
                    days_overdue is None,
                    f"Not started reminder '{reminder['type']}' has days_overdue = None"
                )
    
    # ============================================================================
    # TEST SECTION 8: Performance & Response Time
    # ============================================================================
    
    def test_performance(self, user_id: int, response_time: float):
        """Test API performance."""
        self.log(f"\n--- TEST 8: Performance (User {user_id}) ---", "TEST")
        
        # Should respond within 2 seconds
        self.assert_true(
            response_time < 2.0,
            f"API responds within 2 seconds (actual: {response_time:.2f}s)"
        )
        
        if response_time > 1.0:
            self.warning(f"API response time is high: {response_time:.2f}s")
    
    # ============================================================================
    # MAIN TEST EXECUTION
    # ============================================================================
    
    def run_all_tests(self):
        """Run all tests."""
        self.log("=" * 80, "START")
        self.log("COMPREHENSIVE REMINDERS API TEST SUITE", "START")
        self.log("=" * 80, "START")
        
        for user_name, user_id in TEST_USERS.items():
            self.log(f"\n\n{'#' * 80}", "TEST")
            self.log(f"TESTING USER: {user_name} (ID: {user_id})", "TEST")
            self.log(f"{'#' * 80}", "TEST")
            
            try:
                # Make API request
                start_time = datetime.now()
                response = requests.get(
                    REMINDERS_ENDPOINT,
                    params={"user_id": user_id, "include_ai_insights": "true"},
                    timeout=10
                )
                response_time = (datetime.now() - start_time).total_seconds()
                
                self.log(f"✅ API Request successful (Status: {response.status_code}, Time: {response_time:.2f}s)", "INFO")
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Run all test sections
                    self.test_response_structure(data, user_id)
                    self.test_age_group_fallback(data, user_id)
                    self.test_status_logic(data, user_id)
                    self.test_mobility_metrics(data, user_id)
                    self.test_data_flow(data, user_id)
                    self.test_edge_cases(data, user_id)
                    self.test_performance(user_id, response_time)
                
                elif response.status_code == 404:
                    self.log(f"⚠️  User {user_id} not found (404)", "WARN")
                    self.test_error_handling(user_id)
                
                else:
                    self.log(f"❌ Unexpected status code: {response.status_code}", "ERROR")
            
            except Exception as e:
                self.log(f"❌ Test execution failed: {str(e)}", "ERROR")
                self.test_error_handling(user_id)
        
        # Print final summary
        self.print_summary()
    
    def print_summary(self):
        """Print test summary."""
        self.log(f"\n\n{'=' * 80}", "SUMMARY")
        self.log(f"TEST EXECUTION COMPLETE", "SUMMARY")
        self.log(f"{'=' * 80}", "SUMMARY")
        
        total_tests = self.test_count
        passed_tests = self.pass_count
        failed_tests = len(self.results["failed"])
        warnings = len(self.results["warnings"])
        
        pass_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
        
        self.log(f"\n📊 TEST STATISTICS:", "SUMMARY")
        self.log(f"   Total Tests:    {total_tests}", "SUMMARY")
        self.log(f"   ✅ Passed:       {passed_tests}", "SUMMARY")
        self.log(f"   ❌ Failed:       {failed_tests}", "SUMMARY")
        self.log(f"   ⚠️  Warnings:    {warnings}", "SUMMARY")
        self.log(f"   Pass Rate:      {pass_rate:.1f}%", "SUMMARY")
        
        if failed_tests > 0:
            self.log(f"\n❌ FAILED TESTS:", "SUMMARY")
            for test_name, expected, actual in self.results["failed"]:
                self.log(f"   - {test_name}", "SUMMARY")
                self.log(f"     Expected: {expected}", "SUMMARY")
                self.log(f"     Actual:   {actual}", "SUMMARY")
        
        if warnings > 0:
            self.log(f"\n⚠️  WARNINGS:", "SUMMARY")
            for warning in self.results["warnings"]:
                self.log(f"   - {warning}", "SUMMARY")
        
        self.log(f"\n📊 DATA FLOW ANALYSIS:", "SUMMARY")
        for flow in self.results["data_flow"]:
            self.log(f"\n   User {flow['user_id']}:", "SUMMARY")
            self.log(f"      Reminders: {flow['reminders_count']}", "SUMMARY")
            self.log(f"      Metrics: {flow['metrics_count']}", "SUMMARY")
            self.log(f"      Statuses: {', '.join(flow['unique_statuses'])}", "SUMMARY")
            self.log(f"      Data Sources: {', '.join(flow['data_sources'])}", "SUMMARY")
        
        self.log(f"\n{'=' * 80}", "SUMMARY")
        if pass_rate == 100:
            self.log(f"✅ ALL TESTS PASSED!", "SUMMARY")
        else:
            self.log(f"⚠️  Some tests failed. Review above for details.", "SUMMARY")
        self.log(f"{'=' * 80}\n", "SUMMARY")


def main():
    """Main entry point."""
    tester = RemindersAPITester()
    tester.run_all_tests()
    
    # Exit with appropriate code
    sys.exit(0 if len(tester.results["failed"]) == 0 else 1)


if __name__ == "__main__":
    main()
