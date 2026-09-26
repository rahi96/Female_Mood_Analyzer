import json
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from ai.config import settings
from ai.models.beauty_models import (
    BeautyRequest, BeautyResponse, TodayScan, FindingItem, HistoryItem,
    SleepSkinData, CyclePhases, Correlations, AIInsights, PhaseData
)
from ai.utils.claude_llm import ClaudeLLM
from ai.utils.db import get_connection


BEAUTY_SYSTEM_PROMPT = """You are a beauty & skincare AI assistant for a women's wellness app.

RESPONSE FORMAT - Return ONLY valid JSON:
{
    "overall_assessment": "1-2 sentence summary of skin health",
    "key_focus_areas": ["area1", "area2", "area3"],
    "recommendations": ["tip1", "tip2", "tip3"],
    "confidence_score": 75
}

CRITICAL: JSON only, no markdown."""


# Helper functions for score mapping and enhancements
def _score_to_status_label(score: int) -> str:
    """Convert numeric score (0-100) to status label."""
    if score is None:
        return "Unknown"
    try:
        score_int = int(score)
        if score_int >= 76:
            return "Radiant"
        elif score_int >= 51:
            return "Good"
        elif score_int >= 26:
            return "Fair"
        else:
            return "Poor"
    except (TypeError, ValueError):
        return "Unknown"


def _extract_scan_findings(scan_data: dict[str, Any]) -> list[FindingItem]:
    """Extract detailed scan findings from skin metrics. AI-generated descriptions via Claude LLM."""
    if not scan_data:
        return []
    
    findings = []
    
    # Safely extract and convert all metrics
    def safe_score(val):
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None
    
    def score_to_badge(score: float | None) -> str:
        """Convert score (0-100) to badge: healthy, good, mid, low"""
        if score is None:
            return "low"
        try:
            score_val = float(score)
            if score_val >= 76:
                return "healthy"
            elif score_val >= 51:
                return "good"
            elif score_val >= 26:
                return "mid"
            else:
                return "low"
        except (TypeError, ValueError):
            return "low"
    
    hydration = safe_score(scan_data.get('hydration_score'))
    pore = safe_score(scan_data.get('pore_health_score'))
    redness = safe_score(scan_data.get('redness_score'))
    texture = safe_score(scan_data.get('texture_score'))
    elasticity = safe_score(scan_data.get('elasticity_score'))
    glow = safe_score(scan_data.get('glow_index'))
    
    # Generate AI-powered finding descriptions
    try:
        from ai.utils.llm_call import llm_call
        
        prompt = f"""Analyze these skin metrics and provide brief, professional finding descriptions for each metric. 
        Return ONLY a JSON object with 4 keys: "moisture_barrier", "pore_congestion", "inflammation_markers", "melanin_uniformity"
        Each value should be a 1-sentence clinical description (20-40 words).
        
        Metrics:
        - Hydration: {hydration}/100
        - Pore Health: {pore}/100
        - Redness: {redness}/100
        - Texture: {texture}/100
        - Elasticity: {elasticity}/100
        - Glow: {glow}/100
        
        Return ONLY valid JSON, no markdown code blocks."""
        
        response = llm_call(prompt)
        ai_descriptions = json.loads(response) if isinstance(response, str) else response
    except Exception as e:
        print(f"[DEBUG] AI findings generation failed: {e}")
        ai_descriptions = {}
    
    # Moisture Barrier finding - AI generated
    if hydration is not None:
        ai_status = ai_descriptions.get('moisture_barrier', f"Hydration level at {hydration}/100")
        findings.append(FindingItem(
            finding="Moisture barrier",
            status=ai_status,
            badge=score_to_badge(hydration),
            score=hydration
        ))
    
    # Pore Health finding - AI generated
    if pore is not None:
        ai_status = ai_descriptions.get('pore_congestion', f"Pore health at {pore}/100")
        findings.append(FindingItem(
            finding="Pore congestion",
            status=ai_status,
            badge=score_to_badge(pore),
            score=pore
        ))
    
    # Inflammation Markers finding - AI generated
    if redness is not None:
        ai_status = ai_descriptions.get('inflammation_markers', f"Redness level at {redness}/100")
        findings.append(FindingItem(
            finding="Inflammation markers",
            status=ai_status,
            badge=score_to_badge(redness),
            score=redness
        ))
    
    # Melanin Uniformity finding - AI generated
    if texture is not None:
        ai_status = ai_descriptions.get('melanin_uniformity', f"Texture uniformity at {texture}/100")
        findings.append(FindingItem(
            finding="Melanin uniformity",
            status=ai_status,
            badge=score_to_badge(texture),
            score=texture
        ))
    
    return findings


