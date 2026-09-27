"""Service layer for Cycle & Fertility endpoint.

This module provides comprehensive cycle tracking, ovulation prediction,
and fertility window analysis with Claude AI integration.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional, Dict, List, Tuple

from ai.config import settings
from ai.models.cycle_models import (
    CycleOverviewResponse,
    CycleMetrics,
    FertileWindow,
    BBTAnalysis,
    CycleHistory,
)
from ai.services.cycle_engine_v1_service import _hormone_trends_from_mucus
from ai.utils.claude_llm import ClaudeLLM
from ai.utils.db import get_connection

# Configure logging
logger = logging.getLogger(__name__)

# Constants
CYCLE_PHASE_MAP = {
    "menstrual": ("menstrual", 1, 5),      # phase, start_day, end_day
    "follicular": ("follicular", 1, 13),
    "ovulatory": ("ovulatory", 13, 15),
    "luteal": ("luteal", 15, 28),
}

FERTILE_WINDOW_DAYS = 6  # 5 days before + day of ovulation
MIN_CYCLE_LENGTH = 21
MAX_CYCLE_LENGTH = 35
DEFAULT_CYCLE_LENGTH = 28

CYCLE_SYSTEM_PROMPT = """You are an expert fertility and cycle tracking AI assistant for a women's health app.

ANALYSIS REQUIREMENTS:
- Analyze menstrual cycle data (phase, ovulation prediction, fertility window)
- Consider BBT data if available (temperature patterns, coverline)
- Assess cycle regularity and predictability
- Provide evidence-based fertility recommendations
- Be sensitive to users trying to conceive or avoid pregnancy

RESPONSE FORMAT:
Return ONLY valid JSON:
{
    "cycle_assessment": "string - 2-3 sentence assessment of cycle health",
    "optimal_timing": "string - when is peak fertility",
    "phase_explanation": "string - what current phase means",
    "symptom_tracking": "string - what to track during this phase",
    "key_insights": ["array", "of", "key", "findings"],
    "recommendations": ["array", "of", "actionable", "advice"],
    "next_steps": "string - what to do next",
    "confidence_score": 85
}

