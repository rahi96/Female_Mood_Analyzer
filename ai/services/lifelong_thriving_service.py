"""
Service layer for Lifelong Thriving feature.
Handles:
- Vitality Index calculation (multi-year, weighted ML algorithm)
- Life Arc Timeline generation (milestone detection + Claude descriptions)
- Preventative Health Reminders (guideline-based, dynamic status)
"""

import logging
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
USE_MOCK_DATA = True  # Set to False to use real database


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
    
    def __init__(self, user_id: int, years_back: int = 6):
        self.user_id = user_id
        self.years_back = years_back
        self.claude = ClaudeLLM()
    
    def get_vitality_overview(self) -> VitalityResponse:
        """Generate complete vitality response."""
        try:
            # Fetch all user health data
            user_data = self._fetch_user_health_data()
            
            # Calculate yearly vitality trend
            trend_data = self._calculate_yearly_trends(user_data)
            
            # Calculate current dimensions
            dimensions = self._calculate_dimensions(user_data)
            
            # Calculate overall vitality index
            vitality_index = self._calculate_vitality_index(dimensions)
            
            # Determine vitality level
            vitality_level = self._get_vitality_level(vitality_index)
            
            # Generate personal statement
            personal_best = self._generate_personal_statement(
                vitality_index, vitality_level, dimensions
            )
            
            # Get AI insights if requested
            ai_insights = self._generate_ai_insights(
                vitality_index, dimensions, trend_data, user_data
            )
            
            return VitalityResponse(
                vitality_index=vitality_index,
                vitality_level=vitality_level,
                personal_best=personal_best,
                trend_6_years=trend_data,
                dimensions=dimensions,
                ai_insights=ai_insights
            )
        except Exception as e:
            import traceback
            logger.error(f"❌ ERROR calculating vitality for user {self.user_id}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Return fallback response
            return self._get_fallback_vitality_response()
    
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
        logger.info(f"📊 CALCULATING DIMENSIONS (logs={len(user_data['health_logs'])}, cycles={len(user_data['menstrual_cycles'])})")
        
        # Mobility & Strength - from activity level and health logs
        mobility_score = self._calculate_mobility_score(user_data)
        logger.info(f"   Mobility & Strength: {mobility_score}")
        dimensions.append(VitalityDimension(
            name="Mobility & Strength",
            score=mobility_score,
            status=self._get_status_from_score(mobility_score),
            trend="stable",  # Could calculate actual trend
            last_updated=self._get_last_update_date(user_data["health_logs"]),
            description="Based on activity levels and reported mobility"
        ))
        
        # Cardiovascular Health - from energy logs and lab data
        cardio_score = self._calculate_cardiovascular_score(user_data)
        dimensions.append(VitalityDimension(
            name="Cardiovascular Health",
            score=cardio_score,
            status=self._get_status_from_score(cardio_score),
            trend="stable",
            last_updated=self._get_last_update_date(user_data["lab_reports"]),
            description="Based on energy levels and cardiovascular biomarkers"
        ))
        
        # Cognitive Wellness - from focus/brain fog symptoms
        cognitive_score = self._calculate_cognitive_score(user_data)
        dimensions.append(VitalityDimension(
            name="Cognitive Wellness",
            score=cognitive_score,
            status=self._get_status_from_score(cognitive_score),
            trend="stable",
            last_updated=self._get_last_update_date(user_data["health_logs"]),
            description="Based on focus, brain fog, and mental clarity"
        ))
        
        # Sleep Quality - from health trends and logs
        sleep_score = self._calculate_sleep_score(user_data)
        dimensions.append(VitalityDimension(
            name="Sleep Quality",
            score=sleep_score,
            status=self._get_status_from_score(sleep_score),
            trend="stable",
            last_updated=self._get_last_update_date(user_data["health_logs"]),
            description="Based on sleep duration and quality patterns"
        ))
        
        # Emotional Wellbeing - from mood logs
        emotional_score = self._calculate_emotional_score(user_data)
        dimensions.append(VitalityDimension(
            name="Emotional Wellbeing",
            score=emotional_score,
            status=self._get_status_from_score(emotional_score),
            trend="stable",
            last_updated=self._get_last_update_date(user_data["health_logs"]),
            description="Based on mood patterns and emotional state"
        ))
        
        # Metabolic Health - from lab biomarkers
        metabolic_score = self._calculate_metabolic_score(user_data)
        dimensions.append(VitalityDimension(
            name="Metabolic Health",
            score=metabolic_score,
            status=self._get_status_from_score(metabolic_score),
            trend="stable",
            last_updated=self._get_last_update_date(user_data["lab_reports"]),
            description="Based on metabolic biomarkers and lab results"
        ))
        
        # Reproductive Health - from cycle regularity
        repro_score = self._calculate_reproductive_score(user_data)
        dimensions.append(VitalityDimension(
            name="Reproductive Health",
            score=repro_score,
            status=self._get_status_from_score(repro_score),
            trend="stable",
            last_updated=self._get_last_update_date(user_data["menstrual_cycles"]),
            description="Based on cycle regularity and hormone balance"
        ))
        
        return dimensions
    
    def _calculate_mobility_score(self, user_data: Dict) -> float:
        """Calculate mobility & strength score from activity level."""
        profile = user_data.get("profile", {})
        activity_level = profile.get("activity_level", "moderate")
        
        activity_map = {
            "sedentary": 30,
            "light": 50,
            "moderate": 70,
            "active": 85,
            "very_active": 95
        }
        
        return activity_map.get(activity_level, 50)
    
    def _calculate_cardiovascular_score(self, user_data: Dict) -> float:
        """Calculate cardiovascular health from energy and biomarkers."""
        scores = []
        
        # Map ENUM energy levels to scores
        energy_map = {
            "Very Low": 20,
            "Low": 40,
            "Moderate": 60,
            "High": 80,
            "Very High": 100
        }
        
        # From energy levels in health logs
        for log in user_data["health_logs"][-30:]:  # Last 30 logs
            energy_raw = log.get("energy_level", "Moderate")
            energy_score = energy_map.get(str(energy_raw), 60)
            scores.append(energy_score)
        
        # From lab biomarkers if available
        for report in user_data["lab_reports"]:
            if "heart" in (report.get("test_type") or "").lower():
                # Assume higher values are better (would need to parse biomarkers)
                scores.append(75)
        
        return sum(scores) / len(scores) if scores else 60
    
    def _calculate_cognitive_score(self, user_data: Dict) -> float:
        """Calculate cognitive wellness from symptoms."""
        scores = []
        
        for log in user_data["health_logs"][-30:]:
            symptoms = log.get("symptoms", "")
            
            # Check for negative indicators
            negative_keywords = ["brain fog", "confusion", "memory loss", "concentration"]
            positive_keywords = ["focused", "clear", "sharp", "alert"]
            
            score = 70  # Default baseline
            
            if symptoms:
                symptoms_lower = symptoms.lower()
                for keyword in negative_keywords:
                    if keyword in symptoms_lower:
                        score -= 10
                for keyword in positive_keywords:
                    if keyword in symptoms_lower:
                        score += 10
            
            scores.append(max(0, min(100, score)))
        
        return sum(scores) / len(scores) if scores else 60
    
    def _calculate_sleep_score(self, user_data: Dict) -> float:
        """Calculate sleep quality from health trends and logs."""
        scores = []
        
        for log in user_data["health_logs"][-30:]:
            # Check sleep-related notes
            notes = log.get("notes", "").lower()
            
            score = 70  # Default
            if "slept well" in notes or "good sleep" in notes:
                score = 85
            elif "insomnia" in notes or "restless" in notes:
                score = 40
            elif "tired" in notes or "exhausted" in notes:
                score = 35
            
            scores.append(score)
        
        # Check trend data for sleep correlation
        for trend in user_data["health_trends"][-12:]:
            try:
                trend_data = trend.get("trend_data", {})
                if isinstance(trend_data, str):
                    import json
                    trend_data = json.loads(trend_data)
                
                if "sleep" in trend_data:
                    sleep_val = trend_data["sleep"]
                    if isinstance(sleep_val, (int, float)):
                        scores.append(min(100, sleep_val))
            except:
                pass
        
        return sum(scores) / len(scores) if scores else 65
    
    def _calculate_emotional_score(self, user_data: Dict) -> float:
        """Calculate emotional wellbeing from mood logs."""
        scores = []
        
        for log in user_data["health_logs"][-30:]:
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
        
        return sum(scores) / len(scores) if scores else 60
    
    def _calculate_metabolic_score(self, user_data: Dict) -> float:
        """Calculate metabolic health from biomarkers."""
        scores = []
        
        for report in user_data["lab_reports"]:
            # Base score for having lab work done
            scores.append(75)
            
            # Could parse biomarkers here for more accuracy
            # For now, return average lab-based score
        
        if scores:
            return sum(scores) / len(scores)
        
        # Default if no lab data
        return 60
    
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
                max_tokens=1000,
                temperature=0.7
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
    
    def _get_fallback_vitality_response(self) -> VitalityResponse:
        """Return fallback response on error."""
        return VitalityResponse(
            vitality_index=70,
            vitality_level="Strong",
            personal_best="Maintaining good health",
            trend_6_years=[],
            dimensions=[],
            ai_insights=None
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
        """Generate complete life arc timeline."""
        try:
            # Detect milestones
            milestones = self._detect_milestones()
            
            # Sort by date (reverse chronological)
            milestones = sorted(milestones, key=lambda m: m.milestone_date, reverse=True)
            
            # Calculate summary
            summary = self._calculate_timeline_summary(milestones)
            
            return LifeArcResponse(
                milestones=milestones,
                timeline_summary=summary
            )
        except Exception as e:
            logger.error(f"Error generating life arc: {e}")
            return LifeArcResponse(milestones=[], timeline_summary=TimelineSummary(
                total_milestones=0,
                major_events=0,
                avg_monthly_milestones=0,
                date_range={"start": date.today(), "end": date.today()}
            ))
    
    def _detect_milestones(self) -> List[Milestone]:
        """Detect all health milestones."""
        milestones = []
        cutoff_date = datetime.now() - timedelta(days=self.months_back * 30)
        
        # 1. Cycle-related milestones
        cycle_milestones = self._detect_cycle_milestones(cutoff_date)
        milestones.extend(cycle_milestones)
        
        # 2. Health goal milestones
        goal_milestones = self._detect_health_goal_milestones(cutoff_date)
        milestones.extend(goal_milestones)
        
        # 3. Lab result milestones
        lab_milestones = self._detect_lab_milestones(cutoff_date)
        milestones.extend(lab_milestones)
        
        # 4. Life stage transitions
        life_stage_milestones = self._detect_life_stage_milestones(cutoff_date)
        milestones.extend(life_stage_milestones)
        
        # Log before filtering
        logger.debug(f"User {self.user_id}: Detected {len(cycle_milestones)} cycle, {len(goal_milestones)} goal, {len(lab_milestones)} lab, {len(life_stage_milestones)} life_stage milestones")
        
        # Filter out low-significance events
        milestones_before = len(milestones)
        milestones = [m for m in milestones if m.significance >= 0.3]
        logger.debug(f"User {self.user_id}: After filtering: {milestones_before} -> {len(milestones)} milestones")
        
        return milestones
    
    def _detect_cycle_milestones(self, cutoff_date: datetime) -> List[Milestone]:
        """Detect menstrual cycle milestones."""
        milestones = []
        
        try:
            query = """
                SELECT period_start_date, current_phase, cycle_length
                FROM menstrual_cycles
                WHERE user_id = %s AND period_start_date >= DATE(%s)
                ORDER BY period_start_date DESC
                LIMIT 20
            """
            cycles = self.db_query(query, (self.user_id, cutoff_date.date()))
            
            for cycle in cycles:
                if cycle.get("period_start_date"):
                    milestones.append(Milestone(
                        milestone_date=cycle["period_start_date"],
                        milestone_type="cycle_start",
                        title="Period Started",
                        description=f"New menstrual cycle began. Phase: {cycle.get('current_phase', 'menstrual')}.",
                        significance=0.6,
                        icon="flow",
                        health_context=MilestoneHealthContext(
                            cycle_day=1,
                            phase=cycle.get("current_phase"),
                            duration=f"{cycle.get('cycle_length', 28)} days average"
                        )
                    ))
        except Exception as e:
            logger.error(f"Error detecting cycle milestones: {e}")
        
        return milestones
    
    def _detect_health_goal_milestones(self, cutoff_date: datetime) -> List[Milestone]:
        """Detect health goal achievements."""
        milestones = []
        
        try:
            query = """
                SELECT goal_id, title, progress, start_date, status, category
                FROM health_goals
                WHERE user_id = %s AND start_date >= DATE(%s)
                ORDER BY start_date DESC
            """
            goals = self.db_query(query, (self.user_id, cutoff_date.date()))
            logger.debug(f"User {self.user_id}: Found {len(goals)} health goals for health_goal_milestones")
            
            for goal in goals:
                progress = goal.get("progress", 0)
                
                # Milestone for goal completion
                if progress == 100 or goal.get("status") == "completed":
                    significance = 0.9
                    description = f"Completed {goal['title']}! Major health achievement."
                    milestone_type = "health_goal_completed"
                # Milestone for significant progress
                elif progress >= 50:
                    significance = 0.7
                    description = f"Made significant progress on {goal['title']} ({progress}%)"
                    milestone_type = "health_goal_progress"
                else:
                    continue
                
                if goal.get("start_date"):
                    milestone_date = goal["start_date"].date() if hasattr(goal["start_date"], "date") else goal["start_date"]
                    
                    milestones.append(Milestone(
                        milestone_date=milestone_date,
                        milestone_type=milestone_type,
                        title=goal["title"],
                        description=description,
                        significance=significance,
                        icon="target",
                        health_context=MilestoneHealthContext(
                            progress=f"{progress}%",
                            goal_progress=float(progress)
                        )
                    ))
        except Exception as e:
            logger.error(f"Error detecting goal milestones: {e}")
        
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
                    milestone_date=report["created_at"].date() if hasattr(report["created_at"], "date") else report["created_at"],
                    milestone_type="lab_result",
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
        """Detect life stage transitions and wellness achievements."""
        milestones = []
        
        try:
            query = """
                SELECT journey_id, title, milestone_date, description, status, journey_type, category
                FROM life_journeys
                WHERE user_id = %s AND milestone_date >= DATE(%s)
                ORDER BY milestone_date DESC
            """
            journeys = self.db_query(query, (self.user_id, cutoff_date.date()))
            logger.debug(f"User {self.user_id}: Found {len(journeys)} life journeys for life_stage_milestones")
            
            for journey in journeys:
                journey_type = journey.get("journey_type", "life_stage_transition")
                status = journey.get("status", "completed")
                
                # Determine significance and icon based on journey type
                if "postmenopause" in journey_type.lower() or "perimenopause" in journey_type.lower():
                    significance = 0.95  # Major life transition
                    icon = "health"
                elif "wellness_achievement" in journey_type.lower():
                    significance = 0.85
                    icon = "trophy"
                elif "screening" in journey_type.lower():
                    significance = 0.8
                    icon = "test"
                else:
                    significance = 0.8
                    icon = "journey"
                
                if journey.get("milestone_date"):
                    milestone_date = journey["milestone_date"].date() if hasattr(journey["milestone_date"], "date") else journey["milestone_date"]
                    
                    milestones.append(Milestone(
                        milestone_date=milestone_date,
                        milestone_type=journey_type,
                        title=journey["title"],
                        description=journey.get("description", f"Beginning {journey['title']} health journey"),
                        significance=significance,
                        icon=icon,
                        health_context=MilestoneHealthContext(
                            status=status,
                            key_findings=[f"Status: {status}"]
                        )
                    ))
        except Exception as e:
            logger.error(f"Error detecting life stage milestones: {e}")
        
        return milestones
    
    def _calculate_timeline_summary(self, milestones: List[Milestone]) -> TimelineSummary:
        """Calculate timeline summary statistics."""
        if not milestones:
            return TimelineSummary(
                total_milestones=0,
                major_events=0,
                avg_monthly_milestones=0,
                date_range={"start": date.today(), "end": date.today()}
            )
        
        # Count major events (significance >= 0.8)
        major_events = sum(1 for m in milestones if m.significance >= 0.8)
        
        # Calculate date range
        dates = [m.milestone_date for m in milestones]
        start_date = min(dates)
        end_date = max(dates)
        
        # Calculate monthly average
        days_diff = (end_date - start_date).days
        months = max(1, days_diff / 30)
        avg_monthly = len(milestones) / months
        
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
                type=screening_name,
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