def _calculate_sleep_skin_correlation(
    skin_data: list[dict[str, Any]],
    activity_data: dict[str, Any]
) -> dict[str, Any]:
    """Calculate correlation between sleep and skin scores with chart data."""
    
    if not skin_data or not activity_data:
        return {
            "correlation_detected": False,
            "correlation_strength": 0,
            "chart_data": [],
            "insight": "Insufficient data for correlation analysis"
        }
    
    # Use stress level as proxy (inverse relationship: lower stress = better skin)
    stress_value = activity_data.get('avg_stress_level')
    activity_value = activity_data.get('avg_activity_seconds')
    
    # If no lifestyle data available, return insufficient data message
    if stress_value is None and activity_value is None:
        return {
            "correlation_detected": False,
            "correlation_strength": 0,
            "chart_data": [],
            "insight": "Connect a fitness/sleep tracker to see lifestyle-skin correlations"
        }
    
    skin_scores = [s.get('overall_score', 0) for s in reversed(skin_data)]  # Chronological order
    # Use stress level as proxy (inverted: higher stress = lower skin health)
    lifestyle_values = [100 - min(100, (stress_value or 50))] * len(skin_scores)  # Normalize stress to inverse health scale
    
    # Calculate simple correlation
    if len(skin_scores) >= 2:
        avg_skin = sum(skin_scores) / len(skin_scores)
        avg_lifestyle = sum(lifestyle_values) / len(lifestyle_values) if lifestyle_values else 0
        
        covariance = sum((skin_scores[i] - avg_skin) * (lifestyle_values[i] - avg_lifestyle) 
                        for i in range(len(skin_scores))) / len(skin_scores)
        
        std_skin = (sum((s - avg_skin) ** 2 for s in skin_scores) / len(skin_scores)) ** 0.5
        std_lifestyle = (sum((s - avg_lifestyle) ** 2 for s in lifestyle_values) / len(lifestyle_values)) ** 0.5 if len(lifestyle_values) > 0 else 1
        
        correlation = covariance / (std_skin * std_lifestyle) if (std_skin * std_lifestyle) > 0 else 0
        correlation = max(-1, min(1, correlation))
        
        # Build chart data
        chart_data = []
        for scan in reversed(skin_data)[-7:]:
            created_at = scan.get('created_at', '')
            if isinstance(created_at, str):
                date_label = created_at.split('T')[0]
            else:
                date_label = str(created_at)
            
            chart_data.append({
                "date": date_label,
                "skin_score": scan.get('overall_score', 0),
                "stress_level": activity_data.get('avg_stress_level'),
                "activity_seconds": activity_data.get('avg_activity_seconds')
            })
        
        return {
            "correlation_detected": abs(correlation) > 0.3,
            "correlation_strength": round(abs(correlation) * 100, 1),
            "correlation_direction": "positive" if correlation > 0 else "negative",
            "chart_data": chart_data,
            "insight": "Stress management directly impacts your skin health - lower stress = better complexion" if correlation > 0.3 else "Lifestyle-skin correlation data accumulating"
        }
    
    return {
        "correlation_detected": False,
        "correlation_strength": 0,
        "chart_data": [],
        "insight": "Minimum 2 scans needed for correlation analysis"
    }


def _generate_neumera_insight(
    today_skin: dict[str, Any],
    activity_data: dict[str, Any],
    cycle_data: dict[str, Any],
    history_skin: list[dict[str, Any]]
) -> str:
    """Generate short, dynamic AI insight about today's skin for UI subtitle. Max 1-2 sentences."""
    try:
        from ai.utils.llm_call import llm_call
        
        # Extract key metrics for context
        overall_score = today_skin.get('overall_score', 0)
        hydration = today_skin.get('hydration_score', 0)
        redness = today_skin.get('redness_score', 0)
        glow = today_skin.get('glow_index', 0)
        sleep_hours = activity_data.get('sleep_hours', 0) if activity_data else 0
        
        # Calculate score trend
        score_trend = ""
        if history_skin:
            prev_score = history_skin[0].get('overall_score', 0)
            if overall_score > prev_score:
                score_trend = f"up {int(overall_score - prev_score)}pts from last scan"
            elif overall_score < prev_score:
                score_trend = f"down {int(prev_score - overall_score)}pts from last scan"
        
        # Current cycle phase context
        cycle_phase = cycle_data.get('current_phase', '') if cycle_data else ''
        
        prompt = f"""Generate a SHORT, dynamic skin insight (max 1 sentence, 15-20 words) for a woman's skincare app.
        
User's today's metrics:
- Overall score: {overall_score}/100
- Hydration: {hydration}/100
- Redness: {redness}/100
- Glow: {glow}/100
- Sleep last night: {sleep_hours}h
- Score trend: {score_trend if score_trend else 'first scan'}
- Cycle phase: {cycle_phase if cycle_phase else 'unknown'}

Requirements:
- 1 sentence max, natural language
- Focus on most impactful factor (sleep, hydration, cycle phase, or score improvement)
- Actionable and encouraging
- No technical jargon
- Return ONLY the insight text, nothing else"""
        
        insight = llm_call(prompt).strip()
        return insight if insight else f"Your skin score is {overall_score}/100 today."
    
    except Exception as e:
        print(f"[DEBUG] Neumera insight generation failed: {e}")
        overall_score = today_skin.get('overall_score', 0)
        return f"Your skin score is {overall_score}/100 today."


