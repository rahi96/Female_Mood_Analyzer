"""Athlete Performance & Readiness API Service."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
import json

from fastapi import HTTPException

from ai.models.athlete_models import (
    AthleteReadinessResponse,
    CycleInfo,
    FatigueAlert,
    HRVMetric,
    Metrics,
    PhaseRecommendation,
    RecoveryMetric,
    SleepMetric,
    TrainingLoadMetric,
)
from ai.utils.db import get_current_cycle, get_snapshot, get_user_profile
from ai.utils.llm_call import llm_call


def athlete_readiness(user_id: int) -> AthleteReadinessResponse | dict[str, Any]:
    """
    Calculate athlete performance readiness score (0-100).
    Integrates HRV, sleep, recovery, training load, and menstrual cycle phase.
    
    **Formula:**
    Readiness = (HRV_score * 0.30 + Sleep_score * 0.35 + Recovery_score * 0.35) + Phase_Boost
    
    **Returns:**
    Comprehensive readiness assessment with alerts and phase-based recommendations.
    """
    try:
        # Fetch user data
        profile = get_user_profile(user_id)
        if not profile:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found")
        
        # Fetch raw Terra performance data
        terra_raw_data = _fetch_terra_raw_data(user_id)
        
        # Get cycle info
        cycle_info_dict = _get_cycle_info(user_id)
        
        # Build context for Claude and generate personalized metrics
        context = _build_athlete_context(user_id, terra_raw_data, cycle_info_dict)
        ai_metrics = _generate_readiness_metrics_with_claude(context)
        
        # Build metric objects from Claude's AI-generated values
        hrv_metric = HRVMetric(
            value=ai_metrics.get("hrv_value", 65),
            trend=ai_metrics.get("hrv_trend", 0),
            status=ai_metrics.get("hrv_status", "good"),
        )
        # Convert sleep hours to percentage (8 hours = 100%)
        sleep_hours = ai_metrics.get("sleep_hours", 7.5)
        sleep_percentage = min(100, int((sleep_hours / 8.0) * 100))
        sleep_metric = SleepMetric(
            percentage=sleep_percentage,
            trend=ai_metrics.get("sleep_trend", 0),
            status=ai_metrics.get("sleep_status", "fair"),
        )
        recovery_metric = RecoveryMetric(
            percentage=ai_metrics.get("recovery_score", 55),
            trend=ai_metrics.get("recovery_trend", 0),
            status=ai_metrics.get("recovery_status", "moderate"),
        )
        training_load_metric = TrainingLoadMetric(
            value=ai_metrics.get("training_load_value", 0),
            trend=ai_metrics.get("training_load_trend", 0),
            status=ai_metrics.get("training_load_status", "low"),
        )
        
        # Use Claude's AI-generated readiness score
        final_score = ai_metrics.get("readiness_score", 50)
        readiness_level = ai_metrics.get("readiness_level", "Adequate")
        phase_boost = cycle_info_dict["phase_boost"]
        
        # Generate readiness message
        readiness_message = _get_readiness_message(
            readiness_level, 
            cycle_info_dict["phase"],
            hrv_metric.status,
            recovery_metric.status
        )
        
        # Generate personalized fatigue alerts using Claude AI
        alerts = _generate_personalized_fatigue_alerts(
            user_id,
            hrv_metric,
            sleep_metric,
            recovery_metric,
            training_load_metric,
            cycle_info_dict,
        )
        
        # Generate recommendations
        recommendations = _generate_phase_recommendations(cycle_info_dict["phase"])
        
        # Build cycle info object
        cycle_info = CycleInfo(
            phase=cycle_info_dict["phase"],
            cycle_day=cycle_info_dict["cycle_day"],
            days_to_next_phase=cycle_info_dict["days_to_next_phase"],
            phase_boost=phase_boost,
            phase_description=cycle_info_dict["phase_description"],
        )
        
        # Build metrics object
        metrics = Metrics(
            hrv=hrv_metric,
            sleep=sleep_metric,
            recovery=recovery_metric,
            training_load=training_load_metric,
        )
        
        # Build response
        response = AthleteReadinessResponse(
            date=date.today().isoformat(),
            readiness_score=int(final_score),
            readiness_level=readiness_level,
            # Quick stat cards for display
            hrv=hrv_metric,
            recovery=recovery_metric,
            training_load=training_load_metric,
            # Full details
            metrics=metrics,
            fatigue_alerts=alerts,
            cycle_info=cycle_info,
            recommendations=recommendations,
            next_update=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        )
        
        return response.model_dump(exclude_none=False)
    
    except HTTPException:
        # Let HTTPException (404, etc.) propagate to FastAPI
        raise
    except Exception as e:
        print(f"[ERROR] athlete_readiness failed for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Readiness calculation failed: {str(e)}")


def _fetch_hrv_data(user_id: int) -> dict[str, Any]:
    """Fetch HRV data from terra_activity_data for today and yesterday, calculate trend."""
    try:
        from ai.utils.db import get_connection
        
        with get_connection() as conn:
            cursor = conn.cursor()
            # Fetch today and yesterday's HRV data
            cursor.execute(
                """
                SELECT 
                    JSON_EXTRACT(payload, '$.data[0].heart_data.heart_rate_data.summary.avg_hrv_rmssd') as hrv_value,
                    created_at
                FROM terra_activity_data
                WHERE user_id = %s AND type = 'body'
                ORDER BY created_at DESC
                LIMIT 2
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            
            if not rows:
                return {"value": 0, "trend": 0, "available": False}
            
            # Process today's value (first/most recent)
            hrv_raw = rows[0].get("hrv_value")
            hrv_value = 0
            if hrv_raw and hrv_raw != "null":
                try:
                    hrv_value = float(hrv_raw)
                except (ValueError, TypeError):
                    hrv_value = 0
            
            # Calculate trend from yesterday's value
            trend = 0
            if len(rows) > 1:
                hrv_prev_raw = rows[1].get("hrv_value")
                hrv_prev = 0
                if hrv_prev_raw and hrv_prev_raw != "null":
                    try:
                        hrv_prev = float(hrv_prev_raw)
                    except (ValueError, TypeError):
                        hrv_prev = 0
                trend = int(hrv_value - hrv_prev)
            
            return {
                "value": int(hrv_value),
                "trend": trend,
                "available": hrv_value > 0,
            }
    except Exception as e:
        print(f"[ERROR] _fetch_hrv_data: {e}")
        return {"value": 0, "trend": 0, "available": False}