CRITICAL: Return ONLY JSON, no markdown or additional text."""


def get_cycle_overview(user_id: int, mode: str = "standard", include_bbt: bool = False) -> CycleOverviewResponse:
    """
    Generate comprehensive cycle overview for a user.
    
    Args:
        user_id: User ID (must be positive integer)
        mode: Tracking mode - 'standard', 'tracking', or 'premium'
        include_bbt: Include BBT (Basal Body Temperature) analysis
        
    Returns:
        CycleOverviewResponse with current metrics, fertile window, and AI insights
        
    Raises:
        ValueError: If user not found or data invalid
    """
    try:
        logger.info(f"Generating cycle overview for user {user_id}, mode={mode}")
        
        # Validate user exists
        if not _user_exists(user_id):
            logger.warning(f"User {user_id} not found")
            raise ValueError(f"User {user_id} not found")
        
        # Fetch cycle data
        current_cycle = _fetch_current_cycle(user_id)
        if not current_cycle:
            logger.warning(f"No active cycle found for user {user_id}")
            raise ValueError(f"No active menstrual cycle found for user {user_id}")
        
        # Parse cycle data
        cycle_metrics = _build_cycle_metrics(current_cycle)
        
        # Calculate fertile window
        fertile_window = _calculate_fertile_window(cycle_metrics)
        
        # Get BBT analysis if requested
        bbt_analysis = None
        if include_bbt or mode in ["tracking", "premium"]:
            bbt_analysis = _fetch_bbt_analysis(user_id, current_cycle["id"])
            logger.debug(f"BBT analysis for user {user_id}: {bbt_analysis is not None}")
        
        # Get cycle history
        cycle_history = _fetch_cycle_history(user_id)
        
        # Fetch latest mucus consistency and build hormone trends
        mucus_consistency = _fetch_latest_mucus_consistency(current_cycle["id"])
        hormone_trends = _hormone_trends_from_mucus(mucus_consistency)
        
        # Build context for Claude
        context = _build_cycle_context(
            metrics=cycle_metrics,
            fertile_window=fertile_window,
            bbt_analysis=bbt_analysis,
            history=cycle_history,
            mode=mode
        )
        
        # Generate AI insights
        ai_insights = _generate_cycle_insights(context, mode)
        
        logger.info(f"Successfully generated cycle overview for user {user_id}")
        
        return CycleOverviewResponse(
            current_metrics=cycle_metrics,
            fertile_window=fertile_window,
            bbt_analysis=bbt_analysis,
            cycle_history=cycle_history,
            hormone_trends=hormone_trends,
            ai_insights=ai_insights
        )
    
    except Exception as exc:
        logger.error(f"Error generating cycle overview for user {user_id}: {exc}")
        raise


def _user_exists(user_id: int) -> bool:
    """Check if user exists in the profiles table."""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM profiles WHERE user_id = %s LIMIT 1", (user_id,))
            return cur.fetchone() is not None
    except Exception as exc:
        logger.error(f"Error checking if user exists: {exc}")
        return False


def _fetch_current_cycle(user_id: int) -> Optional[Dict[str, Any]]:
    """Fetch the current active menstrual cycle."""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    id, user_id, period_start_date, period_end_date,
                    current_cycle_day, cycle_length, period_length,
                    predicted_ovulation_day, confirmed_ovulation_day,
                    predicted_peak_day, fertile_start_day, fertile_end_day,
                    current_phase, prediction_source, is_confirmed,
                    is_completed, created_at, updated_at
                FROM menstrual_cycles
                WHERE user_id = %s
                AND is_completed = FALSE
                ORDER BY period_start_date DESC
                LIMIT 1
            """, (user_id,))
            
            row = cur.fetchone()
            return row if row else None
    
    except Exception as exc:
        logger.error(f"Database error fetching current cycle: {exc}")
        return None


def _fetch_bbt_analysis(user_id: int, cycle_id: int) -> Optional[BBTAnalysis]:
    """Fetch and analyze BBT data for the current cycle."""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    log_date, temperature, unit, phase,
                    coverline_value, ovulation_confirmed
                FROM bbt_logs
                WHERE user_id = %s
                AND cycle_id = %s
                ORDER BY log_date ASC
            """, (user_id, cycle_id))
            
            rows = cur.fetchall()
            if not rows:
                logger.debug(f"No BBT logs found for user {user_id}, cycle {cycle_id}")
                return None
            
            return _analyze_bbt_data(rows)
    
    except Exception as exc:
        logger.error(f"Error fetching BBT analysis: {exc}")
        return None


def _fetch_cycle_history(user_id: int, months: int = 6) -> CycleHistory:
    """Fetch cycle history for the past N months."""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            
            # Get completed cycles
            cur.execute("""
                SELECT 
                    cycle_length, period_length, is_completed
                FROM menstrual_cycles
                WHERE user_id = %s
                AND is_completed = TRUE
                AND period_start_date >= DATE_SUB(NOW(), INTERVAL %s MONTH)
                ORDER BY period_start_date DESC
                LIMIT 12
            """, (user_id, months))
            
            rows = cur.fetchall()
            
            if not rows:
                logger.debug(f"No cycle history found for user {user_id}")
                return CycleHistory()
            
            cycle_lengths = [row.get('cycle_length') for row in rows if row.get('cycle_length')]
            period_lengths = [row.get('period_length') for row in rows if row.get('period_length')]
            
            # Calculate regularity (std deviation of cycle lengths)
            avg_length = sum(cycle_lengths) / len(cycle_lengths) if cycle_lengths else DEFAULT_CYCLE_LENGTH
            regularity_score = _calculate_regularity_score(cycle_lengths)
            
            return CycleHistory(
                previous_cycles_count=len(rows),
                avg_cycle_length=int(avg_length),
                avg_period_length=int(sum(period_lengths) / len(period_lengths)) if period_lengths else 5,
                cycle_regularity_score=regularity_score
            )
    
    except Exception as exc:
        logger.error(f"Error fetching cycle history: {exc}")
        return CycleHistory()


def _fetch_latest_mucus_consistency(cycle_id: int) -> Optional[str]:
    """Fetch the most recent cervical mucus consistency for a given cycle."""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT consistency
                FROM cervical_mucus_logs
                WHERE cycle_id = %s
                ORDER BY log_date DESC
                LIMIT 1
            """, (cycle_id,))
            
            row = cur.fetchone()
            return row.get("consistency") if row else None
    
    except Exception as exc:
        logger.error(f"Error fetching latest mucus consistency: {exc}")
        return None