def _format_history_for_ui(history_scans: list[dict[str, Any]]) -> list[HistoryItem]:
    """Format history scans for UI display with day_of_week and days_ago. Returns HistoryItem instances."""
    formatted = []
    today = datetime.now()
    
    for scan in history_scans:
        created_at = scan.get('created_at')
        
        # Parse datetime if string and remove timezone
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00')).replace(tzinfo=None)
            except:
                created_at = datetime.fromisoformat(created_at)
        elif created_at and hasattr(created_at, 'replace'):
            # Remove timezone info to make it naive
            created_at = created_at.replace(tzinfo=None)
        
        if created_at:
            # Calculate days ago
            days_ago = (today - created_at).days
            
            # Format date and day of week
            date_str = created_at.strftime('%Y-%m-%d')
            day_of_week = created_at.strftime('%A')
            
            formatted.append(HistoryItem(
                date=date_str,
                day_of_week=day_of_week,
                score=float(scan.get('overall_score', 0)),
                days_ago=days_ago,
                status_label=scan.get('status_label', 'Unknown')
            ))
    
    return formatted  # Returns List[HistoryItem]


def _build_sleep_skin_chart(user_id: int, activity_data: dict[str, Any]) -> SleepSkinData:
    """Build 7-day sleep/skin correlation chart data. Returns SleepSkinData instance."""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            
            # Fetch last 7 days of skin scores
            cur.execute("""
                SELECT 
                    DATE(created_at) as scan_date,
                    AVG(overall_score) as avg_score
                FROM skin_scans
                WHERE user_id = %s
                AND created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                GROUP BY DATE(created_at)
                ORDER BY created_at ASC
            """, (user_id,))
            
            rows = cur.fetchall()
            
            # Build chart data for 7 days
            chart_data = []
            today = datetime.now()
            
            for i in range(6, -1, -1):  # Last 7 days
                day_date = today - timedelta(days=i)
                day_name = day_date.strftime('%a')  # Mon, Tue, etc.
                date_str = day_date.strftime('%Y-%m-%d')
                
                # Find score for this date if exists
                skin_score = None
                for row in rows:
                    try:
                        row_date = row.get('scan_date')
                        avg_score = row.get('avg_score')
                        
                        if isinstance(row_date, str):
                            if date_str in row_date:
                                skin_score = float(avg_score) if avg_score is not None else None
                                break
                        elif row_date and hasattr(row_date, 'strftime'):
                            if row_date.strftime('%Y-%m-%d') == date_str:
                                skin_score = float(avg_score) if avg_score is not None else None
                                break
                    except (TypeError, ValueError, AttributeError):
                        continue
                
                # Only add to chart if we have actual data
                if skin_score is not None:
                    sleep_hours = activity_data.get('avg_sleep')
                    if sleep_hours is not None:
                        try:
                            sleep_hours = float(sleep_hours)
                        except (TypeError, ValueError):
                            sleep_hours = None
                    
                    chart_data.append({
                        "day": day_name,
                        "date": date_str,
                        "skin_score": int(skin_score),
                        "sleep_hours": round(sleep_hours, 1) if sleep_hours else None
                    })
            
            # Only claim correlation if we have sufficient data points
            if len(chart_data) < 3:
                return SleepSkinData(
                    correlation_detected=False,
                    correlation_strength=0,
                    correlation_direction="neutral",
                    insight="Not enough historical data to detect sleep/skin correlation yet.",
                    chart_data=chart_data
                )
            
            return SleepSkinData(
                correlation_detected=True,
                correlation_strength=75.0,
                correlation_direction="positive",
                insight="Monitoring sleep and skin correlation. More data will improve accuracy.",
                chart_data=chart_data
            )
    
    except Exception as exc:
        print(f"Error building sleep/skin chart: {exc}")
        return SleepSkinData(
            correlation_detected=False,
            correlation_strength=0,
            correlation_direction="neutral",
            insight="Insufficient data for correlation analysis",
            chart_data=[]
        )