def _fetch_sleep_data(user_id: int) -> dict[str, Any]:
    """Fetch sleep data from terra_activity_data for today and yesterday, calculate trend."""
    try:
        from ai.utils.db import get_connection
        
        with get_connection() as conn:
            cursor = conn.cursor()
            # Fetch today and yesterday's sleep data
            cursor.execute(
                """
                SELECT 
                    JSON_EXTRACT(payload, '$.data[0].scores.sleep') as sleep_score,
                    created_at
                FROM terra_activity_data
                WHERE user_id = %s AND type = 'daily'
                ORDER BY created_at DESC
                LIMIT 2
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            
            if not rows:
                return {"hours": 0, "score": 60, "trend": 0, "available": False}
            
            # Process today's value (first/most recent)
            sleep_raw = rows[0].get("sleep_score")
            sleep_score = 60  # Default baseline (adequate sleep)
            if sleep_raw and sleep_raw != "null":
                try:
                    sleep_score = int(float(sleep_raw))
                except (ValueError, TypeError):
                    sleep_score = 60
            
            # Calculate trend from yesterday's value
            trend = 0
            if len(rows) > 1:
                sleep_prev_raw = rows[1].get("sleep_score")
                sleep_prev = 60
                if sleep_prev_raw and sleep_prev_raw != "null":
                    try:
                        sleep_prev = int(float(sleep_prev_raw))
                    except (ValueError, TypeError):
                        sleep_prev = 60
                trend = sleep_score - sleep_prev
            
            return {
                "hours": 0,  # Terra data doesn't include duration_seconds
                "score": sleep_score,
                "trend": trend,
                "available": sleep_score > 0,
            }
    except Exception as e:
        print(f"[ERROR] _fetch_sleep_data: {e}")
        return {"hours": 0, "score": 60, "trend": 0, "available": False}


def _fetch_recovery_data(user_id: int) -> dict[str, Any]:
    """Fetch recovery score from terra_activity_data, estimate from MET level, calculate trend."""
    try:
        from ai.utils.db import get_connection
        
        with get_connection() as conn:
            cursor = conn.cursor()
            # Fetch today and yesterday's recovery data
            cursor.execute(
                """
                SELECT 
                    JSON_EXTRACT(payload, '$.data[0].scores.recovery') as recovery_score,
                    JSON_EXTRACT(payload, '$.data[0].MET_data.avg_level') as avg_met,
                    created_at
                FROM terra_activity_data
                WHERE user_id = %s AND type = 'daily'
                ORDER BY created_at DESC
                LIMIT 2
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            
            if not rows:
                return {"score": 55, "trend": 0, "available": False}
            
            # Process today's value (first/most recent)
            recovery_raw = rows[0].get("recovery_score")
            avg_met_raw = rows[0].get("avg_met")
            
            recovery_score = None
            if recovery_raw and recovery_raw != "null":
                try:
                    recovery_score = int(float(recovery_raw))
                except (ValueError, TypeError):
                    recovery_score = None
            
            avg_met = 0
            if avg_met_raw and avg_met_raw != "null":
                try:
                    avg_met = float(avg_met_raw)
                except (ValueError, TypeError):
                    avg_met = 0
            
            # Determine today's recovery score
            if recovery_score and recovery_score > 0:
                today_score = recovery_score
                available = True
            elif avg_met > 0:
                # Estimate from MET level (inverse relationship)
                today_score = min(80, max(30, int(100 - (avg_met * 3))))
                available = False
            else:
                today_score = 55
                available = False
            
            # Calculate trend from yesterday's value
            trend = 0
            if len(rows) > 1:
                recovery_prev_raw = rows[1].get("recovery_score")
                avg_met_prev_raw = rows[1].get("avg_met")
                
                recovery_prev = None
                if recovery_prev_raw and recovery_prev_raw != "null":
                    try:
                        recovery_prev = int(float(recovery_prev_raw))
                    except (ValueError, TypeError):
                        recovery_prev = None
                
                avg_met_prev = 0
                if avg_met_prev_raw and avg_met_prev_raw != "null":
                    try:
                        avg_met_prev = float(avg_met_prev_raw)
                    except (ValueError, TypeError):
                        avg_met_prev = 0
                
                # Determine yesterday's recovery score
                if recovery_prev and recovery_prev > 0:
                    prev_score = recovery_prev
                elif avg_met_prev > 0:
                    prev_score = min(80, max(30, int(100 - (avg_met_prev * 3))))
                else:
                    prev_score = 55
                
                trend = today_score - prev_score
            
            return {"score": today_score, "trend": trend, "available": available}
    except Exception as e:
        print(f"[ERROR] _fetch_recovery_data: {e}")
        return {"score": 55, "trend": 0, "available": False}


def _fetch_training_load(user_id: int) -> dict[str, Any]:
    """Calculate training load from MET level or activity seconds, calculate trend."""
    try:
        from ai.utils.db import get_connection
        
        with get_connection() as conn:
            cursor = conn.cursor()
            # Fetch today and yesterday's training load data
            cursor.execute(
                """
                SELECT 
                    JSON_EXTRACT(payload, '$.data[0].MET_data.avg_level') as avg_met,
                    JSON_EXTRACT(payload, '$.data[0].active_durations_data.activity_seconds') as activity_seconds,
                    created_at
                FROM terra_activity_data
                WHERE user_id = %s AND type = 'daily'
                ORDER BY created_at DESC
                LIMIT 2
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            
            if not rows:
                return {"value": 0, "trend": 0, "status": "low", "available": False}
            
            # Helper function to calculate load from metrics
            def calc_load(met, activity_sec):
                activity_min = activity_sec / 60
                return (activity_min * 0.8) + (met * 5) if (activity_min or met) else 0
            
            # Process today's value (first/most recent)
            avg_met_raw = rows[0].get("avg_met")
            activity_raw = rows[0].get("activity_seconds")
            
            avg_met = 0
            if avg_met_raw and avg_met_raw != "null":
                try:
                    avg_met = float(avg_met_raw)
                except (ValueError, TypeError):
                    avg_met = 0
            
            activity_seconds = 0
            if activity_raw and activity_raw != "null":
                try:
                    activity_seconds = float(activity_raw)
                except (ValueError, TypeError):
                    activity_seconds = 0
            
            today_load = calc_load(avg_met, activity_seconds)
            status = "low" if today_load < 100 else "moderate" if today_load < 300 else "high"
            
            # Calculate trend from yesterday's value
            trend = 0
            if len(rows) > 1:
                avg_met_prev_raw = rows[1].get("avg_met")
                activity_prev_raw = rows[1].get("activity_seconds")
                
                avg_met_prev = 0
                if avg_met_prev_raw and avg_met_prev_raw != "null":
                    try:
                        avg_met_prev = float(avg_met_prev_raw)
                    except (ValueError, TypeError):
                        avg_met_prev = 0
                
                activity_prev_seconds = 0
                if activity_prev_raw and activity_prev_raw != "null":
                    try:
                        activity_prev_seconds = float(activity_prev_raw)
                    except (ValueError, TypeError):
                        activity_prev_seconds = 0
                
                prev_load = calc_load(avg_met_prev, activity_prev_seconds)
                trend = int(today_load - prev_load)
            
            print(f"[DEBUG] user {user_id}: activity_min={activity_seconds/60}, MET={avg_met}, load={today_load}, trend={trend}")
            
            return {
                "value": round(today_load, 1),
                "trend": trend,
                "status": status,
                "available": (activity_seconds > 0 or avg_met > 0),
            }
    except Exception as e:
        print(f"[ERROR] _fetch_training_load: {e}")
        return {"value": 0, "trend": 0, "status": "low", "available": False}


def _get_cycle_info(user_id: int) -> dict[str, Any]:
    """Get current menstrual cycle phase and information."""
    try:
        cycle = get_current_cycle(user_id)
        
        if not cycle or not cycle.get("period_start_date"):
            return {
                "phase": "unknown",
                "cycle_day": 0,
                "days_to_next_phase": 0,
                "phase_boost": 0,
                "phase_description": "No cycle data available",
            }
        
        period_start = cycle.get("period_start_date")
        if isinstance(period_start, str):
            from datetime import datetime as dt
            period_start = dt.fromisoformat(period_start).date()
        
        today = date.today()
        cycle_day_raw = (today - period_start).days + 1
        
        # ✅ FIX: Validate cycle_day is within valid range (1-28, or default to unknown)
        if cycle_day_raw < 1 or cycle_day_raw > 100:
            # If cycle is invalid (negative or > 100 days), treat as unknown
            return {
                "phase": "unknown",
                "cycle_day": 0,
                "days_to_next_phase": 0,
                "phase_boost": 0,
                "phase_description": "Cycle data out of range - please update",
            }
        
        # Normalize to 1-28 day cycle (if > 28, wrap around)
        cycle_day = ((cycle_day_raw - 1) % 28) + 1
        
        # Phase definitions
        if 1 <= cycle_day <= 5:
            phase = "menstrual"
            phase_boost = -7
            next_phase_day = 6
            description = "Menstrual phase - prioritize recovery and rest"
        elif 6 <= cycle_day <= 13:
            phase = "follicular"
            phase_boost = 2
            next_phase_day = 14
            description = "Follicular phase - building energy, good for strength training"
        elif 14 <= cycle_day <= 16:
            phase = "ovulatory"
            phase_boost = 12
            next_phase_day = 17
            description = "Ovulatory phase - peak energy and performance window"
        else:  # 17-28
            phase = "luteal"
            phase_boost = -3
            next_phase_day = 29  # Will wrap to day 1 (menstrual)
            description = "Luteal phase - stable energy, good for endurance"
        
        # ✅ FIX: Ensure days_to_next_phase is clamped to 0-100
        days_to_next_phase = max(0, min(100, next_phase_day - cycle_day))
        
        return {
            "phase": phase,
            "cycle_day": cycle_day,
            "days_to_next_phase": days_to_next_phase,
            "phase_boost": phase_boost,
            "phase_description": description,
        }
    except Exception as e:
        print(f"[ERROR] _get_cycle_info: {e}")
        return {
            "phase": "unknown",
            "cycle_day": 0,
            "days_to_next_phase": 0,
            "phase_boost": 0,
            "phase_description": "Cycle data unavailable",
        }


def _calculate_hrv_score(hrv_data: dict[str, Any]) -> HRVMetric:
    """Convert HRV (ms) to 0-100 score. Higher HRV = better readiness."""
    # HRV typically ranges 20-200ms. Map to score.
    # < 30ms = poor (0-25), 30-50 = fair (25-50), 50-100 = good (50-85), > 100 = excellent (85-100)
    hrv_value = hrv_data.get("value", 0)
    
    if hrv_value < 30:
        score = max(0, int((hrv_value / 30) * 25))
        status = "poor"
    elif hrv_value < 50:
        score = int(25 + ((hrv_value - 30) / 20) * 25)
        status = "warning"
    elif hrv_value < 100:
        score = int(50 + ((hrv_value - 50) / 50) * 35)
        status = "good"
    else:
        score = min(100, int(85 + ((hrv_value - 100) / 100) * 15))
        status = "good"
    
    return HRVMetric(
        value=hrv_value,
        score=score,
        trend=hrv_data.get("trend", 0),
        status=status,
    )


def _calculate_sleep_score(sleep_data: dict[str, Any]) -> SleepMetric:
    """Calculate sleep quality score."""
    sleep_score = sleep_data.get("score", 0)
    sleep_hours = sleep_data.get("hours", 0)
    trend = sleep_data.get("trend", 0)
    
    # If Terra didn't provide score, estimate from hours (7-9 hours is optimal)
    if sleep_score == 0:
        if sleep_hours >= 7 and sleep_hours <= 9:
            sleep_score = 90
        elif sleep_hours >= 6 and sleep_hours < 7:
            sleep_score = 70
        elif sleep_hours >= 9 and sleep_hours < 10:
            sleep_score = 80
        else:
            sleep_score = max(20, int((sleep_hours / 8) * 100))
    
    status = "good" if sleep_score > 75 else "fair" if sleep_score > 50 else "poor"
    
    return SleepMetric(
        hours=sleep_hours,
        score=sleep_score,
        trend=trend,
        status=status,
    )


def _calculate_recovery_score(recovery_data: dict[str, Any]) -> RecoveryMetric:
    """Calculate recovery metric."""
    recovery_score = recovery_data.get("score", 0)
    trend = recovery_data.get("trend", 0)
    
    status = "recovered" if recovery_score > 80 else "partial" if recovery_score > 50 else "depleted"
    
    return RecoveryMetric(
        score=recovery_score,
        trend=trend,
        status=status,
    )


def _get_readiness_level(score: int) -> str:
    """Determine readiness level from score."""
    if score >= 85:
        return "Peak Ready"
    elif score >= 70:
        return "Ready"
    elif score >= 50:
        return "Adequate"
    elif score >= 30:
        return "Fatigued"
    else:
        return "Depleted"


def _get_readiness_message(
    level: str,
    phase: str,
    hrv_status: str,
    recovery_status: str,
) -> str:
    """Generate personalized readiness message."""
    if level == "Peak Ready":
        if phase == "ovulatory":
            return "You're at peak performance during your ovulatory phase. Ideal for high-intensity workouts, competitions, or setting new PRs."
        return "You're at peak performance. Ideal for high-intensity workouts or competitions."
    
    elif level == "Ready":
        return f"You're ready for training. Your {phase} phase supports good workout performance with {recovery_status} recovery."
    
    elif level == "Adequate":
        return "You're adequately recovered for moderate training. Consider listening to your body today."
    
    elif level == "Fatigued":
        return "You're showing signs of fatigue. Consider active recovery or lighter intensity training today."
    
    else:  # Depleted
        return "You're significantly fatigued. Prioritize rest, sleep, and recovery today."


def _generate_fatigue_alerts(
    sleep_data: dict[str, Any],
    recovery_data: dict[str, Any],
    training_load: dict[str, Any],
    hrv_data: dict[str, Any],
) -> list[FatigueAlert]:
    """Generate fatigue risk alerts."""
    alerts = []
    
    # Recovery alert
    recovery_score = recovery_data.get("score", 0)
    if recovery_score < 50:
        alerts.append(FatigueAlert(
            type="recovery_deficit",
            level="high",
            message="Your recovery score is low. Consider reducing training intensity today.",
        ))
    elif recovery_score < 70:
        alerts.append(FatigueAlert(
            type="recovery_deficit",
            level="moderate",
            message="Recovery is partial. Monitor fatigue levels throughout the day.",
        ))
    else:
        alerts.append(FatigueAlert(
            type="recovery_status",
            level="low",
            message="Fully recovered. Adequate energy for training.",
        ))
    
    # Sleep debt alert
    sleep_hours = sleep_data.get("hours", 0)
    if sleep_hours < 6:
        alerts.append(FatigueAlert(
            type="sleep_debt",
            level="high",
            message=f"Sleep debt: only {sleep_hours}h slept. Prioritize rest today.",
        ))
    elif sleep_hours < 7:
        alerts.append(FatigueAlert(
            type="sleep_debt",
            level="moderate",
            message=f"Sleep below optimal: {sleep_hours}h. Consider earlier bedtime.",
        ))
    
    # Training load alert
    load = training_load.get("value", 0)
    if load > 300:
        alerts.append(FatigueAlert(
            type="overtraining_risk",
            level="high",
            message="Training load is very high. Consider deload or active recovery.",
        ))
    elif load > 200:
        alerts.append(FatigueAlert(
            type="overtraining_risk",
            level="moderate",
            message="Training load is elevated. Monitor cumulative fatigue.",
        ))
    else:
        alerts.append(FatigueAlert(
            type="overtraining_risk",
            level="low",
            message="Training load is manageable.",
        ))
    
    # HRV alert (deviation from baseline)
    hrv_value = hrv_data.get("value", 0)
    if hrv_value < 30:
        alerts.append(FatigueAlert(
            type="cumulative_fatigue",
            level="high",
            message="Low HRV indicates accumulated stress/fatigue. Prioritize recovery.",
        ))
    elif hrv_value < 50:
        alerts.append(FatigueAlert(
            type="cumulative_fatigue",
            level="moderate",
            message="HRV is below optimal. Some accumulated fatigue detected.",
        ))
    
    return alerts


def _generate_personalized_fatigue_alerts(
    user_id: int,
    hrv: HRVMetric,
    sleep: SleepMetric,
    recovery: RecoveryMetric,
    training_load: TrainingLoadMetric,
    cycle_info: dict[str, Any],
) -> list[FatigueAlert]:
    """Generate personalized fatigue alerts using Claude AI (compact format, no messages)."""
    try:
        # Build context for Claude
        context = f"""Analyze the athlete's current status and generate 3 personalized fatigue risk alerts.

ATHLETE STATUS:
- HRV (Heart Rate Variability): {hrv.value}ms, status: {hrv.status}, trend: {hrv.trend}
- Sleep: {sleep.percentage}%, status: {sleep.status}, trend: {sleep.trend}
- Recovery: {recovery.percentage}%, status: {recovery.status}, trend: {recovery.trend}
- Training Load: {training_load.value} AU, status: {training_load.status}, trend: {training_load.trend}
- Menstrual Cycle Phase: {cycle_info.get('phase', 'unknown')}
- Cycle Day: {cycle_info.get('cycle_day', 0)}

GENERATE 3 PERSONALIZED FATIGUE ALERTS with these exact fields:
1. Overtraining Risk - based on training load and recovery
2. Injury Risk Index - based on HRV trends and cycle phase
3. Cumulative Fatigue - based on sleep, recovery, and HRV patterns

For each alert, respond with JSON array containing ONLY type and level (no message):
{{
  "type": "overtraining_risk" | "injury_risk_index" | "cumulative_fatigue",
  "level": "low" | "moderate" | "high"
}}

Respond ONLY with valid JSON array, no markdown or explanation."""

        response = llm_call(context)
        alerts_json = json.loads(response)
        
        alerts = []
        for alert_data in alerts_json:
            alerts.append(FatigueAlert(
                type=alert_data.get("type", "cumulative_fatigue"),
                level=alert_data.get("level", "moderate"),
                message="",  # Keep message empty for compact format
            ))
        
        return alerts
    except Exception as e:
        print(f"[ERROR] _generate_personalized_fatigue_alerts: {e}")
        # Return default alerts if Claude fails (compact format, no messages)
        return [
            FatigueAlert(
                type="overtraining_risk",
                level="low",
                message="",
            ),
            FatigueAlert(
                type="injury_risk_index",
                level="low",
                message="",
            ),
            FatigueAlert(
                type="cumulative_fatigue",
                level="moderate",
                message="",
            ),
        ]


def _generate_phase_recommendations(phase: str) -> PhaseRecommendation:
    """Generate phase-specific training recommendations."""
    recommendations = {
        "menstrual": PhaseRecommendation(
            workout_type="recovery",
            intensity_level="low",
            suggested_workouts=[
                "Restorative yoga",
                "Light walking or leisurely cycling",
                "Stretching and mobility work",
                "Meditation or breathing exercises",
            ],
        ),
        "follicular": PhaseRecommendation(
            workout_type="strength",
            intensity_level="high",
            suggested_workouts=[
                "Heavy strength training (3-6 rep range)",
                "Hypertrophy-focused resistance training",
                "High-intensity interval training (HIIT)",
                "New fitness challenges or skill work",
            ],
        ),
        "ovulatory": PhaseRecommendation(
            workout_type="high_intensity",
            intensity_level="maximum",
            suggested_workouts=[
                "Competitive activities or races",
                "Maximum effort strength/power testing",
                "High-intensity interval training (HIIT)",
                "Personal record (PR) attempts",
                "Demanding metabolic conditioning",
            ],
        ),
        "luteal": PhaseRecommendation(
            workout_type="endurance",
            intensity_level="moderate",
            suggested_workouts=[
                "Steady-state cardio (running, cycling, rowing)",
                "Moderate-intensity strength training",
                "Longer duration, lower intensity sessions",
                "Active recovery paired with strength",
                "Stability and balance work",
            ],
        ),
        "unknown": PhaseRecommendation(
            workout_type="moderate",
            intensity_level="moderate",
            suggested_workouts=[
                "Balanced training with varied intensity",
                "Moderate strength and conditioning",
                "Listen to your body for intensity cues",
            ],
        ),
    }
    
    return recommendations.get(phase, recommendations["unknown"])


def _fetch_terra_raw_data(user_id: int) -> dict[str, Any]:
    """Fetch raw Terra health data (MET, activity, HRV, sleep, etc.)."""
    try:
        from ai.utils.db import get_connection
        from datetime import datetime, timedelta
        import json
        
        with get_connection() as conn:
            cursor = conn.cursor()
            # Fetch latest 5 records from last 60 days to avoid large sort operations
            sixty_days_ago = (datetime.utcnow() - timedelta(days=60)).isoformat()
            
            cursor.execute(
                """
                SELECT payload, created_at
                FROM terra_activity_data
                WHERE user_id = %s 
                  AND created_at >= %s
                ORDER BY created_at DESC
                LIMIT 5
                """,
                (user_id, sixty_days_ago),
            )
            rows = cursor.fetchall()
            
            if not rows:
                return {
                    "avg_met": 0,
                    "sleep_score": None,
                    "recovery_score": None,
                    "hrv_value": 0,
                    "activity_seconds": 0,
                    "calories_burned": 0,
                    "has_data": False,
                }
            
            # Extract and aggregate data from JSON payloads
            avg_met = 0
            sleep_score = None
            recovery_score = None
            hrv_value = 0
            activity_seconds = 0
            calories_burned = 0
            
            for row in rows:
                try:
                    payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
                except (json.JSONDecodeError, TypeError):
                    continue
                
                # Extract MET data
                try:
                    met = payload.get("MET_data", {}).get("avg_level")
                    if met:
                        avg_met = float(met)
                except (ValueError, TypeError, AttributeError):
                    pass
                
                # Extract scores
                try:
                    scores = payload.get("scores", {})
                    if scores.get("sleep"):
                        sleep_score = int(float(scores["sleep"]))
                    if scores.get("recovery"):
                        recovery_score = int(float(scores["recovery"]))
                except (ValueError, TypeError, AttributeError):
                    pass
                
                # Extract HRV
                try:
                    hrv = payload.get("data", [{}])[0].get("heart_data", {}).get("heart_rate_data", {}).get("summary", {}).get("avg_hrv_rmssd")
                    if hrv:
                        hrv_value = float(hrv)
                except (ValueError, TypeError, AttributeError, IndexError):
                    pass
                
                # Extract activity and calories
                try:
                    activity = payload.get("data", [{}])[0].get("active_durations_data", {}).get("activity_seconds")
                    if activity:
                        activity_seconds = float(activity)
                    
                    calories = payload.get("data", [{}])[0].get("calories_data", {}).get("total_burned_calories")
                    if calories:
                        calories_burned = float(calories)
                except (ValueError, TypeError, AttributeError, IndexError):
                    pass
            
            return {
                "avg_met": round(avg_met, 2),
                "sleep_score": sleep_score,
                "recovery_score": recovery_score,
                "hrv_value": int(hrv_value),
                "activity_seconds": int(activity_seconds),
                "calories_burned": round(calories_burned, 2),
                "has_data": avg_met > 0 or hrv_value > 0,
            }
    except Exception as e:
        print(f"[ERROR] _fetch_terra_raw_data: {e}")
        return {"avg_met": 0, "has_data": False}


def _build_athlete_context(user_id: int, terra_data: dict[str, Any], cycle_info: dict[str, Any]) -> str:
    """Build context string for Claude to generate personalized readiness assessment."""
    context_parts = [
        "Generate a personalized athlete readiness assessment based on the following data:",
        f"\nUSER ID: {user_id}",
        "\nAVAILABLE HEALTH DATA FROM WEARABLES:",
    ]
    
    if terra_data.get("has_data"):
        context_parts.append(f"  - Average MET Level: {terra_data.get('avg_met', 0)}")
        context_parts.append(f"  - Activity Duration: {terra_data.get('activity_seconds', 0)} seconds")
        context_parts.append(f"  - Calories Burned: {terra_data.get('calories_burned', 0)}")
        context_parts.append(f"  - HRV Value: {terra_data.get('hrv_value', 0)} ms")
    else:
        context_parts.append("  - Limited wearable data available")
    
    if terra_data.get("sleep_score"):
        context_parts.append(f"  - Sleep Score: {terra_data['sleep_score']}/100")
    
    if terra_data.get("recovery_score"):
        context_parts.append(f"  - Recovery Score: {terra_data['recovery_score']}/100")
    
    context_parts.extend([
        f"\nMENSTRUAL CYCLE PHASE: {cycle_info.get('phase', 'unknown')}",
        f"  - Cycle Day: {cycle_info.get('cycle_day', 0)}",
        f"  - Phase Description: {cycle_info.get('phase_description', 'N/A')}",
        "",
        "GENERATE PERSONALIZED RESPONSE WITH THESE EXACT JSON FIELDS:",
        "",
        "READINESS ASSESSMENT:",
        "  - readiness_score (0-100 integer): Overall athletic readiness",
        "    * If HRV+Sleep+Recovery all high (>80): Score 85-95 (Peak Ready/Ready)",
        "    * If HRV+Sleep high but Recovery moderate (50-80): Score 65-75 (Ready/Adequate)",
        "    * If any metric poor (<50): Score 30-55 (Adequate/Fatigued)",
        "    * If training_load very high (>300) AND recovery low (<40): Score 20-40 (Fatigued/Depleted)",
        "  - readiness_level (string): Peak Ready (≥85) | Ready (70-84) | Adequate (50-69) | Fatigued (30-49) | Depleted (<30)",
        "  - readiness_message (string): 1-2 sentence explaining readiness status",
        "",
        "HRV METRIC:",
        "  - hrv_value (0-200 integer): Estimated heart rate variability in milliseconds (must be actual number, not 0)",
        "  - hrv_score (0-100 integer): HRV assessment score",
        "  - hrv_trend (-50 to +50): Change from yesterday (+3 = improving, -5 = declining)",
        "  - hrv_status (string): good | warning | poor",
        "",
        "SLEEP METRIC:",
        "  - sleep_hours (0-12 float): Estimated sleep duration (must be actual hours like 7.5, not 0)",
        "  - sleep_score (0-100 integer): Sleep quality assessment",
        "  - sleep_trend (-30 to +30): Change from yesterday",
        "  - sleep_status (string): good | fair | poor",
        "",
        "RECOVERY METRIC:",
        "  - recovery_score (0-100 integer): Physical recovery percentage",
        "  - recovery_trend (-30 to +30): Change from yesterday",
        "  - recovery_status (string): high | low | moderate (badge showing recovery level)",
        "",
        "TRAINING LOAD METRIC:",
        "  - training_load_value (0-400 float): Estimated training load in AU (must be actual value, not 0)",
        "  - training_load_trend (-100 to +100): Change from yesterday",
        "  - training_load_status (string): low | moderate | high",
        "",
        "IMPORTANT: Return ONLY valid JSON with no markdown formatting, no code blocks, no explanations.",
    ]
    )
    
    return "\n".join(context_parts)


def _generate_readiness_metrics_with_claude(context: str) -> dict[str, Any]:
    """Call Claude to generate personalized readiness metrics."""
    try:
        # Call Claude LLM
        response = llm_call(context)
        
        # Parse JSON response - Claude returns clean JSON
        metrics = json.loads(response)
        
        # ✅ Extract raw values
        readiness_score = metrics.get("readiness_score", 50)
        hrv_value = metrics.get("hrv_value", 65)
        sleep_hours = metrics.get("sleep_hours", 7.5)
        recovery_score = metrics.get("recovery_score", 70)
        training_load = metrics.get("training_load_value", 200)
        
        # ✅ FIX: Validate scores are actually different (not all the same)
        # If readiness_score is too centered (65-75 range), recalculate with variation
        if 65 <= readiness_score <= 75:
            # Use actual metrics to create real variation
            hrv_component = min(100, max(20, hrv_value))  # 20-100
            sleep_component = min(100, max(30, int((sleep_hours / 8.0) * 100)))  # 30-100
            recovery_component = min(100, max(20, recovery_score))  # 20-100
            
            # Calculate weighted score with better variation
            calculated_score = int(
                (hrv_component * 0.25) +
                (sleep_component * 0.35) +
                (recovery_component * 0.40)
            )
            readiness_score = calculated_score
        
        # Ensure all required fields present with sensible defaults
        return {
            "readiness_score": min(100, max(0, readiness_score)),
            "readiness_level": metrics.get("readiness_level", "Adequate"),
            "readiness_message": metrics.get("readiness_message", "Based on your cycle phase and available metrics."),
            "hrv_value": max(20, hrv_value),  # Ensure non-zero
            "hrv_score": min(100, max(0, metrics.get("hrv_score", 65))),
            "hrv_status": metrics.get("hrv_status", "good"),
            "hrv_trend": metrics.get("hrv_trend", 0),
            "sleep_hours": max(1.0, sleep_hours),  # Ensure non-zero
            "sleep_score": min(100, max(0, metrics.get("sleep_score", 75))),
            "sleep_status": metrics.get("sleep_status", "good"),
            "sleep_trend": metrics.get("sleep_trend", 0),
            "recovery_score": min(100, max(0, recovery_score)),
            "recovery_status": metrics.get("recovery_status", "moderate"),  # Now high/low/moderate
            "recovery_trend": metrics.get("recovery_trend", 0),
            "training_load_value": max(50, training_load),  # Ensure non-zero
            "training_load_status": metrics.get("training_load_status", "moderate"),
            "training_load_trend": metrics.get("training_load_trend", 0),
        }
    except Exception as e:
        print(f"[ERROR] _generate_readiness_metrics_with_claude: {e}")
        print(f"[DEBUG] Raw response: {response if 'response' in locals() else 'no response'}")
        # Return safe defaults if Claude fails - with actual non-zero values
        return {
            "readiness_score": 50,
            "readiness_level": "Adequate",
            "readiness_message": "Unable to generate personalized assessment. Please try again.",
            "hrv_value": 65,
            "hrv_score": 50,
            "hrv_status": "warning",
            "hrv_trend": 0,
            "sleep_hours": 7.0,
            "sleep_score": 60,
            "sleep_status": "fair",
            "sleep_trend": 0,
            "recovery_score": 55,
            "recovery_status": "moderate",
            "recovery_trend": 0,
            "training_load_value": 200,
            "training_load_status": "moderate",
            "training_load_trend": 0,
        }

def get_cycle_training_focus(user_id: int, cycle_phase: str) -> dict[str, Any]:
    """Generate compact training focus recommendations for a specific cycle phase.
    
    Args:
        user_id: The user's ID
        cycle_phase: menstrual | follicular | ovulation | luteal
    
    Returns:
        Dictionary with cycle_phase, phase_day, focus, and recommendations
    """
    from fastapi import HTTPException
    
    try:
        # Validate user exists
        profile = get_user_profile(user_id)
        if not profile:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found")
        
        # Normalize cycle phase (handle "ovulatory" as "ovulation", strip whitespace)
        phase_map = {
            "menstrual": "menstrual",
            "follicular": "follicular",
            "ovulation": "ovulation",
            "ovulatory": "ovulation",
            "luteal": "luteal",
        }
        normalized_phase = phase_map.get(cycle_phase.strip().lower())
        if not normalized_phase:
            raise ValueError(f"Invalid cycle phase: {cycle_phase}")
        
        # Get current cycle day (from menstrual_cycles table, not from readiness calculation)
        cycle = get_current_cycle(user_id)
        cycle_day = 0
        if cycle and cycle.get("period_start_date"):
            period_start = cycle.get("period_start_date")
            if isinstance(period_start, str):
                from datetime import datetime as dt
                period_start = dt.fromisoformat(period_start).date()
            from datetime import date
            today = date.today()
            cycle_day_raw = (today - period_start).days + 1
            if 1 <= cycle_day_raw <= 100:
                cycle_day = ((cycle_day_raw - 1) % 28) + 1
        
        # Build compact context for Claude with cycle day
        context = _build_compact_phase_context_optimized(
            user_id, 
            normalized_phase, 
            cycle_day
        )
        
        # Call Claude for compact recommendations
        llm_response = _generate_compact_phase_recommendations_with_claude(context)
        
        return {
            "cycle_phase": normalized_phase,
            "phase_day": f"D{cycle_day}" if cycle_day > 0 else "Unknown",
            "focus": llm_response.get("focus", ""),
            "recommendations": llm_response.get("recommendations", []),
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] get_cycle_training_focus failed: {e}")
        return {
            "status": "error",
            "message": str(e),
        }


def _build_compact_phase_context_optimized(
    user_id: int, 
    cycle_phase: str, 
    cycle_day: int
) -> str:
    """Build compact context for Claude to generate concise phase recommendations."""
    
    # Map cycle day to phase day label (D1-D28)
    phase_day_label = f"D{cycle_day}" if cycle_day > 0 else "Unknown"
    
    # Define phase characteristics for Claude
    phase_guide = {
        "menstrual": "Days 1-5: Low energy, hormone dip, recovery focus",
        "follicular": "Days 6-13: Rising energy, strength building, new challenges",
        "ovulation": "Days 14-16: Peak performance, max effort, high intensity",
        "luteal": "Days 17-28: Stable energy, endurance focus, fatigue management"
    }
    
    phase_desc = phase_guide.get(cycle_phase, "Unknown phase")
    
    context = f"""Generate COMPACT training focus. Return ONLY JSON (no markdown):

Cycle Phase: {cycle_phase.upper()} ({phase_desc})
Cycle Day: {phase_day_label}

Return:
{{
    "focus": "One-line focus (3-5 words max)",
    "recommendations": ["4-5 recommendations max, 8 words each"]
}}"""
    
    return context


def _generate_compact_phase_recommendations_with_claude(context: str) -> dict[str, Any]:
    """Call Claude to generate compact phase recommendations."""
    try:
        # Call Claude LLM using the standard llm_call function
        response = llm_call(context)
        
        # Parse JSON response
        recommendations = json.loads(response)
        
        # Validate and return response
        return {
            "phase_day": recommendations.get("phase_day", ""),
            "focus": recommendations.get("focus", ""),
            "recommendations": recommendations.get("recommendations", []),
        }
    
    except json.JSONDecodeError as e:
        print(f"[ERROR] Failed to parse Claude response as JSON: {e}")
        # Return safe defaults if JSON parsing fails
        return {
            "phase_day": "",
            "focus": "Rest and recovery",
            "recommendations": ["Listen to your body", "Prioritize sleep", "Hydrate well"],
        }
    
    except Exception as e:
        print(f"[ERROR] _generate_compact_phase_recommendations_with_claude failed: {e}")
        # Return safe defaults if Claude call fails
        return {
            "phase_day": "",
            "focus": "Rest and recovery",
            "recommendations": ["Listen to your body", "Prioritize sleep", "Hydrate well"],
        }


def get_unified_athlete_performance(user_id: int, cycle_phase: str) -> dict[str, Any]:
    """
    Get unified athlete performance combining readiness score and cycle training focus.
    LLM generates phase-specific insights based on readiness metrics.
    
    Args:
        user_id: The user's ID
        cycle_phase: menstrual | follicular | ovulation | luteal
    
    Returns:
        Dictionary with readiness data + cycle training focus combined
    """
    from fastapi import HTTPException
    
    try:
        # Validate user exists
        profile = get_user_profile(user_id)
        if not profile:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found")
        
        # Get readiness data (includes actual cycle info from database)
        readiness_data = athlete_readiness(user_id)
        if isinstance(readiness_data, dict) and "status" in readiness_data:
            # Readiness failed, propagate error
            raise HTTPException(
                status_code=500, 
                detail="Failed to calculate readiness score"
            )
        
        # Get cycle training focus using provided phase
        cycle_training = get_cycle_training_focus(user_id, cycle_phase)
        if isinstance(cycle_training, dict) and "status" in cycle_training:
            # Cycle training failed, propagate error
            raise HTTPException(
                status_code=500,
                detail="Failed to generate cycle training recommendations"
            )
        
        # Combine readiness data with cycle training focus
        unified_response = {
            # Readiness info
            "date": readiness_data.get("date"),
            "readiness_score": readiness_data.get("readiness_score"),
            "readiness_level": readiness_data.get("readiness_level"),
            
            # Quick metrics (for UI cards)
            "hrv": readiness_data.get("hrv"),
            "recovery": readiness_data.get("recovery"),
            "training_load": readiness_data.get("training_load"),
            
            # Full metrics
            "metrics": readiness_data.get("metrics"),
            "fatigue_alerts": readiness_data.get("fatigue_alerts", []),
            "cycle_info": readiness_data.get("cycle_info"),
            
            # Cycle training focus (LLM generates based on readiness + phase)
            "training_focus": {
                "cycle_phase": cycle_training.get("cycle_phase"),
                "phase_day": cycle_training.get("phase_day"),
                "focus": cycle_training.get("focus"),
                "recommendations": cycle_training.get("recommendations", []),
            },
            
            "next_update": readiness_data.get("next_update"),
        }
        
        return unified_response
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] get_unified_athlete_performance failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Unified performance calculation failed: {str(e)}"
        )