def _build_cycle_metrics(cycle_data: Dict[str, Any]) -> CycleMetrics:
    """Build CycleMetrics from database row."""
    
    # Calculate period_end_date if not provided
    period_end_date = cycle_data.get("period_end_date")
    if not period_end_date and cycle_data.get("period_start_date"):
        # If period_end_date is null, calculate it as period_start_date + period_length (or default 5 days)
        from datetime import datetime, timedelta
        try:
            start = cycle_data.get("period_start_date")
            if isinstance(start, str):
                start = datetime.fromisoformat(start).date()
            period_length = cycle_data.get("period_length") or 5  # Default 5-day period
            period_end_date = start + timedelta(days=period_length - 1)  # -1 because it's inclusive
        except Exception as e:
            logger.warning(f"Could not calculate period_end_date: {e}")
            period_end_date = None
    
    return CycleMetrics(
        current_cycle_day=cycle_data.get("current_cycle_day") or 0,
        cycle_length=cycle_data.get("cycle_length") or DEFAULT_CYCLE_LENGTH,
        current_phase=cycle_data.get("current_phase") or "unknown",
        period_start_date=str(cycle_data.get("period_start_date")) if cycle_data.get("period_start_date") else None,
        period_end_date=str(period_end_date) if period_end_date else None,
        predicted_ovulation_day=cycle_data.get("predicted_ovulation_day"),
        confirmed_ovulation_day=cycle_data.get("confirmed_ovulation_day"),
        is_confirmed=bool(cycle_data.get("is_confirmed"))
    )