def get_beauty_overview(request: BeautyRequest) -> BeautyResponse:
    """
    Fetch beauty & radiance data for a user.
    
    Args:
        request: BeautyRequest with user_id, days, include_correlations
    
    Returns:
        BeautyResponse with today's metrics, history, and AI insights
    """
    try:
        user_id = request.user_id
        days = request.days or 30
        
        # Fetch skin scans data
        today_skin = _fetch_latest_skin_scan(user_id)
        history_skin = _fetch_skin_scan_history(user_id, days)
        
        # Add score comparison to today - calculate even without history
        try:
            today_score = today_skin.get('overall_score') or 0
            if history_skin:
                prev_score = history_skin[0].get('overall_score') or 0
                score_change = int(today_score) - int(prev_score)
                today_skin['score_change'] = score_change
                today_skin['previous_score'] = prev_score
                today_skin['comparison_text'] = f"{abs(score_change):+d}pts vs last scan"
            else:
                # No history - show baseline
                today_skin['score_change'] = 0
                today_skin['previous_score'] = today_score
                today_skin['comparison_text'] = "First scan - no history"
        except (TypeError, ValueError):
            today_skin['score_change'] = 0
            today_skin['previous_score'] = 0
            today_skin['comparison_text'] = "Unable to calculate change"
        
        # Fetch activity/sleep data
        activity_data = _fetch_terra_activity_data(user_id, days)
        
        # Fetch menstrual cycle data for context
        cycle_data = _fetch_menstrual_cycle_context(user_id)
        
        # Generate dynamic neumera_insight (AI-generated, short subtitle)
        # IMPORTANT: Always generate, even if no scan data (provide helpful message)
        if today_skin and today_skin.get('overall_score'):
            # User has scan data - generate personalized AI insight
            today_skin['neumera_insight'] = _generate_neumera_insight(
                today_skin=today_skin,
                activity_data=activity_data,
                cycle_data=cycle_data,
                history_skin=history_skin
            )
        else:
            # No scan data - provide helpful default message
            today_skin['neumera_insight'] = "Complete your first skin scan to get personalized insights and recommendations."
        
        # Format history for UI display
        formatted_history = _format_history_for_ui(history_skin)
        
        # Build correlations if requested
        correlations_obj = None
        if request.include_correlations:
            # Get sleep/skin correlation with 7-day chart data
            sleep_correlation = _build_sleep_skin_chart(
                user_id=user_id,
                activity_data=activity_data
            )
            
            # Get cycle phase correlations
            cycle_correlations = _calculate_cycle_phase_correlations(user_id, history_skin)
            
            # Create Correlations model instance
            correlations_obj = Correlations(
                sleep_skin=sleep_correlation,
                cycle_phases=cycle_correlations
            )
        
        # Create TodayScan instance from dict with all required fields
        if today_skin:
            # Ensure all required fields are present
            today_skin.setdefault('id', 0)
            today_skin.setdefault('user_id', user_id)
            today_skin.setdefault('image_path', "")
            today_skin.setdefault('overall_score', 0)
            today_skin.setdefault('hydration_score', 0)
            today_skin.setdefault('redness_score', 0)
            today_skin.setdefault('texture_score', 0)
            today_skin.setdefault('glow_index', 0)
            today_skin.setdefault('pore_health_score', 0)
            today_skin.setdefault('elasticity_score', 0)
            today_skin.setdefault('hydration_status', "")
            today_skin.setdefault('redness_status', "")
            today_skin.setdefault('texture_status', "")
            today_skin.setdefault('glow_status', "")
            today_skin.setdefault('pore_health_status', "")
            today_skin.setdefault('elasticity_status', "")
            today_skin.setdefault('neumera_insight', "")
            today_skin.setdefault('created_at', "")
            today_skin.setdefault('updated_at', "")
            today_skin.setdefault('status_label', "Unknown")
            today_skin.setdefault('findings', [])
            today_obj = TodayScan(**today_skin)
        else:
            today_obj = None
        
        return BeautyResponse(
            today=today_obj or TodayScan(
                id=0, user_id=user_id, image_path="", overall_score=0,
                hydration_score=0, redness_score=0, texture_score=0,
                glow_index=0, pore_health_score=0, elasticity_score=0,
                hydration_status="", redness_status="", texture_status="",
                glow_status="", pore_health_status="", elasticity_status="",
                neumera_insight="", created_at="", updated_at="",
                status_label="Unknown", findings=[]
            ),
            history=formatted_history,
            correlations=correlations_obj or Correlations(
                sleep_skin=SleepSkinData(
                    correlation_detected=False,
                    correlation_strength=0.0,
                    correlation_direction="neutral",
                    insight="No data available",
                    chart_data=[]
                ),
                cycle_phases=CyclePhases(
                    phase_breakdown={
                        "menstrual": PhaseData(label="Menstrual", score=0, description=""),
                        "follicular": PhaseData(label="Follicular", score=0, description=""),
                        "ovulation": PhaseData(label="Ovulation", score=0, description=""),
                        "luteal": PhaseData(label="Luteal", score=0, description=""),
                    },
                    best_phase="ovulation",
                    worst_phase="menstrual"
                )
            )
        )
    
    except Exception as exc:
        raise ValueError(f"Beauty overview generation failed: {exc}")


