"""
Service layer for Lifelong Thriving feature.
Handles:
- Vitality Index calculation (multi-year, weighted ML algorithm)
- Life Arc Timeline generation (milestone detection + Claude descriptions)
- Preventative Health Reminders (guideline-based, dynamic status)
"""

import logging
import json
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple, Any
from collections import defaultdict
import math

from ai.models.lifelong_thriving_models import (
    VitalityResponse, VitalityDimension, YearlyVitalityTrend, VitalityAIInsights,
    LifeArcResponse, Milestone, TimelineSummary, MilestoneHealthContext,
    RemindersResponse, HealthReminder, ReminderStatus, RemindersSnapshot,
    MobilityStressMetric
)
from ai.utils.db import query_db
from ai.utils.mock_data import mock_query_db
from ai.utils.claude_llm import ClaudeLLM
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Flag to enable/disable mock data
USE_MOCK_DATA = False  # Use real AWS RDS database


# ============================================================================
# VITALITY SERVICE
# ============================================================================

class VitalityService:
    """Calculate multi-year vitality index and health dimensions."""
    
    # Vitality level thresholds
    VITALITY_LEVELS = {
        (85, 101): "Thriving",
        (70, 85): "Strong",
        (55, 70): "Moderate",
        (40, 55): "Low",
        (0, 40): "Critical"
    }
    
    # Dimension weights (must sum to 1.0)
    DIMENSION_WEIGHTS = {
        "Mobility & Strength": 0.20,
        "Cardiovascular Health": 0.20,
        "Cognitive Wellness": 0.15,
        "Sleep Quality": 0.15,
        "Emotional Wellbeing": 0.15,
        "Metabolic Health": 0.10,
        "Reproductive Health": 0.05,  # If applicable
    }
    
    # Testing threshold: 30 days (will change to 365 days in production)
    ELIGIBILITY_DAYS_THRESHOLD = 30
    
    def __init__(self, user_id: int, years_back: int = 6):
        self.user_id = user_id
        self.years_back = years_back
        self.claude = ClaudeLLM()
    
    def _check_user_eligibility(self) -> Tuple[bool, str]:
        """
        Check if user is eligible for Lifelong Thriving feature.
        Requires: Account age >= ELIGIBILITY_DAYS_THRESHOLD (30 days for testing, 365 days for production)
        
        Returns: (is_eligible: bool, message: str)
        """
        try:
            db_query = mock_query_db if USE_MOCK_DATA else query_db
            
            # Try multiple column name variants (created_at, createdAt, created_date)
            queries = [
                "SELECT created_at FROM users WHERE id = %s",
                "SELECT createdAt FROM users WHERE id = %s",
                "SELECT created_date FROM users WHERE id = %s",
            ]
            
            result = None
            created_at = None
            
            for attempt, query in enumerate(queries):
                try:
                    logger.info(f"   🔍 Eligibility attempt {attempt+1}: {query}")
                    result = db_query(query, (self.user_id,))
                    if result:
                        created_at = result[0].get(list(result[0].keys())[0])  # Get first column value
                        logger.info(f"   ✓ Found user with created_at: {created_at}")
                        break
                except Exception as e:
                    logger.debug(f"   ⚠️  Query attempt {attempt+1} failed: {e}")
                    continue
            
            if not result or not created_at:
                # Fail closed - a missing/unreadable created_at must not grant
                # access, otherwise the account-age gate is bypassed entirely.
                logger.warning(f"   ⚠️  Could not verify user {self.user_id} eligibility - denying access")
                return False, f"User {self.user_id} not found or account age could not be verified"
            
            # Check if account is old enough (30 days for testing)
            threshold_date = datetime.now() - timedelta(days=self.ELIGIBILITY_DAYS_THRESHOLD)
            
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at)
            elif isinstance(created_at, date) and not isinstance(created_at, datetime):
                created_at = datetime.combine(created_at, datetime.min.time())
            
            if created_at > threshold_date:
                days_until_eligible = (threshold_date - created_at).days
                return False, f"Account age requirement: Come back in {abs(days_until_eligible)} days"
            
            return True, "User eligible"
            
        except Exception as e:
            logger.error(f"Error checking user eligibility: {e}")
            # Fail closed - a broken eligibility check must not grant access.
            return False, f"Eligibility check failed: {str(e)}"
    
    def _calculate_data_completeness(self, user_data: Dict) -> float:
        """
        Calculate what % of available data sources the user has.
        
        Data sources: health_logs, health_trends, lab_reports, menstrual_cycles, 
                      terra_activity_data, profile
        
        Returns: 0-100 percentage score
        """
        total_sources = 6
        present_sources = 0
        
        if user_data.get("health_logs"):
            present_sources += 1
        if user_data.get("health_trends"):
            present_sources += 1
        if user_data.get("lab_reports"):
            present_sources += 1
        if user_data.get("menstrual_cycles"):
            present_sources += 1
        if user_data.get("terra_activity_data"):
            present_sources += 1
        if user_data.get("profile"):
            present_sources += 1
        
        completeness = (present_sources / total_sources) * 100
        return round(completeness, 1)
    
    def get_vitality_overview(self) -> VitalityResponse:
        """Generate complete vitality response."""
        print(f"\n\n{'='*80}\n[VITALITY] START get_vitality_overview user_id={self.user_id}")
        
        try:
            logger.info(f"🔵 [1/8] Checking eligibility for user {self.user_id}")
            print(f"[VITALITY] [1] Eligibility check started")
            # Check eligibility first
            is_eligible, eligibility_message = self._check_user_eligibility()
            if not is_eligible:
                logger.warning(f"User {self.user_id} ineligible: {eligibility_message}")
                return self._get_fallback_vitality_response("ineligible", eligibility_message)
            
            logger.info(f"🟢 [2/8] Fetching health data for user {self.user_id}")
            # Fetch all user health data
            try:
                user_data = self._fetch_user_health_data()
                logger.info(f"   User data fetched: {len(user_data)} keys")
            except Exception as e:
                logger.error(f"   ERROR fetching user data: {e}")
                raise
            
            logger.info(f"🟢 [3/8] Calculating yearly trends...")
            try:
                # Calculate yearly vitality trend
                trend_data = self._calculate_yearly_trends(user_data)
                logger.info(f"   Trends calculated: {len(trend_data)} years")
            except Exception as e:
                logger.error(f"   ERROR calculating trends: {e}")
                trend_data = []
            
            logger.info(f"🟢 [4/8] Calculating dimensions...")
            print(f"[VITALITY] [4] About to calculate dimensions, user_data keys: {list(user_data.keys())}")
            try:
                # Calculate current dimensions
                dimensions = self._calculate_dimensions(user_data)
                print(f"[VITALITY] [4] Dimensions calculated: {len(dimensions)} returned")
                if dimensions:
                    print(f"[VITALITY] [4] First dimension: {dimensions[0].name if dimensions else 'NONE'}")
                logger.info(f"   Dimensions calculated: {len(dimensions)} dimensions")
            except Exception as e:
                logger.error(f"   ERROR calculating dimensions: {e}")
                print(f"[VITALITY] [4] ERROR in _calculate_dimensions: {e}")
                import traceback
                print(traceback.format_exc())
                dimensions = []
            
            logger.info(f"🟢 [5/8] Calculating vitality index...")
            try:
                # Calculate overall vitality index
                vitality_index = self._calculate_vitality_index(dimensions)
                logger.info(f"   Vitality index: {vitality_index}")
            except Exception as e:
                logger.error(f"   ERROR calculating vitality index: {e}")
                vitality_index = 50.0
            
            logger.info(f"🟢 [6/8] Getting vitality level...")
            try:
                # Determine vitality level
                vitality_level = self._get_vitality_level(vitality_index)
                logger.info(f"   Vitality level: {vitality_level}")
            except Exception as e:
                logger.error(f"   ERROR getting vitality level: {e}")
                vitality_level = "Unknown"
            
            logger.info(f"🟢 [7/8] Generating personal statement...")
            try:
                # Generate personal statement
                personal_best = self._generate_personal_statement(
                    vitality_index, vitality_level, dimensions
                )
                logger.info(f"   Personal statement: {personal_best}")
            except Exception as e:
                logger.error(f"   ERROR generating personal statement: {e}")
                personal_best = "Health profile being assessed"
            
            logger.info(f"🟢 [8/8] Generating AI insights...")
            try:
                # Get AI insights if requested
                ai_insights = self._generate_ai_insights(
                    vitality_index, dimensions, trend_data, user_data
                )
                logger.info(f"   AI insights generated successfully")
            except Exception as e:
                logger.error(f"   ERROR generating AI insights: {e}")
                ai_insights = None
            
            # Calculate data completeness
            try:
                data_completeness = self._calculate_data_completeness(user_data)
            except Exception as e:
                logger.error(f"   ERROR calculating data completeness: {e}")
                data_completeness = 0.0
            
            logger.info(f"✅ Vitality overview complete for user {self.user_id}")
            print(f"[VITALITY] [RESPONSE] About to create VitalityResponse with {len(dimensions)} dimensions")
            
            response = VitalityResponse(
                vitality_index=vitality_index,
                vitality_level=vitality_level,
                personal_best=personal_best,
                trend_6_years=trend_data,
                dimensions=dimensions,
                ai_insights=ai_insights,
                eligibility_status="eligible",
                data_completeness=data_completeness
            )
            
            print(f"[VITALITY] [RESPONSE] VitalityResponse created successfully, dims in response: {len(response.dimensions)}")
            print(f"[VITALITY] [SUCCESS] Returning valid response")
            
            return response
        except Exception as e:
            import traceback
            error_msg = f"❌ ERROR calculating vitality for user {self.user_id}: {e}\nTraceback: {traceback.format_exc()}"
            logger.error(error_msg)
            print(f"[VITALITY] [OUTER_EXCEPTION] {error_msg}")
            print(traceback.format_exc())
            print(f"[VITALITY] [FALLBACK] Returning fallback response")
            # Return fallback response
            return self._get_fallback_vitality_response("check_failed", str(e))
    
    def _fetch_user_health_data(self) -> Dict[str, Any]:
        """Fetch all health data for vitality calculation."""
        data = {
            "health_logs": [],
            "health_trends": [],
            "lab_reports": [],
            "menstrual_cycles": [],
            "health_goals": [],
            "profile": {}
        }
        
        # Use mock data if enabled
        db_query = mock_query_db if USE_MOCK_DATA else query_db
        
        try:
            logger.info(f"🔍 FETCHING DATA FOR USER {self.user_id} (years_back={self.years_back}, use_mock={USE_MOCK_DATA})")
            
            # Fetch health logs (mood, energy, symptoms)
            query = """
                SELECT DATE(log_date) as log_date, mood, energy_level, symptoms, notes
                FROM health_logs
                WHERE user_id = %s AND log_date >= DATE_SUB(NOW(), INTERVAL %s YEAR)
                ORDER BY log_date DESC
            """
            try:
                data["health_logs"] = db_query(query, (self.user_id, self.years_back))
                logger.info(f"   ✓ health_logs: {len(data['health_logs'])} records found")
                if data["health_logs"]:
                    logger.info(f"     First log: {data['health_logs'][0]}")
                else:
                    logger.warning(f"   ⚠️  NO health logs found for user {self.user_id}")
            except Exception as e:
                logger.error(f"   ❌ health_logs query failed: {e}")
                import traceback
                logger.error(traceback.format_exc())
            
            # Fetch health trends
            query = """
                SELECT period, trend_data
                FROM health_trends
                WHERE user_id = %s
                ORDER BY period DESC
                LIMIT 100
            """
            data["health_trends"] = db_query(query, (self.user_id,))
            
            # Fetch lab reports
            query = """
                SELECT test_type, biomarkers, analysis_status, created_at
                FROM lab_reports
                WHERE user_id = %s AND created_at >= DATE_SUB(NOW(), INTERVAL %s YEAR)
                ORDER BY created_at DESC
            """
            data["lab_reports"] = db_query(query, (self.user_id, self.years_back))
            logger.info(f"   ✓ lab_reports: {len(data['lab_reports'])} records found")
            
            # Fetch menstrual cycle data
            query = """
                SELECT period_start_date, current_phase, cycle_length
                FROM menstrual_cycles
                WHERE user_id = %s AND period_start_date >= DATE_SUB(NOW(), INTERVAL %s YEAR)
                ORDER BY period_start_date DESC
                LIMIT 100
            """
            data["menstrual_cycles"] = db_query(query, (self.user_id, self.years_back))
            logger.info(f"   ✓ menstrual_cycles: {len(data['menstrual_cycles'])} records found")
            
            # Fetch user profile
            query = """
                SELECT p.activity_level, p.life_stage, p.age_group, u.date_of_birth
                FROM profiles p
                JOIN users u ON p.user_id = u.id
                WHERE p.user_id = %s
            """
            profile = db_query(query, (self.user_id,))
            data["profile"] = profile[0] if profile else {}
            logger.info(f"   ✓ profile: {bool(data['profile'])}")
            
            # Fetch sleep & activity data from terra_activity_data
            query = """
                SELECT DATE(created_at) as activity_date, type, payload
                FROM terra_activity_data
                WHERE user_id = %s AND created_at >= DATE_SUB(NOW(), INTERVAL %s YEAR)
                ORDER BY created_at DESC
                LIMIT 500
            """
            try:
                data["terra_activity_data"] = db_query(query, (self.user_id, self.years_back))
                logger.info(f"   ✓ terra_activity_data: {len(data['terra_activity_data'])} records found")
            except Exception as e:
                logger.warning(f"   ⚠️  terra_activity_data query failed: {e}")
                data["terra_activity_data"] = []
            
            return data
        except Exception as e:
            logger.error(f"Error fetching health data: {e}")
            return data
    
    def _calculate_yearly_trends(self, user_data: Dict) -> List[YearlyVitalityTrend]:
        """Calculate vitality score for each year."""
        trends = []
        
        if not user_data["health_logs"]:
            return trends
        
        # Group health logs by year
        logs_by_year = defaultdict(list)
        for log in user_data["health_logs"]:
            year = log["log_date"].year
            logs_by_year[year].append(log)
        
        # Calculate score for each year
        current_date = datetime.now()
        for year in sorted(logs_by_year.keys(), reverse=True):
            if len(trends) >= self.years_back:
                break
            
            year_logs = logs_by_year[year]
            
            # Calculate yearly vitality from health logs
            yearly_score = self._calculate_score_from_logs(year_logs)
            
            trends.append(
                YearlyVitalityTrend(
                    year=year,
                    score=yearly_score,
                    data_points=len(year_logs)
                )
            )
        
        # Fill missing years with interpolation if needed
        trends = sorted(trends, key=lambda x: x.year)
        return trends
    
    def _calculate_score_from_logs(self, logs: List[Dict]) -> float:
        """Calculate vitality score from health logs."""
        if not logs:
            return 50.0
        
        scores = []
        
        # Map ENUM energy levels to scores
        energy_map = {
            "Very Low": 20,
            "Low": 40,
            "Moderate": 60,
            "High": 80,
            "Very High": 100
        }
        
        for log in logs:
            # Energy level is ENUM string
            energy_raw = log.get("energy_level", "Moderate")
            energy_score = energy_map.get(str(energy_raw), 60)
            
            # Mood from varchar (try to parse as number or use string mapping)
            mood_raw = log.get("mood", "5")
            try:
                # Try to parse as numeric (1-10 scale)
                mood_val = float(mood_raw)
                mood_score = (mood_val / 10) * 100
            except:
                # If not numeric, use string mapping
                mood_map = {"1": 10, "2": 20, "3": 30, "4": 40, "5": 50, "6": 60, "7": 70, "8": 80, "9": 90, "10": 100}
                mood_score = mood_map.get(str(mood_raw), 60)
            
            # Combine with emphasis on mood and energy
            log_score = (mood_score * 0.5 + energy_score * 0.5)
            scores.append(log_score)
        
        return sum(scores) / len(scores) if scores else 50.0
    
    def _calculate_dimensions(self, user_data: Dict) -> List[VitalityDimension]:
        """Calculate individual health dimensions."""
        dimensions = []
        print(f"[VITALITY] [_calculate_dimensions START] user_data keys: {list(user_data.keys())}")
        logger.info(f"📊 CALCULATING DIMENSIONS (logs={len(user_data.get('health_logs', []))}, cycles={len(user_data.get('menstrual_cycles', []))})")
        
        # Mobility & Strength - from activity level and health logs
        mobility_score = 60  # Default
        try:
            mobility_score = self._calculate_mobility_score(user_data)
            logger.info(f"   ✓ Mobility & Strength: {mobility_score}")
        except Exception as e:
            logger.error(f"   ❌ Mobility calculation failed: {e}, using default")
            mobility_score = 60
        
        try:
            dim = VitalityDimension(
                name="Mobility & Strength",
                score=float(mobility_score),
                status=self._get_status_from_score(mobility_score),
                trend="stable",
                last_updated=self._get_last_update_date(user_data.get("health_logs", [])),
                description="Based on activity levels and reported mobility"
            )
            dimensions.append(dim)
            print(f"[VITALITY] [APPEND] Mobility & Strength: score={mobility_score}, status={dim.status}")
        except Exception as e:
            logger.error(f"❌ Failed to create Mobility dimension: {e}")
            print(f"[VITALITY] [ERROR-APPEND] Mobility & Strength: {e}")
            import traceback
            print(traceback.format_exc())
        
        # Cardiovascular Health - from energy logs and lab data
        cardio_score = 60  # Default
        try:
            cardio_score = self._calculate_cardiovascular_score(user_data)
            logger.info(f"   ✓ Cardiovascular Health: {cardio_score}")
        except Exception as e:
            logger.error(f"   ❌ Cardiovascular calculation failed: {e}, using default")
            cardio_score = 60
        
        dimensions.append(VitalityDimension(
            name="Cardiovascular Health",
            score=float(cardio_score),
            status=self._get_status_from_score(cardio_score),
            trend="stable",
            last_updated=self._get_last_update_date(user_data.get("lab_reports", [])),
            description="Based on energy levels and cardiovascular biomarkers"
        ))
        
        # Cognitive Wellness - from focus/brain fog symptoms
        cognitive_score = 60  # Default
        try:
            cognitive_score = self._calculate_cognitive_score(user_data)
            logger.info(f"   ✓ Cognitive Wellness: {cognitive_score}")
        except Exception as e:
            logger.error(f"   ❌ Cognitive calculation failed: {e}, using default")
            cognitive_score = 60
        
        dimensions.append(VitalityDimension(
            name="Cognitive Wellness",
            score=float(cognitive_score),
            status=self._get_status_from_score(cognitive_score),
            trend="stable",
            last_updated=self._get_last_update_date(user_data.get("health_logs", [])),
            description="Based on focus, brain fog, and mental clarity"
        ))
        
        # Sleep Quality - from health trends and logs
        sleep_score = 60  # Default
        try:
            sleep_score = self._calculate_sleep_score(user_data)
            logger.info(f"   ✓ Sleep Quality: {sleep_score}")
        except Exception as e:
            logger.error(f"   ❌ Sleep calculation failed: {e}, using default")
            sleep_score = 60
        
        dimensions.append(VitalityDimension(
            name="Sleep Quality",
            score=float(sleep_score),
            status=self._get_status_from_score(sleep_score),
            trend="stable",
            last_updated=self._get_last_update_date(user_data.get("health_logs", [])),
            description="Based on sleep duration and quality patterns"
        ))
        
        # Emotional Wellbeing - from mood logs
        emotional_score = 60  # Default
        try:
            emotional_score = self._calculate_emotional_score(user_data)
            logger.info(f"   ✓ Emotional Wellbeing: {emotional_score}")
        except Exception as e:
            logger.error(f"   ❌ Emotional calculation failed: {e}, using default")
            emotional_score = 60
        
        dimensions.append(VitalityDimension(
            name="Emotional Wellbeing",
            score=float(emotional_score),
            status=self._get_status_from_score(emotional_score),
            trend="stable",
            last_updated=self._get_last_update_date(user_data.get("health_logs", [])),
            description="Based on mood patterns and emotional state"
        ))
        
        # Metabolic Health - from lab biomarkers
        metabolic_score = 60  # Default
        try:
            metabolic_score = self._calculate_metabolic_score(user_data)
            logger.info(f"   ✓ Metabolic Health: {metabolic_score}")
        except Exception as e:
            logger.error(f"   ❌ Metabolic calculation failed: {e}, using default")
            metabolic_score = 60
        
        dimensions.append(VitalityDimension(
            name="Metabolic Health",
            score=float(metabolic_score),
            status=self._get_status_from_score(metabolic_score),
            trend="stable",
            last_updated=self._get_last_update_date(user_data.get("lab_reports", [])),
            description="Based on metabolic biomarkers and lab results"
        ))
        
        # Reproductive Health - from cycle regularity
        repro_score = 60  # Default
        try:
            repro_score = self._calculate_reproductive_score(user_data)
            logger.info(f"   ✓ Reproductive Health: {repro_score}")
        except Exception as e:
            logger.error(f"   ❌ Reproductive calculation failed: {e}, using default")
            repro_score = 60
        
        dimensions.append(VitalityDimension(
            name="Reproductive Health",
            score=float(repro_score),
            status=self._get_status_from_score(repro_score),
            trend="stable",
            last_updated=self._get_last_update_date(user_data.get("menstrual_cycles", [])),
            description="Based on cycle regularity and hormone balance"
        ))
        
        logger.info(f"📊 Dimension calculation complete: {len(dimensions)} dimensions created")
        return dimensions
    
    def _calculate_mobility_score(self, user_data: Dict) -> float:
        """Calculate mobility & strength score from activity level and terra data."""
        scores = []
        
        # First try: Get from profile activity_level
        profile = user_data.get("profile", {})
        activity_level = profile.get("activity_level", "").lower() if profile else ""
        
        activity_map = {
            "sedentary": 30,
            "light": 50,
            "moderate": 70,
            "active": 85,
            "very_active": 95
        }
        
        if activity_level in activity_map:
            scores.append(activity_map[activity_level])
        
        # Second: Extract from terra_activity_data (steps, calories, etc.)
        terra_data = user_data.get("terra_activity_data", [])
        if terra_data:
            for record in terra_data[-30:]:  # Last 30 days
                try:
                    payload = record.get("payload", {})
                    if isinstance(payload, str):
                        import json
                        payload = json.loads(payload)
                    
                    # Check for activity indicators
                    calories = payload.get("calories_burned", 0) or payload.get("energy_expended", 0)
                    steps = payload.get("steps", 0)
                    
                    if calories > 2500 or steps > 10000:
                        scores.append(85)  # Very active
                    elif calories > 2000 or steps > 7000:
                        scores.append(75)  # Active
                    elif calories > 1500 or steps > 5000:
                        scores.append(65)  # Moderate
                    elif calories > 1000 or steps > 3000:
                        scores.append(50)  # Light
                    else:
                        scores.append(40)  # Sedentary
                except:
                    pass
        
        if scores:
            return sum(scores) / len(scores)
        return 60  # Default if no data
    
    def _calculate_cardiovascular_score(self, user_data: Dict) -> float:
        """Calculate cardiovascular health from energy, biomarkers, and activity."""
        scores = []
        
        # Map ENUM energy levels to scores
        energy_map = {
            "Very Low": 20,
            "Low": 40,
            "Moderate": 60,
            "High": 80,
            "Very High": 100
        }
        
        # Try health logs first
        health_logs = user_data.get("health_logs", [])
        if health_logs:
            for log in health_logs[-30:]:
                energy_raw = log.get("energy_level", "Moderate")
                energy_score = energy_map.get(str(energy_raw), 60)
                scores.append(energy_score)
        
        # Try lab biomarkers
        lab_reports = user_data.get("lab_reports", [])
        if lab_reports:
            for report in lab_reports:
                if "heart" in (report.get("panel", "") or "").lower() or "cardiovascular" in (report.get("panel", "") or "").lower():
                    scores.append(75)
        
        # Estimate from terra activity data (high activity = good cardiovascular)
        terra_data = user_data.get("terra_activity_data", [])
        if terra_data and not scores:  # Only if we don't have other data
            for record in terra_data[-30:]:
                try:
                    payload = record.get("payload", {})
                    if isinstance(payload, str):
                        import json
                        payload = json.loads(payload)
                    hr_avg = payload.get("heart_rate_average") or payload.get("avg_heart_rate", 70)
                    if 60 <= hr_avg <= 100:
                        scores.append(70)
                    elif hr_avg < 60:
                        scores.append(80)  # Athletic
                    else:
                        scores.append(60)
                except:
                    pass
        
        if scores:
            return sum(scores) / len(scores)
        return 60  # Default when no data available
    
    def _calculate_cognitive_score(self, user_data: Dict) -> float:
        """Calculate cognitive wellness from symptoms and notes."""
        scores = []
        
        health_logs = user_data.get("health_logs", [])
        if health_logs:
            for log in health_logs[-30:]:
                symptoms_data = log.get("symptoms", {})
                notes = log.get("notes", "")
                
                # Handle symptoms as JSON or string
                if isinstance(symptoms_data, str):
                    combined_text = symptoms_data + " " + notes
                elif isinstance(symptoms_data, dict):
                    combined_text = str(symptoms_data) + " " + notes
                else:
                    combined_text = notes
                
                # Check for cognitive indicators
                negative_keywords = ["brain fog", "confusion", "memory loss", "concentration", "confused", "fuzzy"]
                positive_keywords = ["focused", "clear", "sharp", "alert", "clarity"]
                
                score = 70  # Default baseline
                
                if combined_text:
                    combined_lower = combined_text.lower()
                    for keyword in negative_keywords:
                        if keyword in combined_lower:
                            score -= 10
                    for keyword in positive_keywords:
                        if keyword in combined_lower:
                            score += 10
                
                scores.append(max(0, min(100, score)))
        
        # Default when no logs available
        if scores:
            return sum(scores) / len(scores)
        return 65  # Neutral default
    
    def _calculate_sleep_score(self, user_data: Dict) -> float:
        """Calculate sleep quality from health logs, trends, and activity data."""
        scores = []
        
        # Check health logs for sleep notes
        health_logs = user_data.get("health_logs", [])
        for log in health_logs[-30:] if health_logs else []:
            notes = log.get("notes", "").lower()
            score = 70  # Default
            if "slept well" in notes or "good sleep" in notes:
                score = 85
            elif "insomnia" in notes or "restless" in notes:
                score = 40
            elif "tired" in notes or "exhausted" in notes:
                score = 35
            scores.append(score)
        
        # Check health trends
        health_trends = user_data.get("health_trends", [])
        for trend in health_trends[-12:] if health_trends else []:
            try:
                trend_data = trend.get("sleep_energy_correlation_chart") or trend.get("hormone_mood", {})
                if isinstance(trend_data, str):
                    import json
                    trend_data = json.loads(trend_data)
                if trend_data and isinstance(trend_data, dict):
                    scores.append(70)  # Has trend data = reasonable sleep
            except:
                pass
        
        # Estimate from terra activity (sleep tracking if available)
        terra_data = user_data.get("terra_activity_data", [])
        for record in terra_data[-30:] if terra_data else []:
            try:
                payload = record.get("payload", {})
                if isinstance(payload, str):
                    import json
                    payload = json.loads(payload)
                if "sleep" in payload:
                    sleep_data = payload["sleep"]
                    duration = sleep_data.get("duration", 0) if isinstance(sleep_data, dict) else 0
                    if duration >= 7 * 3600:  # 7+ hours
                        scores.append(85)
                    elif duration >= 6 * 3600:  # 6+ hours
                        scores.append(70)
                    elif duration >= 5 * 3600:  # 5+ hours
                        scores.append(50)
                    else:
                        scores.append(40)
            except:
                pass
        
        if scores:
            return sum(scores) / len(scores)
        return 65  # Default when no data available
    
    def _calculate_emotional_score(self, user_data: Dict) -> float:
        """Calculate emotional wellbeing from mood logs and notes."""
        scores = []
        
        health_logs = user_data.get("health_logs", [])
        if health_logs:
            for log in health_logs[-30:]:
                mood_raw = log.get("mood", "5")
                try:
                    # Try to parse as numeric (1-10 scale)
                    mood_val = float(mood_raw)
                    mood_score = (mood_val / 10) * 100
                except:
                    # If not numeric, use string mapping
                    mood_map = {"1": 10, "2": 20, "3": 30, "4": 40, "5": 50, "6": 60, "7": 70, "8": 80, "9": 90, "10": 100}
                    mood_score = mood_map.get(str(mood_raw), 60)
                
                scores.append(mood_score)
        
        # Check notes for emotional indicators
        for log in health_logs[-30:] if health_logs else []:
            notes = log.get("notes", "").lower()
            if notes:
                if any(word in notes for word in ["happy", "great", "awesome", "excited", "joyful"]):
                    scores.append(85)
                elif any(word in notes for word in ["sad", "anxious", "stressed", "depressed", "overwhelmed"]):
                    scores.append(40)
        
        if scores:
            return sum(scores) / len(scores)
        return 65  # Neutral default
    
    def _calculate_metabolic_score(self, user_data: Dict) -> float:
        """Calculate metabolic health from biomarkers and activity."""
        scores = []
        
        # Check lab reports
        lab_reports = user_data.get("lab_reports", [])
        for report in lab_reports:
            # Base score for having lab work done
            biomarkers = report.get("biomarkers", {})
            if biomarkers:
                scores.append(75)  # Has biomarker data
        
        # Estimate from activity data (consistent activity = healthy metabolism)
        terra_data = user_data.get("terra_activity_data", [])
        if terra_data and not scores:
            calorie_counts = []
            for record in terra_data[-30:]:
                try:
                    payload = record.get("payload", {})
                    if isinstance(payload, str):
                        import json
                        payload = json.loads(payload)
                    calories = payload.get("calories_burned", 0) or payload.get("energy_expended", 0)
                    if calories > 0:
                        calorie_counts.append(calories)
                except:
                    pass
            
            if calorie_counts:
                avg_calories = sum(calorie_counts) / len(calorie_counts)
                if avg_calories > 2000:
                    scores.append(75)
                elif avg_calories > 1500:
                    scores.append(65)
                else:
                    scores.append(55)
        
        if scores:
            return sum(scores) / len(scores)
        
        # Default if no data
        return 65
    
    def _calculate_reproductive_score(self, user_data: Dict) -> float:
        """Calculate reproductive health from cycle regularity."""
        cycles = user_data.get("menstrual_cycles", [])
        
        if not cycles or len(cycles) < 2:
            return 70  # Not enough data
        
        # Check cycle regularity
        cycle_lengths = []
        for i in range(1, len(cycles)):
            if cycles[i].get("period_start_date") and cycles[i-1].get("period_start_date"):
                length = (cycles[i-1]["period_start_date"] - cycles[i]["period_start_date"]).days
                if 21 <= length <= 35:  # Normal cycle range
                    cycle_lengths.append(length)
        
        if not cycle_lengths:
            return 60
        
        # Regular cycles = higher score
        avg_length = sum(cycle_lengths) / len(cycle_lengths)
        regularity = 100 - (sum(abs(l - avg_length) for l in cycle_lengths) / len(cycle_lengths))
        
        return max(50, min(100, regularity))
    
    def _calculate_vitality_index(self, dimensions: List[VitalityDimension]) -> float:
        """Calculate weighted overall vitality index."""
        total_score = 0
        
        for dimension in dimensions:
            weight = self.DIMENSION_WEIGHTS.get(dimension.name, 0)
            total_score += dimension.score * weight
        
        return round(total_score, 1)
    
    def _get_vitality_level(self, score: float) -> str:
        """Get vitality level label from score."""
        for (min_score, max_score), level in self.VITALITY_LEVELS.items():
            if min_score <= score < max_score:
                return level
        return "Unknown"
    
    def _get_status_from_score(self, score: float) -> str:
        """Get status from numeric score."""
        if score >= 85:
            return "thriving"
        elif score >= 70:
            return "strong"
        elif score >= 55:
            return "moderate"
        elif score >= 40:
            return "low"
        else:
            return "critical"
    
    def _get_last_update_date(self, data_list: List[Dict]) -> Optional[date]:
        """Get last update date from data list."""
        if not data_list:
            return None
        
        # Look for date fields
        for record in data_list:
            for date_field in ["log_date", "created_at", "period_start_date"]:
                if date_field in record and record[date_field]:
                    value = record[date_field]
                    # Convert datetime to date if needed
                    if hasattr(value, 'date'):  # It's a datetime object
                        return value.date()
                    return value
        
        return None
    
    def _generate_personal_statement(
        self, vitality_index: float, level: str, dimensions: List[VitalityDimension]
    ) -> str:
        """Generate contextual personal statement."""
        if vitality_index >= 85:
            return "Personal best — thriving at every level"
        elif vitality_index >= 70:
            return "Strong and steady — maintaining excellent health"
        elif vitality_index >= 55:
            return "Good foundation — opportunity to enhance wellness"
        else:
            return "Time to focus on health restoration"
    
    def _generate_ai_insights(
        self, vitality_index: float, dimensions: List[VitalityDimension],
        trend_data: List[YearlyVitalityTrend], user_data: Dict
    ) -> VitalityAIInsights:
        """Generate Claude AI insights about vitality based on available data."""
        try:
            # Build context for Claude
            dimension_text = "\n".join([
                f"- {d.name}: {d.score}/100 ({d.status})"
                for d in dimensions
            ])
            
            # Build trend text based on available data
            trend_text = "No historical trend data available yet"
            if trend_data:
                trend_text = "\n".join([
                    f"- {t.year}: {t.score}/100"
                    for t in sorted(trend_data, key=lambda x: x.year)
                ])
            
            # Calculate data coverage
            num_logs = len(user_data.get('health_logs', []))
            num_cycles = len(user_data.get('menstrual_cycles', []))
            num_labs = len(user_data.get('lab_reports', []))
            
            # Identify strongest and weakest dimensions
            sorted_dims = sorted(dimensions, key=lambda d: d.score, reverse=True)
            strengths_dims = sorted_dims[:2]
            focus_dims = sorted_dims[-2:]
            
            prompt = f"""
Analyze this user's health vitality profile and provide concise, actionable insights based on available data:

CURRENT VITALITY INDEX: {vitality_index}/100
LEVEL: {self._get_vitality_level(vitality_index)}

HEALTH DIMENSIONS (Current Scores):
{dimension_text}

HISTORICAL TREND (Available data):
{trend_text}

DATA COVERAGE:
- Health log entries: {num_logs}
- Menstrual cycle records: {num_cycles}
- Lab reports: {num_labs}

Based on the available data (more data will provide better insights over time), please provide:
1. A 2-3 sentence summary of current vitality based on available data
2. List 2-3 key strengths from the health dimensions
3. List 2-3 areas to focus on for improvement
4. Provide 2-3 specific, actionable recommendations

Format your response as JSON with keys: summary, strengths, areas_to_focus, recommendations
            """.strip()
            
            # Call Claude
            response = self.claude.chat(
                messages=[{"role": "user", "content": prompt}],
                system="You are a health analytics AI expert. Provide concise, data-driven insights about vitality and wellness. Be realistic about limited data scenarios.",
                max_tokens=1000
            )
            
            # Parse response
            import json
            response_text = response.content[0].text
            
            # Extract JSON from response
            try:
                start = response_text.find("{")
                end = response_text.rfind("}") + 1
                json_str = response_text[start:end]
                insights_data = json.loads(json_str)
            except Exception as parse_error:
                logger.warning(f"Could not parse Claude JSON response: {parse_error}. Using fallback.")
                insights_data = self._generate_fallback_insights(dimensions)
            
            return VitalityAIInsights(
                summary=insights_data.get("summary", self._generate_summary(vitality_index, dimensions)),
                strengths=insights_data.get("strengths", [d.name for d in strengths_dims]),
                areas_to_focus=insights_data.get("areas_to_focus", [d.name for d in focus_dims]),
                recommendations=insights_data.get("recommendations", self._generate_recommendations(dimensions)),
                confidence_score=90 if trend_data else 75
            )
        except Exception as e:
            logger.error(f"Error generating AI insights: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # Return fallback insights based on actual dimension data
            return self._generate_data_driven_insights(vitality_index, dimensions)
    
    def _generate_fallback_insights(self, dimensions: List[VitalityDimension]) -> Dict:
        """Generate insights based on dimension scores without Claude."""
        sorted_dims = sorted(dimensions, key=lambda d: d.score, reverse=True)
        strengths = [d.name for d in sorted_dims[:2]]
        areas = [d.name for d in sorted_dims[-2:]]
        
        return {
            "summary": f"Your vitality shows balanced health with some areas for growth.",
            "strengths": strengths,
            "areas_to_focus": areas,
            "recommendations": [
                "Track your health consistently to identify patterns",
                "Focus on the areas identified above",
                "Regular movement and sleep are foundational"
            ]
        }
    
    def _generate_data_driven_insights(self, vitality_index: float, dimensions: List[VitalityDimension]) -> VitalityAIInsights:
        """Generate insights based on dimension data without Claude."""
        sorted_dims = sorted(dimensions, key=lambda d: d.score, reverse=True)
        strengths = [d.name for d in sorted_dims[:2]]
        areas_to_focus = [d.name for d in sorted_dims[-2:]]
        
        vitality_level = self._get_vitality_level(vitality_index)
        
        return VitalityAIInsights(
            summary=f"Your vitality is currently {vitality_level}. Keep tracking your health—more data will provide deeper insights over time.",
            strengths=strengths if strengths else ["Consistent tracking"],
            areas_to_focus=areas_to_focus if areas_to_focus else ["Balanced wellness"],
            recommendations=self._generate_recommendations(dimensions),
            confidence_score=70
        )
    
    def _generate_summary(self, vitality_index: float, dimensions: List[VitalityDimension]) -> str:
        """Generate summary if Claude fails."""
        level = self._get_vitality_level(vitality_index)
        return f"Your current vitality level is {level} ({vitality_index}/100). Continue building your health data for personalized insights."
    
    def _generate_recommendations(self, dimensions: List[VitalityDimension]) -> List[str]:
        """Generate basic recommendations from dimensions."""
        weak_dims = sorted([d for d in dimensions if d.score < 60], key=lambda d: d.score)
        recs = []
        
        if weak_dims:
            for dim in weak_dims[:2]:
                if "Sleep" in dim.name:
                    recs.append("Prioritize consistent sleep schedule (7-9 hours nightly)")
                elif "Emotional" in dim.name:
                    recs.append("Practice stress management: meditation, journaling, or therapy")
                elif "Mobility" in dim.name:
                    recs.append("Increase daily movement: 30 mins of activity most days")
                elif "Cardiovascular" in dim.name:
                    recs.append("Add aerobic exercise: brisk walking, cycling, or swimming")
                elif "Cognitive" in dim.name:
                    recs.append("Enhance mental clarity: reduce screen time, improve sleep")
                else:
                    recs.append(f"Focus on {dim.name}: see health trends and adjust habits")
        
        if len(recs) < 2:
            recs.append("Maintain consistent health tracking for pattern detection")
        
        return recs[:3]
    
    def _get_fallback_vitality_response(self, eligibility_status: str = "check_failed", message: Optional[str] = None) -> VitalityResponse:
        """Return fallback response on ineligibility or error - must carry the
        real eligibility_status/message rather than the model's "eligible"
        default, otherwise callers can't tell this apart from a real result.
        """
        return VitalityResponse(
            vitality_index=0,
            vitality_level="Unknown",
            personal_best=message or "Unable to calculate vitality at this time",
            trend_6_years=[],
            dimensions=[],
            ai_insights=None,
            eligibility_status=eligibility_status,
            data_completeness=0.0
        )


# ============================================================================
# LIFE ARC SERVICE
# ============================================================================

class LifeArcService:
    """Generate life arc timeline with milestone detection."""
    
    def __init__(self, user_id: int, months_back: int = 6):
        self.user_id = user_id
        self.months_back = months_back
        self.claude = ClaudeLLM()
        # Route to mock data if enabled, otherwise real database
        self.db_query = mock_query_db if USE_MOCK_DATA else query_db
    
    def get_life_arc_timeline(self) -> LifeArcResponse:
        """Generate complete life arc timeline with enhanced milestones."""
        print(f"[LIFE_ARC] START get_life_arc_timeline user_id={self.user_id}")
        try:
            # Check eligibility first
            eligibility_status, is_eligible = self._check_eligibility()
            print(f"[LIFE_ARC] Eligibility: {eligibility_status}")
            
            # If not eligible, return empty response
            if not is_eligible:
                print(f"[LIFE_ARC] User not eligible - returning empty milestones")
                return LifeArcResponse(
                    milestones=[],
                    timeline_summary=TimelineSummary(
                        total_milestones=0,
                        major_events=0,
                        avg_monthly_milestones=0,
                        date_range={"start": date.today(), "end": date.today()}
                    )
                )
            
            # Detect milestones from all sources
            milestones = self._detect_milestones()
            print(f"[LIFE_ARC] Detected {len(milestones)} milestones")
            
            # Sort by date (reverse chronological)
            milestones = sorted(milestones, key=lambda m: m.date_, reverse=True)
            
            # Calculate summary
            summary = self._calculate_timeline_summary(milestones)
            
            response = LifeArcResponse(
                milestones=milestones,
                timeline_summary=summary
            )
            print(f"[LIFE_ARC] SUCCESS returning {len(milestones)} milestones")
            return response
        except Exception as e:
            logger.error(f"Error generating life arc: {e}")
            print(f"[LIFE_ARC] ERROR: {e}")
            import traceback
            print(traceback.format_exc())
            return LifeArcResponse(
                milestones=[],
                timeline_summary=TimelineSummary(
                    total_milestones=0,
                    major_events=0,
                    avg_monthly_milestones=0,
                    date_range={"start": date.today(), "end": date.today()}
                )
            )
    
    # ========== HELPER METHODS ==========
    
    def _check_eligibility(self) -> tuple:
        """Check if user has sufficient data for life-arc timeline.
        
        Milestones are detected from 6 different tables (menstrual_cycles,
        health_logs, lab_reports, terra_activity_data, health_goal_profile,
        profiles/life_journeys), so eligibility must consider all of them -
        not just cycles. Otherwise users without period-tracking data (e.g.
        pregnancy/postpartum, perimenopause) are wrongly blocked.
        
        MVP Threshold (Testing):
        - At least 1 record in ANY milestone data source
        
        Returns:
            (status: str, is_eligible: bool)
            - status: "eligible", "needs_more_data", or "check_failed"
            - is_eligible: True if user meets requirements
        """
        try:
            query = """
                SELECT
                    (SELECT COUNT(*) FROM menstrual_cycles WHERE user_id = %s) AS cycle_count,
                    (SELECT COUNT(*) FROM health_logs WHERE user_id = %s) AS health_log_count,
                    (SELECT COUNT(*) FROM lab_reports WHERE user_id = %s) AS lab_report_count,
                    (SELECT COUNT(*) FROM terra_activity_data WHERE user_id = %s) AS activity_count,
                    (SELECT COUNT(*) FROM health_goal_profile hgp
                        JOIN profiles p ON hgp.profile_id = p.id
                        WHERE p.user_id = %s) AS health_goal_count,
                    (SELECT COUNT(*) FROM profiles WHERE user_id = %s AND life_stage_id IS NOT NULL) AS life_stage_count
            """
            params = (self.user_id,) * 6
            result = self.db_query(query, params)
            result = result[0] if result else {}
            
            total_signals = sum(result.get(k, 0) or 0 for k in (
                "cycle_count", "health_log_count", "lab_report_count",
                "activity_count", "health_goal_count", "life_stage_count",
            ))
            
            print(f"[LIFE_ARC] Eligibility check: {result} (total_signals={total_signals})")
            
            if total_signals < 1:
                print(f"[LIFE_ARC] No milestone data found across any source - needs more data")
                return ("needs_more_data", False)
            
            print(f"[LIFE_ARC] User is eligible! (total_signals={total_signals})")
            return ("eligible", True)
            
        except Exception as e:
            logger.error(f"[LIFE_ARC] Error checking eligibility: {e}")
            print(f"[LIFE_ARC] Error checking eligibility: {e}")
            return ("check_failed", False)
    
    def _calculate_phase(self, cycle_day: int, cycle_length: int = 28) -> str:
        """Map cycle day to reproductive phase."""
        if 1 <= cycle_day <= 5:
            return "menstrual"
        elif 6 <= cycle_day <= 12:
            return "follicular"
        elif 13 <= cycle_day <= 15:
            return "ovulatory"
        else:
            return "luteal"
    
    def _calculate_cycle_day(self, period_start_date: date, reference_date: date = None) -> int:
        """Calculate cycle day from last menstrual period.
        
        Args:
            period_start_date: Start date of menstrual cycle
            reference_date: Date to calculate from (default: today)
        """
        if not period_start_date:
            return 1
        if reference_date is None:
            reference_date = datetime.now().date()
        days_since = (reference_date - period_start_date).days
        return max(1, (days_since % 28) + 1)  # Assume 28-day cycle
    
    def _calculate_significance(self, milestone_type: str, context: dict = None) -> float:
        """Calculate dynamic significance score 0.3-1.0 based on milestone type and context."""
        context = context or {}
        
        # Base significance by type
        base_significance = {
            "cycle_start": 0.4,
            "phase_transition": 0.5,
            "health_achievement": 0.75,
            "vitality_surge": 0.8,
            "symptom_resolution": 0.6,
            "cycle_anomaly": 0.35,
            "lab_result": 0.85,
            "health_goal_completed": 0.9,
            "health_goal_progress": 0.7
        }
        
        significance = base_significance.get(milestone_type, 0.5)
        
        # Boost for major improvements
        if context.get("vitality_change", 0) > 20:
            significance = min(significance + 0.2, 1.0)
        
        # Reduce for expected routine events
        if milestone_type == "cycle_start" and context.get("is_regular_cycle"):
            significance = 0.35
        
        return round(significance, 2)
    
    def _populate_health_context(self, milestone_type: str, cycle_data: dict = None, health_logs: list = None, milestone_date: date = None) -> dict:
        """Populate health context fields with calculated data.
        
        Args:
            milestone_type: Type of milestone
            cycle_data: Cycle information dict
            health_logs: Health logs (unused)
            milestone_date: Date of milestone (used for historical cycle_day calculation)
        """
        context = {
            "cycle_day": None,
            "phase": None,
            "duration": None,
            "progress": None,
            "status": None,
            "key_findings": [],
            "goal_progress": None
        }
        
        if not cycle_data:
            return context
        
        # Calculate cycle day and phase
        period_start = cycle_data.get("period_start_date")
        cycle_length = cycle_data.get("cycle_length") or 28
        period_length = cycle_data.get("period_length") or 5
        
        if period_start:
            cycle_day = self._calculate_cycle_day(period_start, milestone_date)
            phase = self._calculate_phase(cycle_day, cycle_length)
            progress = round((cycle_day / cycle_length) * 100, 1)
            
            context["cycle_day"] = cycle_day
            context["phase"] = phase
            context["duration"] = f"{cycle_length} days average"
            context["progress"] = f"{progress}%"  # Convert to string with % symbol
            
            # Determine status based on phase
            if phase == "menstrual":
                context["status"] = "Menstrual phase"
            elif phase == "follicular":
                context["status"] = "Rising energy - follicular phase"
            elif phase == "ovulatory":
                context["status"] = "Peak energy - ovulatory phase"
            else:
                context["status"] = "Luteal phase - self-care focus"
            
            # Add key findings
            context["key_findings"] = [
                f"Cycle day {cycle_day} of {cycle_length}",
                f"Phase: {phase.title()}"
            ]
            
            if cycle_data.get("confirmed_ovulation_day"):
                context["key_findings"].append(f"Ovulation confirmed on day {cycle_data['confirmed_ovulation_day']}")
        
        return context
    
    def _detect_milestones(self) -> List[Milestone]:
        """Detect all health milestones from multiple sources."""
        milestones = []
        cutoff_date = datetime.now() - timedelta(days=self.months_back * 30)
        
        # 1. Enhanced cycle-related milestones
        cycle_milestones = self._detect_cycle_milestones(cutoff_date)
        milestones.extend(cycle_milestones)
        
        # 2. Phase transitions
        phase_milestones = self._detect_phase_transitions(cutoff_date)
        milestones.extend(phase_milestones)
        
        # 3. Health achievements (from activity/health logs)
        achievement_milestones = self._detect_health_achievements(cutoff_date)
        milestones.extend(achievement_milestones)
        
        # 4. Symptom resolutions
        symptom_milestones = self._detect_symptom_resolutions(cutoff_date)
        milestones.extend(symptom_milestones)
        
        # 5. Cycle anomalies
        anomaly_milestones = self._detect_cycle_anomalies(cutoff_date)
        milestones.extend(anomaly_milestones)
        
        # 6. Health goal milestones
        goal_milestones = self._detect_health_goal_milestones(cutoff_date)
        milestones.extend(goal_milestones)
        
        # 7. Lab result milestones
        lab_milestones = self._detect_lab_milestones(cutoff_date)
        milestones.extend(lab_milestones)
        
        # 8. Life stage milestones
        life_stage_milestones = self._detect_life_stage_milestones(cutoff_date)
        milestones.extend(life_stage_milestones)
        
        # 9. Health insights from AI analyses
        insight_milestones = self._detect_health_insights(cutoff_date)
        milestones.extend(insight_milestones)
        
        logger.debug(f"[LIFE_ARC] User {self.user_id}: Detected {len(cycle_milestones)} cycle, "
                    f"{len(phase_milestones)} phase, {len(achievement_milestones)} achievement, "
                    f"{len(symptom_milestones)} symptom, {len(anomaly_milestones)} anomaly, "
                    f"{len(goal_milestones)} goal, {len(lab_milestones)} lab, "
                    f"{len(life_stage_milestones)} life_stage, {len(insight_milestones)} insight milestones")
        
        # Filter out low-significance events
        milestones_before = len(milestones)
        milestones = [m for m in milestones if m.significance >= 0.3]
        logger.debug(f"[LIFE_ARC] User {self.user_id}: After filtering: {milestones_before} -> {len(milestones)} milestones")
        
        return milestones
    
    def _detect_cycle_milestones(self, cutoff_date: datetime) -> List[Milestone]:
        """Detect menstrual cycle milestones with full health context."""
        milestones = []
        
        try:
            query = """
                SELECT 
                    id, period_start_date, period_end_date, cycle_length, period_length,
                    current_cycle_day, current_phase, predicted_ovulation_day, confirmed_ovulation_day,
                    fertile_start_day, fertile_end_day, is_completed, created_at
                FROM menstrual_cycles
                WHERE user_id = %s AND period_start_date >= DATE(%s)
                ORDER BY period_start_date DESC
                LIMIT 20
            """
            cycles = self.db_query(query, (self.user_id, cutoff_date.date()))
            print(f"[LIFE_ARC] Found {len(cycles)} cycles for user {self.user_id}")
            
            for cycle in cycles:
                if not cycle.get("period_start_date"):
                    continue
                
                period_start = cycle["period_start_date"]
                if hasattr(period_start, 'date'):
                    period_start = period_start.date()
                
                # Calculate current cycle stats
                cycle_day = self._calculate_cycle_day(period_start)
                phase = self._calculate_phase(cycle_day, cycle.get("cycle_length", 28))
                
                # Populate health context
                health_context = self._populate_health_context("cycle_start", cycle, milestone_date=period_start)
                
                # Calculate significance
                is_regular = (datetime.now().date() - period_start).days % 28 < 5
                significance = self._calculate_significance("cycle_start", {"is_regular_cycle": is_regular})
                
                description = f"New menstrual cycle began. Phase: {phase.title()}."
                if cycle.get("predicted_ovulation_day"):
                    description += f" Ovulation predicted on day {cycle['predicted_ovulation_day']}."
                if cycle.get("fertile_start_day") and cycle.get("fertile_end_day"):
                    description += f" Fertile window: days {cycle['fertile_start_day']}-{cycle['fertile_end_day']}."
                
                milestones.append(Milestone(
                    date_=period_start,
                    type_="cycle_start",
                    title="Period Started",
                    description=description,
                    significance=significance,
                    icon="flow",
                    health_context=MilestoneHealthContext(**health_context)
                ))
        except Exception as e:
            logger.error(f"[LIFE_ARC] Error detecting cycle milestones: {e}")
            print(f"[LIFE_ARC] Error detecting cycle milestones: {e}")
            import traceback
            print(traceback.format_exc())
        
        return milestones
    
    def _detect_phase_transitions(self, cutoff_date: datetime) -> List[Milestone]:
        """Detect phase transition milestones (calculated based on cycle dates)."""
        milestones = []
        
        try:
            # Get recent cycles to calculate phase transitions
            query = """
                SELECT period_start_date, cycle_length, predicted_ovulation_day
                FROM menstrual_cycles
                WHERE user_id = %s AND period_start_date >= DATE(%s)
                ORDER BY period_start_date DESC
                LIMIT 10
            """
            cycles = self.db_query(query, (self.user_id, cutoff_date.date()))
            
            for cycle in cycles:
                if not cycle.get("period_start_date"):
                    continue
                
                period_start = cycle["period_start_date"]
                if not period_start:
                    continue
                    
                if hasattr(period_start, 'date'):
                    period_start = period_start.date()
                
                cycle_length = cycle.get("cycle_length") or 28
                ovulation_day = cycle.get("predicted_ovulation_day")
                if not ovulation_day:
                    ovulation_day = 14
                
                # Follicular to Ovulatory transition (around day 13)
                try:
                    follicular_end = period_start + timedelta(days=ovulation_day - 1)
                except (TypeError, ValueError):
                    continue
                    
                if cutoff_date.date() <= follicular_end <= datetime.now().date():
                    # Use populate function to get full context including duration/progress
                    health_context = self._populate_health_context("phase_transition", cycle, milestone_date=follicular_end)
                    # Override with phase-specific status and findings
                    health_context["status"] = "Energy peak - ovulation begins"
                    health_context["key_findings"] = [
                        f"Ovulation begins on cycle day {ovulation_day}",
                        "Expect peak energy and fertility"
                    ]
                    
                    milestones.append(Milestone(
                        date_=follicular_end,
                        type_="phase_transition",
                        title="Ovulatory Phase Begins",
                        description="Transition to ovulatory phase. Peak energy expected.",
                        significance=self._calculate_significance("phase_transition"),
                        icon="moon",
                        health_context=MilestoneHealthContext(**health_context)
                    ))
                
                # Ovulatory to Luteal transition (around day 16)
                try:
                    luteal_start = period_start + timedelta(days=ovulation_day + 1)
                except (TypeError, ValueError):
                    continue
                    
                if cutoff_date.date() <= luteal_start <= datetime.now().date():
                    # Use populate function to get full context including duration/progress
                    health_context = self._populate_health_context("phase_transition", cycle, milestone_date=luteal_start)
                    # Override with phase-specific status and findings
                    health_context["status"] = "Luteal phase - self-care focus"
                    health_context["key_findings"] = [
                        "Ovulation completed",
                        "Energy may gradually decrease - plan accordingly"
                    ]
                    
                    milestones.append(Milestone(
                        date_=luteal_start,
                        type_="phase_transition",
                        title="Luteal Phase Begins",
                        description="Transition to luteal phase. Energy may dip - focus on self-care.",
                        significance=self._calculate_significance("phase_transition"),
                        icon="moon",
                        health_context=MilestoneHealthContext(**health_context)
                    ))
        except Exception as e:
            logger.error(f"[LIFE_ARC] Error detecting phase transitions: {e}")
        
        return milestones
    
    def _detect_health_achievements(self, cutoff_date: datetime) -> List[Milestone]:
        """Detect health achievements (activity streaks, goal progress, etc.)."""
        milestones = []
        
        try:
            # Look for activity patterns in terra_activity_data
            query = """
                SELECT DATE(created_at) as activity_date, COUNT(*) as activity_count
                FROM terra_activity_data
                WHERE user_id = %s AND created_at >= %s
                GROUP BY DATE(created_at)
                ORDER BY activity_date DESC
            """
            activities = self.db_query(query, (self.user_id, cutoff_date))
            
            if activities and len(activities) >= 7:
                # Calculate consecutive activity days
                consecutive_days = 0
                for i in range(len(activities) - 1):
                    current_date = activities[i]["activity_date"]
                    next_date = activities[i + 1]["activity_date"]
                    
                    if hasattr(current_date, 'date'):
                        current_date = current_date.date()
                    if hasattr(next_date, 'date'):
                        next_date = next_date.date()
                    
                    days_diff = (current_date - next_date).days
                    if days_diff == 1:
                        consecutive_days += 1
                    else:
                        consecutive_days = 0
                    
                    # 7-day streak milestone
                    if consecutive_days >= 6:  # 7 consecutive days
                        streak_start = current_date - timedelta(days=consecutive_days)
                        health_context = {
                            "status": "Active",
                            "key_findings": [
                                f"7-day activity streak achieved",
                                "Consistent engagement with health tracking"
                            ],
                            "goal_progress": 100.0
                        }
                        
                        milestones.append(Milestone(
                            date_=current_date,
                            type_="health_achievement",
                            title="7-Day Activity Streak",
                            description="Completed 7 consecutive days of activity tracking. Great consistency!",
                            significance=self._calculate_significance("health_achievement"),
                            icon="checkmark",
                            health_context=MilestoneHealthContext(**health_context)
                        ))
                        break
        except Exception as e:
            logger.error(f"[LIFE_ARC] Error detecting health achievements: {e}")
        
        return milestones
    
    def _detect_symptom_resolutions(self, cutoff_date: datetime) -> List[Milestone]:
        """Detect symptom resolution milestones."""
        milestones = []
        
        try:
            # Look for symptom patterns in health_logs
            query = """
                SELECT log_date, symptoms, notes
                FROM health_logs
                WHERE user_id = %s AND log_date >= DATE(%s)
                ORDER BY log_date DESC
                LIMIT 60
            """
            logs = self.db_query(query, (self.user_id, cutoff_date.date()))
            
            if logs:
                # Check for improvement patterns
                recent_symptoms = set()
                older_symptoms = set()
                
                for i, log in enumerate(logs):
                    if log.get("symptoms"):
                        try:
                            symptoms = json.loads(log["symptoms"]) if isinstance(log["symptoms"], str) else log["symptoms"]
                            if isinstance(symptoms, list):
                                symptom_set = set(symptoms)
                            else:
                                symptom_set = {log["symptoms"]}
                        except:
                            symptom_set = {log["symptoms"]}
                        
                        if i < len(logs) // 2:
                            recent_symptoms.update(symptom_set)
                        else:
                            older_symptoms.update(symptom_set)
                
                # Find resolved symptoms
                resolved_symptoms = older_symptoms - recent_symptoms
                if resolved_symptoms:
                    # Clean up symptom names (remove JSON array notation if present)
                    symptom_list = list(resolved_symptoms)
                    clean_symptoms = []
                    for s in symptom_list:
                        if isinstance(s, str):
                            # Remove all quotes, brackets, and escape characters (aggressive cleaning)
                            import re
                            s = re.sub(r'[\\\"\'"\[\]]', '', s)  # Remove all escape chars and quotes
                            s = s.strip()  # Remove whitespace
                            if s:  # Only add non-empty strings
                                clean_symptoms.append(s)
                    
                    symptoms_text = ', '.join(clean_symptoms) if clean_symptoms else 'various symptoms'
                    top_symptoms = ', '.join(clean_symptoms[:3]) if clean_symptoms else 'symptoms'
                    
                    health_context = {
                        "status": "Improved",
                        "key_findings": [
                            f"No longer reporting: {top_symptoms}",
                            "Positive health trend detected"
                        ]
                    }
                    
                    milestones.append(Milestone(
                        date_=logs[0]["log_date"] if logs else datetime.now().date(),
                        type_="symptom_resolution",
                        title="Symptom Improvement",
                        description=f"Successfully resolved symptoms including {symptoms_text}.",
                        significance=self._calculate_significance("symptom_resolution"),
                        icon="checkmark",
                        health_context=MilestoneHealthContext(**health_context)
                    ))
        except Exception as e:
            logger.error(f"[LIFE_ARC] Error detecting symptom resolutions: {e}")
        
        return milestones
    
    def _detect_cycle_anomalies(self, cutoff_date: datetime) -> List[Milestone]:
        """Detect cycle length anomalies."""
        milestones = []
        
        try:
            query = """
                SELECT period_start_date, cycle_length
                FROM menstrual_cycles
                WHERE user_id = %s AND period_start_date >= DATE(%s)
                ORDER BY period_start_date DESC
                LIMIT 5
            """
            cycles = self.db_query(query, (self.user_id, cutoff_date.date()))
            
            if len(cycles) >= 2:
                # Calculate average cycle length
                cycle_lengths = [c.get("cycle_length", 28) for c in cycles if c.get("cycle_length")]
                if cycle_lengths:
                    avg_length = sum(cycle_lengths) / len(cycle_lengths)
                    
                    # Check for deviations
                    for cycle in cycles[:1]:  # Check most recent
                        current_length = cycle.get("cycle_length", 28)
                        deviation = abs(current_length - avg_length)
                        
                        if deviation > 3:  # More than 3 days deviation
                            period_start = cycle["period_start_date"]
                            if hasattr(period_start, 'date'):
                                period_start = period_start.date()
                            
                            health_context = {
                                "status": "Monitor",
                                "key_findings": [
                                    f"Cycle length: {current_length} days (average: {avg_length:.0f})",
                                    f"Deviation: {deviation:.0f} days - monitor next cycle"
                                ]
                            }
                            
                            milestones.append(Milestone(
                                date_=period_start,
                                type_="cycle_anomaly",
                                title="Cycle Length Variation",
                                description=f"Cycle length ({current_length} days) differs from average ({avg_length:.0f} days). Monitor for pattern changes.",
                                significance=self._calculate_significance("cycle_anomaly"),
                                icon="alert",
                                health_context=MilestoneHealthContext(**health_context)
                            ))
        except Exception as e:
            logger.error(f"[LIFE_ARC] Error detecting cycle anomalies: {e}")
        
        return milestones
    
    def _detect_health_goal_milestones(self, cutoff_date: datetime) -> List[Milestone]:
        """Detect health goal achievements via join table health_goal_profile."""
        milestones = []
        
        try:
            # Schema: health_goals → health_goal_profile (join) → profiles.user_id
            # NOTE: Get ALL health goals assigned to user (no date filter - assignment date may predate cutoff)
            logger.info(f"[LIFE_ARC_DEBUG] health_goal detection: Querying for user_id={self.user_id}")
            
            query = """
                SELECT hg.id, hg.title, hg.status, hgp.created_at, hgp.updated_at
                FROM health_goals hg
                JOIN health_goal_profile hgp ON hg.id = hgp.health_goal_id
                JOIN profiles p ON hgp.profile_id = p.id
                WHERE p.user_id = %s
                ORDER BY COALESCE(hgp.updated_at, hgp.created_at) DESC
                LIMIT 20
            """
            goals = self.db_query(query, (self.user_id,))
            goal_count = len(goals) if goals else 0
            logger.info(f"[LIFE_ARC_DEBUG] health_goal query returned {goal_count} rows")
            print(f"[HEALTH_GOAL_DEBUG] Query returned {goal_count} rows for user_id={self.user_id}")
            
            if goals:
                for i, g in enumerate(goals[:3]):  # Print first 3
                    print(f"  Goal {i+1}: id={g.get('id')}, title={g.get('title')}, created_at={g.get('created_at')}, updated_at={g.get('updated_at')}")
            
            logger.debug(f"[LIFE_ARC] User {self.user_id}: Found {goal_count} health goals")
            
            for goal in goals:
                # Use updated_at if created_at is NULL (fallback pattern)
                goal_date = goal.get("created_at") or goal.get("updated_at")
                if not goal_date:
                    logger.warning(f"[LIFE_ARC] Goal {goal.get('id')} has no created_at or updated_at")
                    continue
                
                goal_date = goal_date.date() if hasattr(goal_date, "date") else goal_date
                
                # Status: 1 = active, 0 = completed/inactive
                status = "Completed" if goal.get("status") == 0 else "In Progress"
                significance = 0.6
                
                milestones.append(Milestone(
                    date_=goal_date,
                    type_="health_goal",
                    title=goal.get("title", "Health Goal"),
                    description=f"Health goal: {goal.get('title', 'Unnamed')}. Status: {status}.",
                    significance=significance,
                    icon="target",
                    health_context=MilestoneHealthContext(
                        status=status,
                        key_findings=[f"Goal: {goal.get('title', 'Unnamed')}", f"Status: {status}"]
                    )
                ))
        except Exception as e:
            logger.error(f"[LIFE_ARC] Error detecting goal milestones: {e}")
        
        return milestones
    
    def _detect_lab_milestones(self, cutoff_date: datetime) -> List[Milestone]:
        """Detect significant lab result milestones."""
        milestones = []
        
        try:
            query = """
                SELECT test_type, biomarkers, analysis_status, created_at
                FROM lab_reports
                WHERE user_id = %s AND created_at >= %s
                ORDER BY created_at DESC
                LIMIT 20
            """
            reports = self.db_query(query, (self.user_id, cutoff_date))
            
            for report in reports:
                # All lab results are significant
                significance = 0.85
                test_type = report.get("test_type", "Lab Test")
                status = report.get("analysis_status", "completed")
                
                description = f"{test_type} completed. Status: {status}."
                if report.get("biomarkers"):
                    description += " Results show normal hormone levels." if status == "normal" else " Results require attention."
                
                milestones.append(Milestone(
                    date_=report["created_at"].date() if hasattr(report["created_at"], "date") else report["created_at"],
                    type_="lab_result",
                    title=test_type,
                    description=description,
                    significance=significance,
                    icon="test",
                    health_context=MilestoneHealthContext(
                        status=status,
                        key_findings=["Test completed successfully"]
                    )
                ))
        except Exception as e:
            logger.error(f"Error detecting lab milestones: {e}")
        
        return milestones
    
    def _detect_life_stage_milestones(self, cutoff_date: datetime) -> List[Milestone]:
        """Detect life stage transitions from user profiles linked to life_journeys."""
        milestones = []
        
        try:
            # Schema: profiles.id -> life_journey_profile.profile_id -> life_journeys.id.
            # This is the current source of truth for active journeys (a profile can
            # have several at once); the legacy profiles.life_stage_id scalar can be
            # stale/out of sync with it, so it must not be used here.
            # NOTE: Get ALL life stages assigned to user (no date filter - assignment may predate cutoff)
            logger.info(f"[LIFE_ARC_DEBUG] life_stage detection: Querying for user_id={self.user_id}")
            
            query = """
                SELECT p.id, p.created_at, p.updated_at, lj.id as journey_id, lj.icon, lj.title, 
                       lj.subtitle, lj.description, lj.status, lj.created_at as journey_created_at
                FROM profiles p
                JOIN life_journey_profile ljp ON ljp.profile_id = p.id
                JOIN life_journeys lj ON lj.id = ljp.life_journey_id
                WHERE p.user_id = %s
                ORDER BY COALESCE(lj.created_at, p.updated_at) DESC
                LIMIT 20
            """
            stages = self.db_query(query, (self.user_id,))
            stage_count = len(stages) if stages else 0
            logger.info(f"[LIFE_ARC_DEBUG] life_stage query returned {stage_count} rows")
            print(f"[LIFE_STAGE_DEBUG] Query returned {stage_count} rows for user_id={self.user_id}")
            
            if stages:
                for i, s in enumerate(stages[:3]):  # Print first 3
                    print(f"  Stage {i+1}: journey_id={s.get('journey_id')}, title={s.get('title')}, updated_at={s.get('updated_at')}")
            
            logger.debug(f"[LIFE_ARC] User {self.user_id}: Found {stage_count} life stage transitions")
            
            for stage in stages:
                journey_id = stage.get("journey_id")
                if not journey_id:
                    continue  # Skip profiles with no life_journey set
                
                # Use profile updated_at or journey created_at as milestone date
                milestone_date = stage.get("created_at") or stage.get("updated_at")
                if not milestone_date:
                    continue
                
                milestone_date = milestone_date.date() if hasattr(milestone_date, "date") else milestone_date
                
                title = stage.get("title", "Life Stage Transition")
                description = stage.get("description") or stage.get("subtitle") or f"Life stage: {title}"
                status = "Completed" if stage.get("status") == 0 else "In Progress"
                
                # Determine significance based on life stage type.
                # NOTE: lj.icon holds a full image URL, not a short icon key - never use it directly.
                significance = 0.75
                icon = "journey"
                
                if any(x in title.lower() for x in ["perimenopause", "menopause", "postmenopause"]):
                    significance = 0.95  # Major life transition
                    icon = "health"
                elif any(x in title.lower() for x in ["pregnancy", "postpartum", "postpregn"]):
                    significance = 0.9
                    icon = "health"
                
                milestones.append(Milestone(
                    date_=milestone_date,
                    type_="life_stage",
                    title=title,
                    description=description,
                    significance=significance,
                    icon=icon,
                    health_context=MilestoneHealthContext(
                        status=status,
                        key_findings=[f"Life Stage: {title}", f"Status: {status}"]
                    )
                ))
        except Exception as e:
            logger.error(f"[LIFE_ARC] Error detecting life stage milestones: {e}")
        
        return milestones
    
    def _detect_health_insights(self, cutoff_date: datetime) -> List[Milestone]:
        """Detect health insights from smart analyses (AI-generated insights)."""
        milestones = []
        
        try:
            # smart_analyses table schema: id, user_id, title, alerts (json), status, created_at, updated_at
            # Missing: category, insight_summary, analysis_date
            # Using created_at as analysis_date, using title as category placeholder
            query = """
                SELECT id, title, alerts, status, created_at
                FROM smart_analyses
                WHERE user_id = %s AND created_at >= %s
                ORDER BY created_at DESC
                LIMIT 30
            """
            analyses = self.db_query(query, (self.user_id, cutoff_date))
            logger.debug(f"User {self.user_id}: Found {len(analyses)} smart analyses for health insights")
            
            for analysis in analyses:
                if not analysis.get("created_at"):
                    continue
                
                title = analysis.get("title", "AI Analysis")
                alerts = analysis.get("alerts")
                
                # Parse alerts if it's a JSON string/array
                alert_list = []
                if alerts:
                    try:
                        if isinstance(alerts, str):
                            # Try to parse as JSON
                            alert_list = json.loads(alerts) if alerts.startswith('[') or alerts.startswith('{') else [alerts]
                        elif isinstance(alerts, list):
                            alert_list = alerts
                        elif isinstance(alerts, dict):
                            alert_list = [alerts]
                    except:
                        alert_list = [str(alerts)] if alerts else []
                
                # Create milestone if there are alerts
                if alert_list:
                    # Use title as category placeholder since table doesn't have category column
                    category = title.lower().replace(" ", "_") if title else "general"
                    
                    # Map category to icon
                    icon_map = {
                        "fertility": "target",
                        "sleep_energy": "moon",
                        "skin_hydration": "droplet",
                        "mood": "heart",
                        "hormone": "heart",
                        "nutrition": "apple",
                        "fitness": "activity",
                        "general": "lightbulb",
                        "smart_alerts": "bell",
                        "ai_analysis": "lightbulb"
                    }
                    
                    icon = icon_map.get(category, "lightbulb")
                    
                    # Create description from alerts
                    alert_text = ', '.join(str(a) for a in alert_list[:3])
                    description = f"AI Analysis: {title}. Key findings: {alert_text}."
                    
                    milestone_date = analysis["created_at"]
                    if hasattr(milestone_date, 'date'):
                        milestone_date = milestone_date.date()
                    
                    milestones.append(Milestone(
                        date_=milestone_date,
                        type_="health_insight",
                        title=f"{title} Insight",
                        description=description,
                        significance=0.65,  # Moderate significance for AI insights
                        icon=icon,
                        health_context=MilestoneHealthContext(
                            status=f"{title} analysis completed",
                            key_findings=alert_list[:3] if alert_list else []
                        )
                    ))
        except Exception as e:
            logger.error(f"Error detecting health insights: {e}")
            print(f"[LIFE_ARC] Error detecting health insights: {e}")
        
        return milestones
    
    def _generate_timeline_insights(self, milestones: List[Milestone]) -> Optional[VitalityAIInsights]:
        """Generate Claude AI insights about the life arc timeline.
        
        Note: Currently disabled - UI does not display AI insights section.
        Returns None to keep JSON clean.
        """
        return None
    
    def _calculate_timeline_summary(self, milestones: List[Milestone]) -> TimelineSummary:
        """Calculate timeline summary statistics with proper major events counting."""
        if not milestones:
            return TimelineSummary(
                total_milestones=0,
                major_events=0,
                avg_monthly_milestones=0,
                date_range={"start": date.today(), "end": date.today()}
            )
        
        # Count major events (significance >= 0.7 for better visibility)
        major_events = sum(1 for m in milestones if m.significance >= 0.7)
        
        # Calculate date range
        dates = [m.date_ for m in milestones]
        start_date = min(dates)
        end_date = max(dates)
        
        # Calculate monthly average
        days_diff = (end_date - start_date).days
        months = max(1, days_diff / 30)
        avg_monthly = len(milestones) / months
        
        print(f"[LIFE_ARC] Timeline summary: {len(milestones)} total, {major_events} major, {avg_monthly:.1f} per month")
        
        return TimelineSummary(
            total_milestones=len(milestones),
            major_events=major_events,
            avg_monthly_milestones=round(avg_monthly, 1),
            date_range={"start": start_date, "end": end_date}
        )


# ============================================================================
# REMINDERS SERVICE
# ============================================================================

class RemindersService:
    """Generate preventative health reminders."""
    
    # Evidence-based screening guidelines
    SCREENING_GUIDELINES = {
        "Mammogram": {
            "start_age": 40,
            "interval_years": 1,
            "apply_to": "female",
            "priority": 1
        },
        "Bone Density Scan": {
            "start_age": 50,
            "interval_years": 2,
            "apply_to": "female",
            "priority": 2
        },
        "Colonoscopy": {
            "start_age": 45,
            "interval_years": 10,
            "apply_to": "all",
            "priority": 2
        },
        "Pap Smear": {
            "start_age": 21,
            "interval_years": 3,
            "apply_to": "female",
            "priority": 2
        },
        "Blood Pressure Check": {
            "start_age": 18,
            "interval_years": 2,
            "apply_to": "all",
            "priority": 3
        },
        "Cholesterol Panel": {
            "start_age": 20,
            "interval_years": 4,
            "apply_to": "all",
            "priority": 3
        },
        "Skin Cancer Check": {
            "start_age": 18,
            "interval_years": 1,
            "apply_to": "all",
            "priority": 3
        },
        "Eye Exam": {
            "start_age": 18,
            "interval_years": 2,
            "apply_to": "all",
            "priority": 4
        },
        "Dental Checkup": {
            "start_age": 18,
            "interval_years": 1,
            "apply_to": "all",
            "priority": 4
        }
    }
    
    def __init__(self, user_id: int):
        self.user_id = user_id
        # Route to mock data if enabled, otherwise real database
        self.db_query = mock_query_db if USE_MOCK_DATA else query_db
    
    def get_preventative_reminders(self) -> RemindersResponse:
        """Generate preventative health reminders response."""
        try:
            # Get user profile and age
            user_profile = self._get_user_profile()
            
            # Generate reminders
            reminders = self._generate_reminders(user_profile)
            
            # Get mobility/stress metrics
            mobility_metrics = self._get_mobility_stress_metrics()
            
            # Calculate summary
            summary = self._calculate_summary(reminders)
            
            return RemindersResponse(
                reminders=reminders,
                mobility_stress_reminders=mobility_metrics,
                summary=summary
            )
        except Exception as e:
            logger.error(f"Error generating reminders: {e}")
            return RemindersResponse(
                reminders=[],
                mobility_stress_reminders=[],
                summary=RemindersSnapshot(
                    total_reminders=0, overdue=0, due_soon=0,
                    scheduled=0, up_to_date=0, not_applicable=0
                )
            )
    
    def _get_user_profile(self) -> Dict[str, Any]:
        """Get user age and profile info."""
        try:
            query = """
                SELECT u.id, u.date_of_birth, p.activity_level, p.life_stage, p.age_group
                FROM users u
                JOIN profiles p ON u.id = p.user_id
                WHERE u.id = %s
            """
            result = self.db_query(query, (self.user_id,))
            return result[0] if result else {}
        except Exception as e:
            logger.error(f"Error fetching user profile: {e}")
            return {}
    
    def _get_user_age(self, user_profile: Dict) -> int:
        """Calculate user age from date of birth or age_group."""
        try:
            # Try date_of_birth first
            dob = user_profile.get("date_of_birth")
            if dob:
                today = date.today()
                age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                return age
        except:
            pass
        
        # Fall back to age_group from profiles table
        try:
            age_group = user_profile.get("age_group")
            if age_group and isinstance(age_group, str):
                # Parse age_group (e.g., "40-50" → 40)
                lower_bound = age_group.split('-')[0].strip()
                return int(lower_bound)
        except:
            pass
        
        return 40  # Default age for unknown users
    
    def _generate_reminders(self, user_profile: Dict) -> List[HealthReminder]:
        """Generate reminders based on guidelines."""
        reminders = []
        age = self._get_user_age(user_profile)
        today = date.today()
        
        reminder_counter = 1
        for screening_name, guideline in self.SCREENING_GUIDELINES.items():
            # Check if applicable to this user
            if not self._is_screening_applicable(guideline, age):
                continue
            
            # Calculate due dates and status
            reminder_id = reminder_counter
            reminder_counter += 1
            
            # Get last screening date from lab reports
            last_done = self._get_last_screening_date(screening_name)
            
            # Calculate due date
            due_date = self._calculate_due_date(last_done, guideline["interval_years"])
            
            # Determine status
            status = self._determine_status(last_done, due_date, today)
            
            # Determine priority based on status
            priority_mapping = {
                ReminderStatus.NOT_STARTED: "medium",
                ReminderStatus.OVERDUE: "critical",
                ReminderStatus.DUE_SOON: "high",
                ReminderStatus.SCHEDULED: "medium",
                ReminderStatus.UP_TO_DATE: "low",
                ReminderStatus.NOT_APPLICABLE: "low"
            }
            priority = priority_mapping.get(status, "medium")
            
            # Calculate days
            days_overdue = None
            days_until_due = None
            days_until_scheduled = None
            
            if status == ReminderStatus.OVERDUE:
                days_overdue = (today - due_date).days
            elif status == ReminderStatus.DUE_SOON:
                days_until_due = (due_date - today).days
            elif status == ReminderStatus.NOT_STARTED:
                # For not started screenings, show days until recommended start
                days_until_due = (due_date - today).days if due_date >= today else 0
            
            # Get recommendation
            recommendation = self._get_recommendation(status)
            
            # Get status label and color
            status_label = self._get_status_label(status)
            status_color = self._get_status_color(status)
            
            reminders.append(HealthReminder(
                id=reminder_id,
                type_=screening_name,
                status=status,
                priority=priority,
                last_done=last_done,
                due_date=due_date,
                scheduled_date=None,
                days_overdue=days_overdue,
                days_until_due=days_until_due,
                days_until_scheduled=days_until_scheduled,
                guideline=f"Every {guideline['interval_years']} year(s) for ages {guideline['start_age']}+",
                recommendation=recommendation,
                status_label=status_label,
                status_color=status_color
            ))
        
        # Sort by priority
        reminders.sort(key=lambda r: r.priority)
        
        return reminders
    
    def _is_screening_applicable(self, guideline: Dict, age: int) -> bool:
        """Check if screening applies to this user."""
        if age < guideline["start_age"]:
            return False
        return True
    
    def _get_last_screening_date(self, screening_name: str) -> Optional[date]:
        """Get date of last screening from lab reports."""
        try:
            query = """
                SELECT MAX(created_at) as last_date
                FROM lab_reports
                WHERE user_id = %s AND test_type LIKE %s
            """
            result = self.db_query(query, (self.user_id, f"%{screening_name}%"))
            if result and result[0].get("last_date"):
                return result[0]["last_date"].date() if hasattr(result[0]["last_date"], "date") else result[0]["last_date"]
        except Exception as e:
            logger.error(f"Error getting last screening date: {e}")
        
        return None
    
    def _calculate_due_date(self, last_done: Optional[date], interval_years: int) -> date:
        """Calculate when next screening is due."""
        if last_done:
            return last_done + timedelta(days=365 * interval_years)
        else:
            # If never done, due today
            return date.today()
    
    def _determine_status(self, last_done: Optional[date], due_date: date, today: date) -> ReminderStatus:
        """Determine reminder status."""
        if last_done is None:
            # Never done before - mark as NOT_STARTED (not overdue)
            return ReminderStatus.NOT_STARTED
        
        if today > due_date + timedelta(days=30):
            return ReminderStatus.OVERDUE
        elif today > due_date - timedelta(days=30):
            return ReminderStatus.DUE_SOON
        elif today <= due_date + timedelta(days=365):
            return ReminderStatus.UP_TO_DATE
        else:
            return ReminderStatus.UP_TO_DATE
    
    def _get_recommendation(self, status: ReminderStatus) -> str:
        """Get recommendation based on status."""
        recommendations = {
            ReminderStatus.NOT_STARTED: "Schedule your first screening",
            ReminderStatus.OVERDUE: "Schedule immediately",
            ReminderStatus.DUE_SOON: "Schedule within 30 days",
            ReminderStatus.SCHEDULED: "Appointment confirmed",
            ReminderStatus.UP_TO_DATE: "Continue regular monitoring",
            ReminderStatus.NOT_APPLICABLE: "Not needed at this time"
        }
        return recommendations.get(status, "Check with healthcare provider")
    
    def _get_status_label(self, status: ReminderStatus) -> str:
        """Get display label for status."""
        labels = {
            ReminderStatus.NOT_STARTED: "Not Started",
            ReminderStatus.OVERDUE: "Overdue",
            ReminderStatus.DUE_SOON: "Due Soon",
            ReminderStatus.SCHEDULED: "Scheduled",
            ReminderStatus.UP_TO_DATE: "Up to Date",
            ReminderStatus.NOT_APPLICABLE: "Not Applicable"
        }
        return labels.get(status, "Unknown")
    
    def _get_status_color(self, status: ReminderStatus) -> str:
        """Get color for status."""
        colors = {
            ReminderStatus.NOT_STARTED: "yellow",
            ReminderStatus.OVERDUE: "red",
            ReminderStatus.DUE_SOON: "orange",
            ReminderStatus.SCHEDULED: "green",
            ReminderStatus.UP_TO_DATE: "blue",
            ReminderStatus.NOT_APPLICABLE: "gray"
        }
        return colors.get(status, "gray")
    
    def _get_mobility_stress_metrics(self) -> List[MobilityStressMetric]:
        """Get mobility-related metrics from actual user data."""
        metrics = []
        
        try:
            # Get last measurement date
            last_log_query = """
                SELECT MAX(log_date) as last_date
                FROM health_logs
                WHERE user_id = %s
            """
            log_result = self.db_query(last_log_query, (self.user_id,))
            last_measured = log_result[0]["last_date"] if log_result and log_result[0].get("last_date") else date.today()
            if hasattr(last_measured, "date"):
                last_measured = last_measured.date()
            
            # Calculate each mobility metric
            hip_flexibility = self._calculate_hip_flexibility_score()
            grip_strength = self._calculate_grip_strength_score()
            balance_score = self._calculate_balance_score()
            posture_alignment = self._calculate_posture_score()
            
            metrics.append(MobilityStressMetric(
                area="Hip Flexibility",
                score=hip_flexibility,
                status="good" if hip_flexibility >= 70 else "moderate" if hip_flexibility >= 50 else "poor",
                last_measured=last_measured
            ))
            
            metrics.append(MobilityStressMetric(
                area="Grip Strength",
                score=grip_strength,
                status="good" if grip_strength >= 70 else "moderate" if grip_strength >= 50 else "poor",
                last_measured=last_measured
            ))
            
            metrics.append(MobilityStressMetric(
                area="Balance Score",
                score=balance_score,
                status="good" if balance_score >= 70 else "moderate" if balance_score >= 50 else "poor",
                last_measured=last_measured
            ))
            
            metrics.append(MobilityStressMetric(
                area="Posture Alignment",
                score=posture_alignment,
                status="good" if posture_alignment >= 70 else "moderate" if posture_alignment >= 50 else "poor",
                last_measured=last_measured
            ))
        except Exception as e:
            logger.error(f"Error getting mobility metrics: {e}")
            # Fallback if data unavailable
            metrics.append(MobilityStressMetric(area="Hip Flexibility", score=70, status="good", last_measured=date.today()))
            metrics.append(MobilityStressMetric(area="Grip Strength", score=70, status="good", last_measured=date.today()))
            metrics.append(MobilityStressMetric(area="Balance Score", score=70, status="good", last_measured=date.today()))
            metrics.append(MobilityStressMetric(area="Posture Alignment", score=70, status="good", last_measured=date.today()))
        
        return metrics
    
    def _calculate_hip_flexibility_score(self) -> int:
        """Calculate hip flexibility from health logs mentioning flexibility, stretching, yoga."""
        try:
            query = """
                SELECT COUNT(*) as log_count,
                       SUM(CASE WHEN notes LIKE '%stretch%' OR notes LIKE '%yoga%' OR notes LIKE '%flexible%' THEN 1 ELSE 0 END) as positive_count,
                       SUM(CASE WHEN notes LIKE '%stiff%' OR notes LIKE '%tight%' OR notes LIKE '%pain%' THEN -1 ELSE 0 END) as negative_count
                FROM health_logs
                WHERE user_id = %s AND log_date >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            """
            result = self.db_query(query, (self.user_id,))
            if result and result[0]:
                log_count = result[0].get("log_count", 0) or 0
                positive_count = result[0].get("positive_count", 0) or 0
                negative_count = result[0].get("negative_count", 0) or 0
                if log_count > 0:
                    sentiment = ((positive_count - negative_count) / log_count) * 15
                    return max(0, min(100, int(70 + sentiment)))
            return 70
        except Exception as e:
            logger.error(f"Error calculating hip flexibility: {e}")
            return 70
    
    def _calculate_grip_strength_score(self) -> int:
        """Calculate grip strength from activity data and strength-related logs."""
        try:
            query = """
                SELECT COUNT(*) as log_count,
                       SUM(CASE WHEN notes LIKE '%strength%' OR notes LIKE '%weight%' OR notes LIKE '%strong%' THEN 1 ELSE 0 END) as positive_count,
                       SUM(CASE WHEN notes LIKE '%weak%' OR notes LIKE '%fatigue%' THEN -1 ELSE 0 END) as negative_count
                FROM health_logs
                WHERE user_id = %s AND log_date >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            """
            result = self.db_query(query, (self.user_id,))
            if result and result[0]:
                log_count = result[0].get("log_count", 0) or 0
                positive_count = result[0].get("positive_count", 0) or 0
                negative_count = result[0].get("negative_count", 0) or 0
                if log_count > 0:
                    sentiment = ((positive_count - negative_count) / log_count) * 18
                    return max(0, min(100, int(72 + sentiment)))
            return 72
        except Exception as e:
            logger.error(f"Error calculating grip strength: {e}")
            return 72
    
    def _calculate_balance_score(self) -> int:
        """Calculate balance score from activity and coordination-related logs."""
        try:
            query = """
                SELECT COUNT(*) as log_count,
                       SUM(CASE WHEN notes LIKE '%balance%' OR notes LIKE '%coordin%' OR notes LIKE '%stable%' THEN 1 ELSE 0 END) as positive_count,
                       SUM(CASE WHEN notes LIKE '%dizzy%' OR notes LIKE '%unsteady%' OR notes LIKE '%fall%' THEN -1 ELSE 0 END) as negative_count
                FROM health_logs
                WHERE user_id = %s AND log_date >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            """
            result = self.db_query(query, (self.user_id,))
            if result and result[0]:
                log_count = result[0].get("log_count", 0) or 0
                positive_count = result[0].get("positive_count", 0) or 0
                negative_count = result[0].get("negative_count", 0) or 0
                if log_count > 0:
                    sentiment = ((positive_count - negative_count) / log_count) * 20
                    return max(0, min(100, int(75 + sentiment)))
            return 75
        except Exception as e:
            logger.error(f"Error calculating balance score: {e}")
            return 75
    
    def _calculate_posture_score(self) -> int:
        """Calculate posture alignment from posture and alignment-related logs."""
        try:
            query = """
                SELECT COUNT(*) as log_count,
                       SUM(CASE WHEN notes LIKE '%posture%' OR notes LIKE '%align%' OR notes LIKE '%straight%' THEN 1 ELSE 0 END) as positive_count,
                       SUM(CASE WHEN notes LIKE '%slouch%' OR notes LIKE '%hunch%' OR notes LIKE '%back pain%' THEN -1 ELSE 0 END) as negative_count
                FROM health_logs
                WHERE user_id = %s AND log_date >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            """
            result = self.db_query(query, (self.user_id,))
            if result and result[0]:
                log_count = result[0].get("log_count", 0) or 0
                positive_count = result[0].get("positive_count", 0) or 0
                negative_count = result[0].get("negative_count", 0) or 0
                if log_count > 0:
                    sentiment = ((positive_count - negative_count) / log_count) * 16
                    return max(0, min(100, int(73 + sentiment)))
            return 73
        except Exception as e:
            logger.error(f"Error calculating posture score: {e}")
            return 73
    

    
    def _calculate_summary(self, reminders: List[HealthReminder]) -> RemindersSnapshot:
        """Calculate summary statistics."""
        summary = RemindersSnapshot(
            total_reminders=len(reminders),
            not_started=sum(1 for r in reminders if r.status == ReminderStatus.NOT_STARTED),
            overdue=sum(1 for r in reminders if r.status == ReminderStatus.OVERDUE),
            due_soon=sum(1 for r in reminders if r.status == ReminderStatus.DUE_SOON),
            scheduled=sum(1 for r in reminders if r.status == ReminderStatus.SCHEDULED),
            up_to_date=sum(1 for r in reminders if r.status == ReminderStatus.UP_TO_DATE),
            not_applicable=sum(1 for r in reminders if r.status == ReminderStatus.NOT_APPLICABLE)
        )
        return summary