def _calculate_fertile_window(metrics: CycleMetrics) -> FertileWindow:
    """Calculate fertile window based on cycle metrics."""
    
    # Standard fertility window is 5 days before ovulation + day of ovulation
    ovulation_day = metrics.confirmed_ovulation_day or metrics.predicted_ovulation_day
    
    if not ovulation_day:
        # Predict based on cycle length (typically day 14 for 28-day cycle)
        ovulation_day = (metrics.cycle_length // 2) + 1
    
    fertile_start = max(1, ovulation_day - 5)
    fertile_end = min(metrics.cycle_length, ovulation_day)
    
    # Calculate confidence based on whether ovulation is confirmed
    probability = 95.0 if metrics.is_confirmed else 75.0
    
    # Check if currently in fertile window
    is_fertile_now = fertile_start <= metrics.current_cycle_day <= fertile_end
    
    # Days until ovulation (can be negative if past ovulation)
    days_until = ovulation_day - metrics.current_cycle_day
    
    return FertileWindow(
        fertile_start_day=fertile_start,
        fertile_end_day=fertile_end,
        days_until_ovulation=days_until if days_until >= 0 else None,
        ovulation_probability=probability,
        is_fertile_now=is_fertile_now
    )


def _analyze_bbt_data(rows: List[Dict[str, Any]]) -> Optional[BBTAnalysis]:
    """Analyze BBT temperature data for patterns."""
    
    if not rows:
        return None
    
    try:
        temperatures = [row['temperature'] for row in rows if row.get('temperature')]
        phases = [row['phase'] for row in rows if row.get('phase')]
        
        # Split by phase
        follicular_temps = [row['temperature'] for row in rows if row.get('temperature') and row.get('phase') == "follicular"]
        luteal_temps = [row['temperature'] for row in rows if row.get('temperature') and row.get('phase') == "luteal"]
        
        # Calculate averages
        avg_follicular = sum(follicular_temps) / len(follicular_temps) if follicular_temps else None
        avg_luteal = sum(luteal_temps) / len(luteal_temps) if luteal_temps else None
        
        # Detect temperature shift (simple: compare last 3 days to first 3 days)
        temp_shift = False
        shift_date = None
        if len(temperatures) >= 6:
            first_avg = sum(temperatures[:3]) / 3
            last_avg = sum(temperatures[-3:]) / 3
            temp_shift = last_avg > first_avg + 0.3  # 0.3°C shift
            if temp_shift:
                shift_date = str(rows[-3]['log_date']) if rows[-3].get('log_date') else None
        
        return BBTAnalysis(
            temperature_entries=len(temperatures),
            avg_follicular_temp=round(avg_follicular, 2) if avg_follicular else None,
            avg_luteal_temp=round(avg_luteal, 2) if avg_luteal else None,
            temp_rise_detected=temp_shift,
            temp_rise_date=shift_date,
            coverline_value=rows[-1].get('coverline_value') if rows else None,
            prediction_confidence=90.0 if temp_shift else 60.0
        )
    
    except Exception as exc:
        logger.error(f"Error analyzing BBT data: {exc}")
        return None


def _calculate_regularity_score(cycle_lengths: List[int]) -> float:
    """Calculate cycle regularity score (0-100) based on variance."""
    
    if not cycle_lengths or len(cycle_lengths) < 2:
        return 50.0  # Unknown
    
    avg = sum(cycle_lengths) / len(cycle_lengths)
    variance = sum((x - avg) ** 2 for x in cycle_lengths) / len(cycle_lengths)
    std_dev = variance ** 0.5
    
    # Score: 100 = very regular (std dev ~1), 0 = very irregular (std dev ~10)
    score = max(0, min(100, 100 - (std_dev * 10)))
    return round(score, 1)


def _build_cycle_context(
    metrics: CycleMetrics,
    fertile_window: FertileWindow,
    bbt_analysis: Optional[BBTAnalysis],
    history: CycleHistory,
    mode: str
) -> str:
    """Build context string for Claude analysis."""
    
    parts = []
    
    # Current cycle info
    parts.append("CURRENT CYCLE METRICS:")
    parts.append(f"  Cycle Day: {metrics.current_cycle_day}/{metrics.cycle_length}")
    parts.append(f"  Current Phase: {metrics.current_phase}")
    parts.append(f"  Period Started: {metrics.period_start_date}")
    parts.append(f"  Predicted Ovulation: Day {metrics.predicted_ovulation_day}")
    if metrics.is_confirmed:
        parts.append(f"  ✓ Ovulation Confirmed: Day {metrics.confirmed_ovulation_day}")
    
    # Fertile window
    parts.append("\nFERTILE WINDOW:")
    parts.append(f"  Fertile Days: {fertile_window.fertile_start_day}-{fertile_window.fertile_end_day}")
    parts.append(f"  Currently Fertile: {fertile_window.is_fertile_now}")
    if fertile_window.days_until_ovulation is not None:
        parts.append(f"  Days Until Ovulation: {fertile_window.days_until_ovulation}")
    parts.append(f"  Ovulation Probability: {fertile_window.ovulation_probability}%")
    
    # BBT analysis
    if bbt_analysis:
        parts.append("\nBBT ANALYSIS:")
        parts.append(f"  Temperature Readings: {bbt_analysis.temperature_entries}")
        if bbt_analysis.avg_follicular_temp:
            parts.append(f"  Avg Follicular Temp: {bbt_analysis.avg_follicular_temp}°C")
        if bbt_analysis.avg_luteal_temp:
            parts.append(f"  Avg Luteal Temp: {bbt_analysis.avg_luteal_temp}°C")
        parts.append(f"  Temperature Shift: {bbt_analysis.temp_rise_detected}")
        parts.append(f"  BBT Confidence: {bbt_analysis.prediction_confidence}%")
    
    # History
    parts.append("\nCYCLE HISTORY:")
    parts.append(f"  Cycles Tracked: {history.previous_cycles_count}")
    if history.avg_cycle_length:
        parts.append(f"  Avg Cycle Length: {history.avg_cycle_length} days")
    parts.append(f"  Regularity Score: {history.cycle_regularity_score}%")
    
    return "\n".join(parts)


def _generate_cycle_insights(context: str, mode: str) -> dict:
    """Generate AI insights using Claude."""
    
    try:
        import json
        
        llm = ClaudeLLM()
        
        system_msg = CYCLE_SYSTEM_PROMPT
        if mode == "premium":
            system_msg += "\n\nPREMIUM MODE: Provide detailed medical-grade analysis with all possible insights."
        
        response = llm.chat(
            system=system_msg,
            messages=[{
                "role": "user",
                "content": f"Analyze this user's cycle and provide personalized insights:\n\n{context}"
            }]
        )
        
        # Extract text from response object
        response_text = response.content[0].text.strip()
        
        # Remove markdown code blocks if present
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        
        insights = json.loads(response_text)
        logger.info("Successfully generated cycle insights from Claude")
        return insights
    
    except Exception as exc:
        logger.error(f"Error generating cycle insights: {exc}")
        return {
            "cycle_assessment": "Unable to generate insights at this time",
            "optimal_timing": "",
            "phase_explanation": "",
            "recommendations": [],
            "confidence_score": 0
        }


# Legacy functions required by chat_service.py for backward compatibility
def fetch_backend_data(user_id: str) -> dict[str, Any]:
    """
    Fetch legacy temperature data from backend.
    
    This is a legacy function maintained for backward compatibility with chat_service.py.
    It attempts to fetch historical temperature data for context enrichment.
    
    Args:
        user_id: User ID as string
        
    Returns:
        Dictionary containing legacy temperature backend data or empty dict on failure
    """
    try:
        user_id_int = int(user_id)
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    log_date, temperature, unit, phase, coverline_value
                FROM bbt_logs
                WHERE user_id = %s
                ORDER BY log_date DESC
                LIMIT 30
            """, (user_id_int,))
            
            rows = cur.fetchall()
            if not rows:
                return {}
            
            # Format as legacy backend structure
            return {
                "count": len(rows),
                "recent_readings": [
                    {
                        "date": str(row[0]),
                        "temperature": row[1],
                        "unit": row[2],
                        "phase": row[3]
                    }
                    for row in rows[:10]  # Return last 10
                ]
            }
    
    except Exception as exc:
        logger.warning(f"Error fetching legacy backend data for user {user_id}: {exc}")
        return {}


def fetch_subscription(user_id: str) -> dict[str, Any]:
    """
    Fetch user subscription/plan information.
    
    This is a legacy function maintained for backward compatibility with chat_service.py.
    Returns subscription tier for usage limiting and feature access control.
    
    Args:
        user_id: User ID as string
        
    Returns:
        Dictionary with plan/subscription info, defaults to free tier
    """
    try:
        # In a full implementation, this would query a subscriptions table
        # For now, return default free tier
        return {
            "plan": "free",
            "subscription": "free",
            "tier": "free",
            "status": "active"
        }
    
    except Exception as exc:
        logger.warning(f"Error fetching subscription for user {user_id}: {exc}")
        return {"plan": "free"}