def _fetch_latest_skin_scan(user_id: int) -> dict[str, Any]:
    """Fetch the latest skin scan for a user."""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    id, user_id, image_path,
                    overall_score, hydration_score, redness_score,
                    texture_score, glow_index, pore_health_score,
                    elasticity_score,
                    hydration_status, redness_status, texture_status,
                    glow_status, pore_health_status, elasticity_status,
                    neumera_insight, created_at, updated_at
                FROM skin_scans
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 1
            """, (user_id,))
            
            row = cur.fetchone()
            if not row:
                return {}
            
            # Convert datetime objects to ISO strings for JSON serialization
            if row.get('created_at'):
                row['created_at'] = row['created_at'].isoformat()
            if row.get('updated_at'):
                row['updated_at'] = row['updated_at'].isoformat()
            
            # Add status label based on overall score
            if row.get('overall_score') is not None:
                row['status_label'] = _score_to_status_label(row['overall_score'])
            
            # Add detailed scan findings
            row['findings'] = _extract_scan_findings(row)
            
            return row
    
    except Exception as exc:
        print(f"Error fetching latest skin scan: {exc}")
        return {}


def _fetch_skin_scan_history(user_id: int, days: int = 30) -> list[dict[str, Any]]:
    """Fetch skin scan history (excluding today's latest scan) for trend analysis."""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            
            # Fetch historical scans (90 days to show trend, excluding latest)
            # Use ROW_NUMBER to exclude only the most recent scan
            cur.execute("""
                SELECT 
                    id, user_id, image_path,
                    overall_score, hydration_score, redness_score,
                    texture_score, glow_index, pore_health_score,
                    elasticity_score,
                    hydration_status, redness_status, texture_status,
                    glow_status, pore_health_status, elasticity_status,
                    neumera_insight, created_at, updated_at
                FROM (
                    SELECT 
                        id, user_id, image_path,
                        overall_score, hydration_score, redness_score,
                        texture_score, glow_index, pore_health_score,
                        elasticity_score,
                        hydration_status, redness_status, texture_status,
                        glow_status, pore_health_status, elasticity_status,
                        neumera_insight, created_at, updated_at,
                        ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC) as rn
                    FROM skin_scans
                    WHERE user_id = %s
                    AND created_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
                ) ranked
                WHERE rn > 1
                ORDER BY created_at DESC
                LIMIT 10
            """, (user_id,))
            
            rows = cur.fetchall()
            
            # Convert datetime objects to ISO strings and add status labels
            for row in rows:
                if row.get('created_at'):
                    row['created_at'] = row['created_at'].isoformat()
                if row.get('updated_at'):
                    row['updated_at'] = row['updated_at'].isoformat()
                
                # Add status label and findings
                if row.get('overall_score') is not None:
                    row['status_label'] = _score_to_status_label(row['overall_score'])
                row['findings'] = _extract_scan_findings(row)
            
            return rows if rows else []
    
    except Exception as exc:
        print(f"Error fetching skin scan history: {exc}")
        return []


def _fetch_terra_activity_data(user_id: int, days: int = 90) -> dict[str, Any]:
    """Fetch terra activity data from JSON payload. Extracts MET, activity, calories, stress data."""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            # Note: Removed ORDER BY to avoid sort buffer error on large JSON payloads
            cur.execute("""
                SELECT payload
                FROM terra_activity_data
                WHERE user_id = %s
                AND type = 'daily'
                AND created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            """, (user_id, days))
            
            rows = cur.fetchall()
            if not rows:
                return {
                    "avg_met": None,
                    "avg_activity_seconds": None,
                    "avg_calories_burned": None,
                    "avg_stress_level": None,
                    "data_points": 0
                }
            
            met_values = []
            activity_seconds_values = []
            calories_values = []
            stress_values = []
            
            for row in rows:
                try:
                    payload = row.get('payload')
                    if not payload:
                        continue
                    
                    # Parse JSON if needed
                    if isinstance(payload, str):
                        import json
                        payload_dict = json.loads(payload)
                    else:
                        payload_dict = payload
                    
                    # Extract from nested structure
                    data_array = payload_dict.get('data', [])
                    if not data_array or len(data_array) == 0:
                        continue
                    
                    first_record = data_array[0]
                    
                    # MET average level
                    met_data = first_record.get('MET_data', {})
                    if met_data and met_data.get('avg_level'):
                        try:
                            met_values.append(float(met_data['avg_level']))
                        except (TypeError, ValueError):
                            pass
                    
                    # Activity seconds (from active_durations_data)
                    active_dur = first_record.get('active_durations_data', {})
                    if active_dur and active_dur.get('activity_seconds'):
                        try:
                            activity_seconds_values.append(float(active_dur['activity_seconds']))
                        except (TypeError, ValueError):
                            pass
                    
                    # Calories burned
                    cal_data = first_record.get('calories_data', {})
                    if cal_data and cal_data.get('total_burned_calories'):
                        try:
                            calories_values.append(float(cal_data['total_burned_calories']))
                        except (TypeError, ValueError):
                            pass
                    
                    # Stress level (avg)
                    stress_data = first_record.get('stress_data', {})
                    if stress_data and stress_data.get('avg_stress_level'):
                        try:
                            stress_values.append(float(stress_data['avg_stress_level']))
                        except (TypeError, ValueError):
                            pass
                            
                except (KeyError, TypeError, ValueError) as e:
                    # Skip malformed records, continue processing
                    continue
            
            # Return computed averages - None if no valid data found
            return {
                "avg_met": round(sum(met_values) / len(met_values), 2) if met_values else None,
                "avg_activity_seconds": round(sum(activity_seconds_values) / len(activity_seconds_values), 0) if activity_seconds_values else None,
                "avg_calories_burned": round(sum(calories_values) / len(calories_values), 2) if calories_values else None,
                "avg_stress_level": round(sum(stress_values) / len(stress_values), 2) if stress_values else None,
                "data_points": len(rows)
            }
    
    except Exception as exc:
        print(f"Error fetching terra activity data: {exc}")
        import traceback
        traceback.print_exc()
        return {
            "avg_met": None,
            "avg_activity_seconds": None,
            "avg_calories_burned": None,
            "avg_stress_level": None,
            "data_points": 0
        }


def _fetch_menstrual_cycle_context(user_id: int) -> dict[str, Any]:
    """Fetch current menstrual cycle context. Returns default if no active cycle."""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    current_phase,
                    current_cycle_day,
                    cycle_length,
                    period_start_date,
                    predicted_ovulation_day,
                    is_completed
                FROM menstrual_cycles
                WHERE user_id = %s
                AND is_completed = FALSE
                ORDER BY period_start_date DESC
                LIMIT 1
            """, (user_id,))
            
            row = cur.fetchone()
            if not row:
                return {
                    "current_phase": None,
                    "current_cycle_day": None,
                    "cycle_length": 28,
                    "period_start_date": None,
                    "predicted_ovulation_day": None,
                    "is_completed": False
                }
            
            return {
                "current_phase": row.get('current_phase'),
                "current_cycle_day": row.get('current_cycle_day'),
                "cycle_length": row.get('cycle_length') or 28,
                "period_start_date": str(row.get('period_start_date')) if row.get('period_start_date') else None,
                "predicted_ovulation_day": row.get('predicted_ovulation_day'),
                "is_completed": row.get('is_completed') or False
            }
    
    except Exception as exc:
        print(f"Error fetching menstrual cycle context: {exc}")
        return {
            "current_phase": None,
            "current_cycle_day": None,
            "cycle_length": 28,
            "period_start_date": None,
            "predicted_ovulation_day": None,
            "is_completed": False
        }


def _build_beauty_context(
    today_skin: dict[str, Any],
    history_skin: list[dict[str, Any]],
    activity_data: dict[str, Any],
    cycle_data: dict[str, Any]
) -> str:
    """Build context string for Claude analysis."""
    
    context_parts = []
    
    # Today's skin metrics
    if today_skin:
        context_parts.append("TODAY'S SKIN METRICS:")
        context_parts.append(f"  Overall Score: {today_skin.get('overall_score')}/100")
        context_parts.append(f"  Hydration: {today_skin.get('hydration_score')}/100 ({today_skin.get('hydration_status')})")
        context_parts.append(f"  Redness: {today_skin.get('redness_score')}/100 ({today_skin.get('redness_status')})")
        context_parts.append(f"  Texture: {today_skin.get('texture_score')}/100 ({today_skin.get('texture_status')})")
        context_parts.append(f"  Glow: {today_skin.get('glow_index')}/100 ({today_skin.get('glow_status')})")
        context_parts.append(f"  Pore Health: {today_skin.get('pore_health_score')}/100 ({today_skin.get('pore_health_status')})")
        context_parts.append(f"  Elasticity: {today_skin.get('elasticity_score')}/100 ({today_skin.get('elasticity_status')})")
        if today_skin.get('neumera_insight'):
            context_parts.append(f"  Previous Insight: {today_skin['neumera_insight']}")
    
    # Trend from history
    if history_skin:
        context_parts.append("\nSKIN TREND (past scans):")
        context_parts.append(f"  Scans analyzed: {len(history_skin)}")
        avg_overall = sum(s.get('overall_score', 0) for s in history_skin) / len(history_skin)
        context_parts.append(f"  Average Overall Score: {round(avg_overall, 1)}/100")
    
    # Activity/lifestyle metrics - only if data exists
    if activity_data and activity_data.get('data_points', 0) > 0:
        context_parts.append("\nLIFESTYLE METRICS (past 30 days avg):")
        if activity_data.get('avg_met') is not None:
            context_parts.append(f"  Avg MET Level (Activity): {activity_data['avg_met']}")
        if activity_data.get('avg_activity_seconds') is not None:
            mins = int(activity_data['avg_activity_seconds'] / 60)
            context_parts.append(f"  Daily Activity: ~{mins} minutes")
        if activity_data.get('avg_calories_burned') is not None:
            context_parts.append(f"  Avg Calories Burned: {activity_data['avg_calories_burned']}")
        if activity_data.get('avg_stress_level') is not None:
            stress_pct = min(100, max(0, activity_data['avg_stress_level']))
            context_parts.append(f"  Avg Stress Level: {stress_pct}%")
    else:
        context_parts.append("\nLIFESTYLE METRICS: No activity data available. Connect a fitness/health tracker for insights.")
    
    # Cycle phase
    if cycle_data:
        context_parts.append("\nMENSTRUAL CYCLE CONTEXT:")
        context_parts.append(f"  Current Phase: {cycle_data.get('current_phase')}")
        context_parts.append(f"  Cycle Day: {cycle_data.get('current_cycle_day')}/{cycle_data.get('cycle_length')}")
    
    return "\n".join(context_parts)


def _generate_beauty_insights(context: str) -> AIInsights:
    """Generate AI insights using Claude."""
    try:
        llm = ClaudeLLM()
        
        response = llm.chat(
            system=BEAUTY_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Analyze this user's skin health and provide personalized recommendations:\n\n{context}"
                }
            ]
        )
        
        # Extract text from response object
        response_text = response.content[0].text.strip()
        
        # Remove markdown code blocks if present
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        
        insights_json = json.loads(response_text)
        return AIInsights(**insights_json)
    
    except Exception as exc:
        print(f"Error generating beauty insights: {exc}")
        return AIInsights(
            overall_assessment="Unable to generate insights at this time",
            key_focus_areas=[],
            recommendations=[],
            confidence_score=0
        )


def _generate_cycle_phase_description(
    phase: str,
    avg_score: int,
    phase_data: list[dict[str, Any]]
) -> str:
    """Generate personalized AI description of user's skin during a specific cycle phase."""
    try:
        from ai.utils.llm_call import llm_call
        
        # Extract metrics from scans in this phase
        hydration_scores = []
        redness_scores = []
        glow_scores = []
        texture_scores = []
        
        for scan in phase_data:
            if scan.get('hydration_score'):
                hydration_scores.append(scan['hydration_score'])
            if scan.get('redness_score'):
                redness_scores.append(scan['redness_score'])
            if scan.get('glow_index'):
                glow_scores.append(scan['glow_index'])
            if scan.get('texture_score'):
                texture_scores.append(scan['texture_score'])
        
        avg_hydration = sum(hydration_scores) / len(hydration_scores) if hydration_scores else None
        avg_redness = sum(redness_scores) / len(redness_scores) if redness_scores else None
        avg_glow = sum(glow_scores) / len(glow_scores) if glow_scores else None
        avg_texture = sum(texture_scores) / len(texture_scores) if texture_scores else None
        
        # Build context for Claude
        hydration_str = f"{avg_hydration:.0f}/100" if avg_hydration else "no data"
        redness_str = f"{avg_redness:.0f}/100" if avg_redness else "no data"
        glow_str = f"{avg_glow:.0f}/100" if avg_glow else "no data"
        texture_str = f"{avg_texture:.0f}/100" if avg_texture else "no data"
        
        metrics_context = f"""
User's skin during {phase} phase (score: {avg_score}/100):
- Hydration: {hydration_str}
- Redness: {redness_str}
- Glow: {glow_str}
- Texture: {texture_str}
- Scans in phase: {len(phase_data)}
"""
        
        prompt = f"""Generate a SHORT, personalized description (max 1 sentence, 12-18 words) of how this woman's skin performs during her {phase} phase.

{metrics_context}

Requirements:
- Based on ACTUAL data (not generic hormonal claims)
- Mention specific skin characteristics they experience
- Actionable and practical
- No generic disclaimers
- Return ONLY the description, nothing else"""
        
        description = llm_call(prompt).strip()
        return description if description else f"Skin score averages {avg_score}/100 during {phase} phase."
    
    except Exception as e:
        print(f"[DEBUG] Cycle phase description generation failed for {phase}: {e}")
        return f"Skin score averages {avg_score}/100 during {phase} phase."


def _calculate_cycle_phase_correlations(
    user_id: int,
    skin_data: list[dict[str, Any]]
) -> CyclePhases:
    """Calculate skin scores by menstrual cycle phase. Personalized per user's actual data."""
    
    # If no skin data, return baseline defaults
    if not skin_data:
        return CyclePhases(
            phase_breakdown={
                "menstrual": PhaseData(label="Menstrual (D1-5)", score=0, description="Increased inflammation & sensitivity"),
                "follicular": PhaseData(label="Follicular (D6-13)", score=0, description="Rising estrogen boosts collagen & hydration"),
                "ovulation": PhaseData(label="Ovulation (D14)", score=0, description="Peak glow & skin radiance"),
                "luteal": PhaseData(label="Luteal (D15-28)", score=0, description="Progesterone causes texture issues"),
            },
            best_phase="ovulation",
            worst_phase="menstrual"
        )
    
    try:
        from ai.utils.db import get_connection
        
        with get_connection() as conn:
            cur = conn.cursor()
            
            # Get all cycles for this user to map scan dates to phases
            cur.execute("""
                SELECT period_start_date, period_end_date, cycle_length
                FROM menstrual_cycles
                WHERE user_id = %s
                ORDER BY period_end_date DESC
                LIMIT 24
            """, (user_id,))
            
            cycles = cur.fetchall()
            if not cycles:
                # No cycle data, return defaults with score 0
                return CyclePhases(
                    phase_breakdown={
                        "menstrual": PhaseData(label="Menstrual (D1-5)", score=0, description="Increased inflammation & sensitivity"),
                        "follicular": PhaseData(label="Follicular (D6-13)", score=0, description="Rising estrogen boosts collagen & hydration"),
                        "ovulation": PhaseData(label="Ovulation (D14)", score=0, description="Peak glow & skin radiance"),
                        "luteal": PhaseData(label="Luteal (D15-28)", score=0, description="Progesterone causes texture issues"),
                    },
                    best_phase="ovulation",
                    worst_phase="menstrual"
                )
            
            # Build phase scores from skin data mapped to cycle phases
            phase_scores = {"menstrual": [], "follicular": [], "ovulation": [], "luteal": []}
            phase_scans = {"menstrual": [], "follicular": [], "ovulation": [], "luteal": []}  # Track scans per phase
            
            for scan in skin_data:
                scan_date = scan.get('created_at')
                if not scan_date:
                    continue
                
                # Convert to date if datetime
                if hasattr(scan_date, 'date'):
                    scan_date = scan_date.date()
                
                # Find which cycle this scan falls into
                for cycle in cycles:
                    cycle_start = cycle.get('period_start_date')
                    cycle_end = cycle.get('period_end_date')
                    
                    if not cycle_start or not cycle_end:
                        continue
                    
                    if cycle_start <= scan_date <= cycle_end:
                        # Calculate day in cycle
                        days_in_cycle = (scan_date - cycle_start).days
                        cycle_length = cycle.get('cycle_length') or 28
                        
                        # Map to phase
                        if 0 <= days_in_cycle <= 4:
                            phase = "menstrual"
                        elif 5 <= days_in_cycle <= 12:
                            phase = "follicular"
                        elif 13 <= days_in_cycle <= 13:
                            phase = "ovulation"
                        else:  # 14-28
                            phase = "luteal"
                        
                        # Add score and track scan
                        score = scan.get('overall_score')
                        if score is not None:
                            try:
                                phase_scores[phase].append(float(score))
                                phase_scans[phase].append(scan)  # Track scan for description generation
                            except (TypeError, ValueError):
                                pass
                        break
            
            # Calculate averages for each phase
            phase_breakdown = {}
            labels = {
                "menstrual": "Menstrual (D1-5)",
                "follicular": "Follicular (D6-13)",
                "ovulation": "Ovulation (D14)",
                "luteal": "Luteal (D15-28)"
            }
            
            for phase in ["menstrual", "follicular", "ovulation", "luteal"]:
                scores = phase_scores[phase]
                avg_score = int(sum(scores) / len(scores)) if scores else 0
                
                # Generate AI-personalized description based on user's actual phase data
                phase_description = _generate_cycle_phase_description(
                    phase=phase,
                    avg_score=avg_score,
                    phase_data=phase_scans[phase]  # Pass only scans from this phase
                )
                
                phase_breakdown[phase] = PhaseData(
                    label=labels[phase],
                    score=min(100, max(0, avg_score)),
                    description=phase_description
                )
            
            # Determine best and worst phases - only if data exists
            scores_list = [(phase, data.score) for phase, data in phase_breakdown.items()]
            
            # Only set best/worst if we have actual data (max score > 0)
            if scores_list:
                max_score = max(s[1] for s in scores_list)
                min_score = min(s[1] for s in scores_list)
                
                if max_score > 0:  # Only if there's actual data
                    best_phase = max(scores_list, key=lambda x: x[1])[0]
                    worst_phase = min(scores_list, key=lambda x: x[1])[0]
                else:  # All zeros, no data
                    best_phase = "ovulation"
                    worst_phase = "menstrual"
            else:
                best_phase = "ovulation"
                worst_phase = "menstrual"
            
            return CyclePhases(
                phase_breakdown=phase_breakdown,
                best_phase=best_phase,
                worst_phase=worst_phase
            )
    
    except Exception as exc:
        print(f"Error calculating cycle phase correlations: {exc}")
        # Fallback to safe defaults
        return CyclePhases(
            phase_breakdown={
                "menstrual": PhaseData(label="Menstrual (D1-5)", score=0, description="Increased inflammation & sensitivity"),
                "follicular": PhaseData(label="Follicular (D6-13)", score=0, description="Rising estrogen boosts collagen & hydration"),
                "ovulation": PhaseData(label="Ovulation (D14)", score=0, description="Peak glow & skin radiance"),
                "luteal": PhaseData(label="Luteal (D15-28)", score=0, description="Progesterone causes texture issues"),
            },
            best_phase="ovulation",
            worst_phase="menstrual"
        )


def _calculate_correlations(
    skin_data: list[dict[str, Any]],
    activity_data: dict[str, Any]
) -> dict[str, Any]:
    """Calculate correlations between skin metrics and lifestyle."""
    
    if not skin_data or not activity_data:
        return {}
    
    try:
        # Simple correlation analysis - ensure all values are numbers
        skin_scores = []
        for s in skin_data:
            score = s.get('overall_score')
            try:
                if score is not None:
                    skin_scores.append(float(score))
                else:
                    skin_scores.append(0)
            except (TypeError, ValueError):
                skin_scores.append(0)
        
        avg_skin = sum(skin_scores) / len(skin_scores) if skin_scores else 0
        
        # Safely get activity values
        avg_met = activity_data.get('avg_met')
        if avg_met is None:
            avg_met = 0
        else:
            try:
                avg_met = float(avg_met)
            except (TypeError, ValueError):
                avg_met = 0
        
        avg_stress = activity_data.get('avg_stress_level')
        if avg_stress is None:
            avg_stress = 0
        else:
            try:
                avg_stress = float(avg_stress)
            except (TypeError, ValueError):
                avg_stress = 0
        
        avg_activity = activity_data.get('avg_activity_seconds')
        if avg_activity is None:
            avg_activity = 0
        else:
            try:
                avg_activity = float(avg_activity) / 3600  # Convert seconds to hours
            except (TypeError, ValueError):
                avg_activity = 0
        
        return {
            "skin_trend": "improving" if skin_scores and skin_scores[0] > avg_skin else "stable",
            "stress_impact": "high" if avg_stress > 60 else "moderate",
            "activity_impact": "high" if avg_activity > 2 else "moderate",
            "met_level": "good" if avg_met > 10 else "low",
            "lifestyle_score": round((100 - min(100, avg_stress) + avg_met + (avg_activity * 10)) / 3, 1)
        }
    except Exception as e:
        print(f"Error in _calculate_correlations: {e}")
        return {}



