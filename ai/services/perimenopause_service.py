"""Perimenopause & Menopause API service with business logic."""

from datetime import datetime, date, timedelta
from typing import Any, Dict, Optional, List
import json
from collections import defaultdict

from ai.models.perimenopause_models import (
    MenopauseSummary, VasomotorTracker, VasomotorEvent, SymptomMatrix, 
    SymptomEntry, ClinicalExport, PerimenopauseInsights, ReportPreview
)

# life_journeys has two duplicate rows for the same real-world journey
# (id=4 "Peri / Menopause & Vitality", id=7 "Perimenopause/Menopause &
# Vitality") - gate on both ids instead of a single title so users linked to
# either variant are treated as having an active perimenopause journey.
PERIMENOPAUSE_JOURNEY_IDS = [4, 7]


# ============================================================================
# HARDCODED CLINICAL DATA - ACOG Guidelines
# ============================================================================

MENOPAUSE_STAGES_INFO = {
    "perimenopause": {
        "description": "Transitional phase with irregular cycles",
        "duration_months": "4-10 years",
        "key_features": ["Irregular periods", "Hot flashes", "Sleep disruption"]
    },
    "menopause": {
        "description": "Official menopause after 12 months without period",
        "duration_months": "Ongoing from diagnosis",
        "key_features": ["No menstrual periods", "Vasomotor symptoms", "Mood changes"]
    },
    "postmenopause": {
        "description": "Years after menopause transition",
        "duration_months": "Lifelong",
        "key_features": ["Bone health focus", "Cardiovascular health", "Long-term wellness"]
    }
}

TRIGGER_KEYWORDS = {
    "caffeine": ["coffee", "caffeine", "tea", "energy drink", "soda"],
    "stress": ["stress", "anxious", "worried", "overwhelmed", "pressure"],
    "spicy_food": ["spicy", "hot food", "pepper", "curry", "chili"],
    "warm_environment": ["warm", "hot room", "heat", "weather", "sun"],
    "exercise": ["exercise", "workout", "running", "gym", "walked"],
    "alcohol": ["alcohol", "wine", "beer", "drink", "cocktail"],
    "lack_of_sleep": ["sleep", "insomnia", "tired", "exhausted"],
    "hormonal": ["hormonal", "cycle", "period", "menstrual"]
}

SYMPTOM_SEVERITY_MAP = {"none": 0, "mild": 1, "moderate": 2, "severe": 3}

# Mood values are stored as emoji in health_logs.mood; map known emoji to a 1-10 score.
# Unseen emoji fall back to a neutral score rather than crashing or defaulting to "sad".
MOOD_EMOJI_SCORES = {
    "😊": 8, "🙂": 6, "😐": 5, "🙁": 3, "😢": 2, "😡": 2,
}


# ============================================================================
# HELPER FUNCTIONS - Symptom Parsing
# ============================================================================

def _normalize_symptoms(symptoms: Any) -> Dict[str, Any]:
    """
    Convert symptoms to standardized dict format.
    Handles both:
    - Old list format: ["Cramps", "Brain fog", "Hot flashes"] -> {symptom_name: "moderate"}
    - New dict format: {"hot_flash": "severe", "brain_fog": "mild"} -> passed through
    """
    if not symptoms:
        return {}
    
    # If it's a string, try to parse as JSON
    if isinstance(symptoms, str):
        try:
            symptoms = json.loads(symptoms)
        except (json.JSONDecodeError, TypeError):
            return {}
    
    # If it's a list (old format), convert to dict
    if isinstance(symptoms, list):
        symptom_dict = {}
        # Map common symptom names to default severity
        severity_map = {
            "Hot flashes": "moderate",
            "Hot flash": "moderate",
            "Night sweats": "moderate",
            "Night sweat": "moderate",
            "Brain fog": "mild",
            "Cramps": "moderate",
            "Bloating": "mild",
            "Headache": "mild",
            "Headaches": "mild",
            "Insomnia": "severe",
            "Fatigue": "moderate",
            "Fatigue ": "moderate",
            "Back pain": "mild",
            "Joint pain": "mild",
        }
        
        for symptom_name in symptoms:
            if symptom_name in severity_map:
                # Convert to snake_case key
                key = symptom_name.lower().replace(" ", "_")
                symptom_dict[key] = severity_map[symptom_name]
        
        return symptom_dict
    
    # If it's already a dict, return as-is
    if isinstance(symptoms, dict):
        return symptoms
    
    return {}


# ============================================================================
# MAIN API FUNCTIONS
# ============================================================================

def _empty_dashboard(user_id: int, period: str, journey_active: bool = False, message: Optional[str] = None) -> Dict[str, Any]:
    """Honest empty-state dashboard for users with no data (or who don't exist yet).

    Matches the same top-level shape the UI always expects, instead of an
    ad-hoc {"status": "error", ...} dict that omits every field the frontend
    depends on (transition_stage_tracker, vasomotor_tracker, etc.) and would
    otherwise be returned with a misleading HTTP 200.

    journey_active distinguishes "no active Perimenopause/Menopause journey"
    from "journey active but no data logged yet" - both produce this same
    zeroed-out shape otherwise, which a caller can't tell apart.
    """
    return {
        "transition_stage_tracker": {
            "menopause_stage": "unknown",
            "is_in_perimenopause": False,
            "months_since_last_period": None,
            "last_period_date": None,
            "cycle_status": "absent",
        },
        "vasomotor_tracker": _build_vasomotor_tracker([], period, date.today(), date.today()),
        "gsm_health": _calculate_gsm_health([]),
        "symptom_matrix": _build_symptom_matrix([], period, date.today(), date.today()),
        "clinical_export": None,
        "period_selected": period,
        "tabs": ["Symptoms", "Insights", "Export"],
        "journey_active": journey_active,
        "message": message,
    }


def _fetch_period_health_logs(user_id: int, period: str) -> tuple:
    """Fetch health_logs for a period, extending start_date back to the first
    log if the user's earliest entry predates the nominal period window.
    Returns (health_logs, start_date, end_date).
    """
    from ai.utils.db import get_connection
    with get_connection() as conn:
        cursor = conn.cursor()

        end_date = date.today()
        start_date = end_date - timedelta(days={"7d": 7, "30d": 30, "90d": 90}.get(period, 7))

        cursor.execute("""
            SELECT log_date FROM health_logs
            WHERE user_id = %s AND log_date >= %s
            ORDER BY log_date ASC LIMIT 1
        """, (user_id, start_date))
        first_log = cursor.fetchone()
        if first_log and first_log.get("log_date"):
            start_date = first_log.get("log_date")

        cursor.execute("""
            SELECT log_date, mood, energy_level, symptoms, notes
            FROM health_logs
            WHERE user_id = %s AND log_date >= %s AND log_date <= %s
            ORDER BY log_date ASC
        """, (user_id, start_date, end_date))
        health_logs = cursor.fetchall()

    return health_logs, start_date, end_date


def get_perimenopause_symptoms(user_id: int, period: str = "7d") -> Dict[str, Any]:
    """
    Get Symptoms tab data only - transition stage + vasomotor tracker + GSM health.

    No LLM call - pure DB + Python, fast path for the default/most-viewed tab.
    """
    try:
        summary = get_menopause_summary(user_id)
        if summary.get("status") == "error":
            empty = _empty_dashboard(user_id, period, journey_active=False, message=summary.get("message"))
            return {
                "transition_stage_tracker": empty["transition_stage_tracker"],
                "vasomotor_tracker": empty["vasomotor_tracker"],
                "gsm_health": empty["gsm_health"],
                "period_selected": period,
                "tabs": ["Symptoms"],
                "journey_active": False,
                "message": summary.get("message"),
            }

        health_logs, start_date, end_date = _fetch_period_health_logs(user_id, period)
        vasomotor_tracker = _build_vasomotor_tracker(health_logs, period, start_date, end_date)

        return {
            "transition_stage_tracker": {
                "menopause_stage": summary.get("menopause_stage"),
                "is_in_perimenopause": summary.get("is_in_perimenopause"),
                "months_since_last_period": summary.get("months_since_last_period"),
                "last_period_date": summary.get("last_period_date"),
                "cycle_status": summary.get("cycle_status")
            },
            "vasomotor_tracker": vasomotor_tracker,
            "gsm_health": _calculate_gsm_health(health_logs),
            "period_selected": period,
            "tabs": ["Symptoms"],
            "journey_active": True,
            "message": None,
        }

    except Exception as e:
        print(f"[ERROR] get_perimenopause_symptoms failed for user {user_id}: {e}")
        return {"status": "error", "message": str(e), "user_id": user_id}


def get_perimenopause_insights_tab(user_id: int, period: str = "7d") -> Dict[str, Any]:
    """
    Get Insights tab data only - symptom matrix with correlations.

    No LLM call - pure DB + Python, kept separate from Export so opening
    Insights never pays for the Export tab's clinical_export LLM latency.
    """
    try:
        summary = get_menopause_summary(user_id)
        if summary.get("status") == "error":
            empty_matrix = _build_symptom_matrix([], period, date.today(), date.today())
            return {
                "symptom_matrix": empty_matrix,
                "period_selected": period,
                "tabs": ["Insights"],
                "journey_active": False,
                "message": summary.get("message"),
            }

        health_logs, start_date, end_date = _fetch_period_health_logs(user_id, period)
        
        # Fetch Terra wearable data for sleep/HRV
        terra_data = _fetch_terra_sleep_data(user_id, start_date, end_date)
        symptom_matrix = _build_symptom_matrix(health_logs, period, start_date, end_date, terra_data=terra_data, user_id=user_id)

        return {
            "symptom_matrix": symptom_matrix,
            "period_selected": period,
            "tabs": ["Insights"],
            "journey_active": True,
            "message": None,
        }

    except Exception as e:
        print(f"[ERROR] get_perimenopause_insights_tab failed for user {user_id}: {e}")
        return {"status": "error", "message": str(e), "user_id": user_id}





def get_menopause_summary(user_id: int) -> Dict[str, Any]:
    """Get quick menopause status overview - UI Dashboard view."""
    try:
        from ai.utils.db import get_connection, get_user_profile, get_active_journey_by_ids
        
        # Gate on the Perimenopause/Menopause journey being active for this
        # user - previously this endpoint only checked that the user exists,
        # so any user with menstrual_cycles/health_logs rows (e.g. someone on
        # the Cycle & Fertility journey) could get perimenopause staging that
        # doesn't apply to them.
        journey = get_active_journey_by_ids(user_id, PERIMENOPAUSE_JOURNEY_IDS)
        if not journey:
            profile = get_user_profile(user_id)
            if not profile:
                return {"status": "error", "message": "User not found"}
            return {
                "status": "error",
                "message": f"User {user_id} does not have an active Perimenopause/Menopause journey.",
            }
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            profile = get_user_profile(user_id)
            
            # Get menstrual cycle data
            cursor.execute("""
                SELECT period_start_date, period_end_date, is_completed
                FROM menstrual_cycles
                WHERE user_id = %s
                ORDER BY period_end_date DESC
                LIMIT 12
            """, (user_id,))
            cycles = cursor.fetchall()
            
            # Get health logs for last 7 days
            cursor.execute("""
                SELECT log_date, mood, energy_level, symptoms, notes
                FROM health_logs
                WHERE user_id = %s AND log_date >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                ORDER BY log_date DESC
            """, (user_id,))
            health_logs = cursor.fetchall()
            
            # Wider window for symptom-cluster assessment - staging should
            # look at a recent pattern, not just the last 7 days used for the
            # daily-average metrics below.
            cursor.execute("""
                SELECT symptoms
                FROM health_logs
                WHERE user_id = %s AND log_date >= DATE_SUB(NOW(), INTERVAL 90 DAY)
            """, (user_id,))
            symptom_window_logs = cursor.fetchall()
            supporting_symptom_count = _count_supporting_symptoms(symptom_window_logs)
            
            user_age = profile.get("age")
            
            # Determine menopause stage
            menopause_stage, months_since_last_period = _determine_menopause_stage(
                cycles, age=user_age, supporting_symptom_count=supporting_symptom_count
            )
            
            # Parse vasomotor events from last 7 days
            hot_flash_count = 0
            total_severity = 0
            for log in health_logs:
                symptoms = _normalize_symptoms(log.get("symptoms"))
                hot_flash_count += symptoms.get("hot_flash_count", 0)
                if symptoms.get("hot_flash"):
                    severity_map = {"mild": 3, "moderate": 6, "severe": 9}
                    total_severity += severity_map.get(symptoms.get("hot_flash"), 0)
            
            avg_hot_flashes = hot_flash_count / 7 if health_logs else 0
            avg_severity = total_severity / max(1, hot_flash_count) if hot_flash_count > 0 else 0
            
            # Parse symptoms
            primary_symptoms = _extract_top_symptoms(health_logs)
            
            # Calculate mood stability (mood is stored as emoji, not English words)
            moods = []
            for log in health_logs:
                if log.get("mood"):
                    mood_score = MOOD_EMOJI_SCORES.get(log.get("mood"), 5)
                    moods.append(mood_score)
            mood_stability = int((sum(moods) / len(moods) / 10 * 100)) if moods else 50
            
            # Parse sleep hours
            sleep_hours = []
            for log in health_logs:
                symptoms = _normalize_symptoms(log.get("symptoms"))
                if symptoms.get("sleep_hours"):
                    sleep_hours.append(symptoms.get("sleep_hours"))
            avg_sleep = sum(sleep_hours) / len(sleep_hours) if sleep_hours else 7
            
            # Determine alerts
            alerts = _generate_perimenopause_alerts(
                avg_hot_flashes, mood_stability, avg_sleep, avg_severity
            )
            
            # Determine severity
            if avg_severity >= 7:
                overall_severity = "severe"
            elif avg_severity >= 5:
                overall_severity = "moderate"
            else:
                overall_severity = "mild"
            
            result = MenopauseSummary(
                is_in_perimenopause=menopause_stage == "perimenopause",
                menopause_stage=menopause_stage,
                months_since_last_period=months_since_last_period,
                months_in_current_stage=None,
                last_period_date=(cycles[0].get("period_end_date").isoformat() if cycles and cycles[0].get("period_end_date") else None),
                cycle_status=_determine_cycle_status(cycles),
                primary_symptoms=primary_symptoms,
                symptom_severity_overview=overall_severity,
                avg_hot_flashes_per_day=round(avg_hot_flashes, 1),
                avg_sleep_hours=round(avg_sleep, 1),
                mood_stability_percent=int(mood_stability),
                alert_status="normal" if not alerts else ("critical" if any(a for a in alerts if "severe" in a.lower()) else "warning"),
                active_alerts=alerts,
                recommended_actions=_get_recommendations(menopause_stage, primary_symptoms)
            ).model_dump(exclude_none=False)
            result["profile_id"] = journey["profile_id"]
            result["journey_id"] = journey["journey_id"]
            result["journey_title"] = journey["journey_title"]
            return result
    
    except Exception as e:
        print(f"[ERROR] get_menopause_summary failed for user {user_id}: {e}")
        return {"status": "error", "message": str(e), "user_id": user_id}


def get_perimenopause_insights(
    user_id: int,
    period: str = "7d",
    include: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Get comprehensive perimenopause insights - UI Insights view (vasomotor + symptoms)."""
    try:
        from ai.utils.db import get_connection
        
        if include is None:
            include = ["vasomotor", "symptoms"]  # Default to both
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Convert period to days
            period_days = {"7d": 7, "30d": 30, "90d": 90}.get(period, 7)
            start_date = date.today() - timedelta(days=period_days)
            end_date = date.today()
            
            # Get health logs for period
            cursor.execute("""
                SELECT log_date, mood, energy_level, symptoms, notes
                FROM health_logs
                WHERE user_id = %s AND log_date >= %s AND log_date <= %s
                ORDER BY log_date ASC
            """, (user_id, start_date, end_date))
            health_logs = cursor.fetchall()
            
            # Get menstrual cycles for stage
            cursor.execute("""
                SELECT period_start_date, period_end_date, is_completed
                FROM menstrual_cycles
                WHERE user_id = %s
                ORDER BY period_end_date DESC
                LIMIT 12
            """, (user_id,))
            cycles = cursor.fetchall()
            
            # Get menopause summary
            summary = get_menopause_summary(user_id)
            
            # Fetch Terra wearable data for sleep/HRV
            terra_data = _fetch_terra_sleep_data(user_id, start_date, end_date)
            
            result = {"summary": summary}
            
            # Build vasomotor tracker if requested
            if "vasomotor" in include:
                vasomotor = _build_vasomotor_tracker(health_logs, period, start_date, end_date)
                result["vasomotor_tracker"] = vasomotor
            
            # Build symptom matrix if requested (with Terra data)
            if "symptoms" in include:
                symptom_matrix = _build_symptom_matrix(health_logs, period, start_date, end_date, terra_data=terra_data, user_id=user_id)
                result["symptom_matrix"] = symptom_matrix
            
            return result
    
    except Exception as e:
        print(f"[ERROR] get_perimenopause_insights failed for user {user_id}: {e}")
        return {"status": "error", "message": str(e), "user_id": user_id}


def get_perimenopause_export(user_id: int, period: str = "7d") -> Dict[str, Any]:
    """
    Get Export tab data only - clinical_export with LLM-generated recommendations.

    period-based wrapper around get_clinical_export, matching the signature of
    get_perimenopause_symptoms/get_perimenopause_insights_tab so all 3 tabs
    can be called independently. This is the only one of the 3 tab endpoints
    that makes an LLM call, so it should be requested on-demand (tab opened /
    Export button clicked), not on every dashboard load.
    """
    end_date = date.today()
    start_date = end_date - timedelta(days={"7d": 7, "30d": 30, "90d": 90}.get(period, 7))
    result = get_clinical_export(user_id, start_date.isoformat(), end_date.isoformat())
    if result.get("status") == "error":
        return {
            "clinical_export": None,
            "tabs": ["Export"],
            "journey_active": False,
            "message": result.get("message"),
        }
    return {
        "clinical_export": result,
        "tabs": ["Export"],
        "journey_active": True,
        "message": None,
    }


def get_clinical_export(
    user_id: int,
    start_date: str,
    end_date: str
) -> Dict[str, Any]:
    """Get clinical export ready for sharing with healthcare provider."""
    try:
        from ai.utils.db import get_connection, get_user_profile, get_active_journey_by_ids
        from ai.utils.llm_call import llm_call
        
        journey = get_active_journey_by_ids(user_id, PERIMENOPAUSE_JOURNEY_IDS)
        if not journey:
            return {
                "status": "error",
                "message": f"User {user_id} does not have an active Perimenopause/Menopause journey.",
            }
        
        # Get journey created_at for stage duration calculation
        journey_created_at = None
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT ljp.created_at
                FROM life_journey_profile ljp
                JOIN profiles p ON p.id = ljp.profile_id
                WHERE p.user_id = %s AND ljp.life_journey_id IN (%s, %s)
                ORDER BY ljp.created_at ASC
                LIMIT 1
            """, (user_id, *PERIMENOPAUSE_JOURNEY_IDS[:2]))
            journey_row = cursor.fetchone()
            if journey_row and journey_row.get("created_at"):
                journey_created_at = journey_row["created_at"]
                if isinstance(journey_created_at, date) and not isinstance(journey_created_at, datetime):
                    journey_created_at = datetime.combine(journey_created_at, datetime.min.time())
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Parse dates
            start = datetime.fromisoformat(start_date).date()
            end = datetime.fromisoformat(end_date).date()
            
            # Get health logs for period
            cursor.execute("""
                SELECT log_date, mood, energy_level, symptoms, notes
                FROM health_logs
                WHERE user_id = %s AND log_date >= %s AND log_date <= %s
                ORDER BY log_date ASC
            """, (user_id, start, end))
            health_logs = cursor.fetchall()
            
            # Get menstrual cycles
            cursor.execute("""
                SELECT period_start_date, period_end_date, is_completed
                FROM menstrual_cycles
                WHERE user_id = %s
                ORDER BY period_end_date DESC
                LIMIT 12
            """, (user_id,))
            cycles = cursor.fetchall()
            
            profile = get_user_profile(user_id)
            user_age = profile.get("age") if profile else None
            supporting_symptom_count = _count_supporting_symptoms(health_logs)
            
            # Determine stage
            menopause_stage, months_since_last = _determine_menopause_stage(
                cycles, age=user_age, supporting_symptom_count=supporting_symptom_count
            )
            
            # Get real FSH lab value if available - clinical_recommendations
            # and suggested_tests below previously referenced FSH only as
            # static boilerplate text with no connection to actual lab data.
            cursor.execute("""
                SELECT biomarkers
                FROM lab_reports
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 1
            """, (user_id,))
            latest_lab = cursor.fetchone()
            fsh_value, fsh_status = _extract_fsh_from_biomarkers(latest_lab.get("biomarkers") if latest_lab else None)
            
            # Fetch Terra wearable data for sleep
            terra_data = _fetch_terra_sleep_data(user_id, start, end)
            
            # Get vasomotor data
            vasomotor = _build_vasomotor_tracker(health_logs, "custom", start, end)
            
            # Get symptom data (with Terra)
            symptom_matrix = _build_symptom_matrix(health_logs, "custom", start, end, terra_data=terra_data, user_id=user_id)
            
            # Compile metrics
            primary_symptoms = _extract_top_symptoms(health_logs)
            
            # Parse severity and health metrics
            symptom_severity_breakdown = {}
            for symptom in primary_symptoms:
                severity_counts = defaultdict(int)
                for log in health_logs:
                    symptoms = _normalize_symptoms(log.get("symptoms"))
                    if symptoms.get(symptom):
                        severity_counts[symptoms.get(symptom)] += 1
                
                if severity_counts:
                    most_common = max(severity_counts, key=severity_counts.get)
                    symptom_severity_breakdown[symptom] = most_common
            
            # Calculate sleep - prefer Terra wearable data
            avg_sleep_hours = None
            if terra_data and terra_data.get("has_data") and terra_data.get("avg_sleep_hours") is not None:
                avg_sleep_hours = terra_data["avg_sleep_hours"]
            
            # Fallback to health_logs
            if avg_sleep_hours is None:
                sleep_hours = []
                for log in health_logs:
                    symptoms = _normalize_symptoms(log.get("symptoms"))
                    if symptoms.get("sleep_hours"):
                        sleep_hours.append(symptoms.get("sleep_hours"))
                avg_sleep_hours = sum(sleep_hours) / len(sleep_hours) if sleep_hours else 7
            
            sleep_quality_scores = []
            for log in health_logs:
                symptoms = _normalize_symptoms(log.get("symptoms"))
                if symptoms.get("sleep_quality"):
                    sq_map = {"poor": 1, "fair": 2, "good": 3, "excellent": 4}
                    sleep_quality_scores.append(sq_map.get(symptoms.get("sleep_quality"), 2))
            sleep_quality_avg = sum(sleep_quality_scores) / len(sleep_quality_scores) if sleep_quality_scores else 2
            sleep_quality_labels = {1: "poor", 2: "fair", 3: "good", 4: "excellent"}
            sleep_quality = sleep_quality_labels.get(round(sleep_quality_avg), "fair")
            
            # Generate LLM recommendations
            symptom_summary = ", ".join(primary_symptoms) if primary_symptoms else "No symptoms recorded"
            sleep_summary = f"{avg_sleep_hours:.1f} hours per night"
            vasomotor_summary = f"{vasomotor.get('avg_daily_frequency', 0):.1f} events per day"
            age_summary = f"{user_age} years old" if user_age else "age not on file"
            fsh_summary = f"{fsh_value} ({fsh_status})" if fsh_value is not None else "no recent FSH lab on file"
            
            llm_prompt = f"""
Based on menopause data from {start} to {end}:
- Stage: {menopause_stage}
- Patient age: {age_summary}
- Primary symptoms: {symptom_summary}
- Average sleep: {sleep_summary}
- Hot flashes: {vasomotor_summary}
- Latest FSH: {fsh_summary}

Provide 3-4 specific clinical recommendations for a gynecologist.
Format as bullet points.
            """
            
            try:
                clinical_rec_text = llm_call(llm_prompt, max_tokens=200)
                clinical_recommendations = [line.strip() for line in clinical_rec_text.split('\n') if line.strip() and line.startswith('-')][:4]
            except:
                clinical_recommendations = [
                    "Schedule follow-up with gynecologist",
                    "Consider hormone level testing (FSH, estradiol)",
                    "Evaluate lifestyle modifications",
                    "Monitor symptom progression"
                ]
            
            # Lifestyle recommendations
            lifestyle_rec = [
                "Maintain consistent sleep schedule (aim for 7-8 hours)",
                "Regular exercise (150 min/week aerobic + strength training)",
                "Reduce caffeine and spicy foods if they trigger symptoms",
                "Practice stress reduction techniques (yoga, meditation, breathing)"
            ]
            
            # Warning flags
            warning_flags = []
            if avg_sleep_hours < 5:
                warning_flags.append("Severe sleep disruption (< 5 hours/night) - Priority: High")
            if vasomotor.get("avg_severity", 0) >= 8:
                warning_flags.append("Severe vasomotor symptoms - Consider HRT evaluation")
            if symptom_matrix.get("avg_mood_stability_percent", 50) < 40:
                warning_flags.append("Significant mood instability - Mental health support recommended")
            if fsh_status == "elevated":
                warning_flags.append(f"FSH elevated ({fsh_value}) - Correlate with menstrual history")
            if menopause_stage == "insufficient_data" and (user_age or 0) >= MIN_PLAUSIBLE_PERIMENOPAUSE_AGE:
                warning_flags.append(
                    "Age-appropriate but insufficient cycle/symptom history to confirm stage - continue monitoring"
                )
            
            # Suggested tests
            suggested_tests = [
                "FSH (Follicle-Stimulating Hormone)",
                "Estradiol level",
                "TSH (Thyroid function)",
                "Vitamin D",
                "Iron and ferritin",
                "Lipid panel"
            ]
            
            # Calculate GSM health for report preview
            gsm_health = _calculate_gsm_health(health_logs)
            
            # Determine period string from date range
            days_in_period = (end - start).days
            if days_in_period <= 7:
                period_str = "7d"
            elif days_in_period <= 30:
                period_str = "30d"
            else:
                period_str = "90d"
            
            # Build report preview (clean UI summary)
            # Pass user_age for clinical integrity - prevents labeling young users as perimenopause
            # Pass user_id and date range for dynamic data queries (vasomotor_logs, perimenopause_profiles)
            report_preview = _build_report_preview(
                user_id=user_id,
                journey_created_at=journey_created_at,
                menopause_stage=menopause_stage,
                months_since_last_period=months_since_last,
                health_logs=health_logs,
                period=period_str,
                days_in_period=days_in_period,
                start_date=start,
                end_date=end,
                terra_data=terra_data,
                mood_stability_percent=symptom_matrix.get("avg_mood_stability_percent", 50),
                gsm_health=gsm_health,
                fsh_value=fsh_value,
                fsh_status=fsh_status,
                user_age=user_age
            )
            
            result = ClinicalExport(
                export_date=datetime.now().strftime("%b %d, %Y"),
                period_covered=f"{start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}",
                menopause_stage=menopause_stage,
                months_since_onset=None,
                months_since_last_period=months_since_last,
                vasomotor_events_total=vasomotor.get("total_events", 0),
                vasomotor_avg_frequency_per_day=vasomotor.get("avg_daily_frequency", 0),
                vasomotor_avg_severity=vasomotor.get("avg_severity", 0),
                vasomotor_trend=vasomotor.get("trend", "stable"),
                vasomotor_primary_triggers=[x[0] for x in sorted(
                    vasomotor.get("common_triggers", {}).items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:3]],
                primary_symptoms=primary_symptoms,
                symptom_severity_breakdown=symptom_severity_breakdown,
                avg_sleep_hours=avg_sleep_hours,
                sleep_quality=sleep_quality,
                avg_mood_stability=symptom_matrix.get("avg_mood_stability_percent", 50),
                weight_change_lbs=None,
                clinical_recommendations=clinical_recommendations,
                lifestyle_recommendations=lifestyle_rec,
                warning_flags=warning_flags,
                suggested_tests=suggested_tests,
                data_points_collected=len(health_logs),
                data_completeness_percent=min(100, int((len(health_logs) / max(1, (end - start).days)) * 100))
            ).model_dump(exclude_none=False)
            result["profile_id"] = journey["profile_id"]
            result["journey_id"] = journey["journey_id"]
            result["journey_title"] = journey["journey_title"]
            
            # Add report_preview - clean UI summary with 6 personalized fields
            result["report_preview"] = report_preview
            
            return result
    
    except Exception as e:
        print(f"[ERROR] get_clinical_export failed for user {user_id}: {e}")
        return {"status": "error", "message": str(e), "user_id": user_id}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def _fetch_terra_sleep_data(user_id: int, start_date: date, end_date: date) -> Dict[str, Any]:
    """Fetch sleep/HRV data from terra_activity_data for perimenopause insights.
    
    Returns dict with avg_sleep_hours, avg_hrv, sleep_score, has_data flag.
    Structure-safe: returns None values (not defaults) when no data exists.
    """
    try:
        from ai.utils.db import get_connection
        
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT payload, created_at
                FROM terra_activity_data
                WHERE user_id = %s 
                  AND created_at >= %s
                  AND created_at <= %s
                ORDER BY created_at DESC
                LIMIT 30
                """,
                (user_id, start_date.isoformat(), (end_date + timedelta(days=1)).isoformat()),
            )
            rows = cursor.fetchall()
            
            if not rows:
                return {
                    "avg_sleep_hours": None,
                    "avg_hrv": None,
                    "sleep_score": None,
                    "recovery_score": None,
                    "has_data": False,
                }
            
            sleep_scores = []
            hrv_values = []
            recovery_scores = []
            
            for row in rows:
                try:
                    payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
                except (json.JSONDecodeError, TypeError):
                    continue
                
                # Extract sleep score from scores dict
                try:
                    scores = payload.get("scores", {})
                    if scores.get("sleep") is not None:
                        sleep_scores.append(float(scores["sleep"]))
                    if scores.get("recovery") is not None:
                        recovery_scores.append(float(scores["recovery"]))
                    
                    # Also check nested data structure
                    data_list = payload.get("data", [])
                    if data_list and isinstance(data_list, list):
                        for data_item in data_list:
                            nested_scores = data_item.get("scores", {})
                            if nested_scores.get("sleep") is not None:
                                sleep_scores.append(float(nested_scores["sleep"]))
                except (ValueError, TypeError, AttributeError):
                    pass
                
                # Extract HRV
                try:
                    data_list = payload.get("data", [])
                    if data_list and isinstance(data_list, list):
                        for data_item in data_list:
                            hrv = data_item.get("heart_data", {}).get("heart_rate_data", {}).get("summary", {}).get("avg_hrv_rmssd")
                            if hrv is not None:
                                hrv_values.append(float(hrv))
                except (ValueError, TypeError, AttributeError, IndexError):
                    pass
            
            # Calculate averages - return None if no valid data
            avg_sleep_score = sum(sleep_scores) / len(sleep_scores) if sleep_scores else None
            avg_hrv = sum(hrv_values) / len(hrv_values) if hrv_values else None
            avg_recovery = sum(recovery_scores) / len(recovery_scores) if recovery_scores else None
            
            # Convert sleep score to hours estimate (score is typically 0-100 scale)
            # This is approximate - actual sleep duration would need sleep_durations_data
            avg_sleep_hours = None
            if avg_sleep_score is not None:
                # Map score to hours: score 80+ = 7-8hrs, 60-80 = 6-7hrs, <60 = 5-6hrs
                avg_sleep_hours = round(5 + (avg_sleep_score / 100) * 3, 1)
            
            return {
                "avg_sleep_hours": avg_sleep_hours,
                "avg_hrv": round(avg_hrv, 1) if avg_hrv else None,
                "sleep_score": round(avg_sleep_score, 1) if avg_sleep_score else None,
                "recovery_score": round(avg_recovery, 1) if avg_recovery else None,
                "has_data": bool(sleep_scores or hrv_values),
            }
    except Exception as e:
        print(f"[ERROR] _fetch_terra_sleep_data for user {user_id}: {e}")
        return {"avg_sleep_hours": None, "avg_hrv": None, "has_data": False}


# Perimenopause onset before this age is clinically atypical (suggestive of
# POI/thyroid/PCOS rather than a default assumption) per ACOG/STRAW+10
# guidance, so age-gating avoids mislabeling young irregular cycles.
MIN_PLAUSIBLE_PERIMENOPAUSE_AGE = 35

# Vasomotor/sleep/mood/GSM symptom keys STRAW+10-style staging treats as
# supporting evidence for perimenopause when clustered alongside cycle
# irregularity - a single incidental symptom is not diagnostic on its own.
PERIMENOPAUSE_SUPPORTING_SYMPTOMS = {
    "hot_flashes", "hot_flash", "night_sweats", "night_sweat",
    "vaginal_dryness", "urinary_frequency", "pelvic_discomfort", "libido_impact",
    "brain_fog", "insomnia",
}
MIN_SUPPORTING_SYMPTOMS_FOR_PERIMENOPAUSE = 2


def _count_supporting_symptoms(health_logs: list) -> int:
    """Count distinct perimenopause-supporting symptoms logged (not raw occurrences)."""
    found = set()
    for log in health_logs:
        symptoms = _normalize_symptoms(log.get("symptoms"))
        for key, value in symptoms.items():
            if key in PERIMENOPAUSE_SUPPORTING_SYMPTOMS and value and value not in ("none", "None", 0):
                found.add(key)
    return len(found)


def _extract_fsh_from_biomarkers(biomarkers_data: Any) -> tuple[Optional[str], Optional[str]]:
    """Extract FSH value and status from lab_reports.biomarkers JSON.

    Returns (fsh_value_string, status) where status is "elevated", "normal",
    or None if no FSH found. This connects real lab data (not static boilerplate)
    to clinical recommendations and warning flags.
    """
    if not biomarkers_data:
        return None, None
    
    try:
        if isinstance(biomarkers_data, str):
            biomarkers_data = json.loads(biomarkers_data)
        
        needs_attention = biomarkers_data.get("needs_attention") or []
        normal_results = biomarkers_data.get("normal_results") or []
        
        def _is_valid_fsh_value(value: Any) -> bool:
            """Check if FSH value is a valid numeric reading, not 'Not found' or empty."""
            if not value:
                return False
            value_str = str(value).strip().lower()
            # Invalid values from OCR/parsing failures
            if value_str in ("not found", "n/a", "na", "none", "", "-", "pending"):
                return False
            # Try to extract a numeric value
            try:
                # Handle values like "18.4 mIU/mL" or just "18.4"
                numeric_part = ''.join(c for c in value_str.split()[0] if c.isdigit() or c == '.')
                if numeric_part:
                    float(numeric_part)
                    return True
            except (ValueError, IndexError):
                pass
            return False
        
        for biomarker in needs_attention:
            if biomarker.get("name", "").upper() == "FSH":
                value = biomarker.get("value")
                if _is_valid_fsh_value(value):
                    return value, "elevated"
        
        for biomarker in normal_results:
            if biomarker.get("name", "").upper() == "FSH":
                value = biomarker.get("value")
                if _is_valid_fsh_value(value):
                    return value, "normal"
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass
    
    return None, None


# ============================================================================
# REPORT PREVIEW HELPER FUNCTIONS - Dynamic UI Fields
# ============================================================================

def _calculate_stage_display(
    journey_created_at: Optional[datetime],
    menopause_stage: str,
    months_since_last_period: Optional[int],
    user_age: Optional[int] = None
) -> Optional[str]:
    """
    Calculate stage display string for UI Report Preview.
    
    Returns format like "Year 2 (confirmed)" or "Perimenopause (tracking)"
    Returns None for age-implausible users (under 35) with unknown/insufficient data.
    
    Clinical integrity: Perimenopause typically occurs 40-55, rarely before 35.
    We don't label young users as "Perimenopause" without clinical evidence.
    """
    if not journey_created_at:
        return None
    
    # Age-based validation: Don't display perimenopause stage for young users
    # unless there's confirmed clinical evidence (actual perimenopause/menopause stage)
    age_is_plausible = user_age is None or user_age >= MIN_PLAUSIBLE_PERIMENOPAUSE_AGE
    
    # For age-implausible users with unknown/insufficient data, return None
    # This prevents labeling an 18-year-old as "Perimenopause"
    if not age_is_plausible and menopause_stage in ("unknown", "insufficient_data", "regular_cycles"):
        return None
    
    # For age-plausible users with unknown/insufficient data, show tracking status
    if menopause_stage in ("unknown", "insufficient_data"):
        if age_is_plausible:
            return "Tracking (awaiting data)"
        return None
    
    # For regular cycles (not perimenopause), return appropriate message
    if menopause_stage == "regular_cycles":
        return "Regular cycles (not in perimenopause)"
    
    # Calculate years in journey for confirmed stages
    days_in_journey = (datetime.now() - journey_created_at).days
    years_in_journey = max(1, days_in_journey // 365)
    
    # Determine confirmation status
    # Menopause is "confirmed" after 12+ months without period
    if months_since_last_period and months_since_last_period >= 12:
        confirmation = "confirmed"
    elif menopause_stage in ("menopause", "postmenopause"):
        confirmation = "confirmed"
    elif menopause_stage == "perimenopause":
        confirmation = "tracking"
    else:
        confirmation = "tracking"
    
    # Format stage name for display
    stage_display = menopause_stage.replace("_", " ").title()
    
    return f"{stage_display} · Year {years_in_journey} ({confirmation})"


def _calculate_hot_flash_display(
    user_id: int,
    period: str,
    start_date: date,
    end_date: date
) -> Optional[str]:
    """
    Calculate hot flash frequency display for UI Report Preview.
    
    Data source: vasomotor_logs table (primary), perimenopause_profiles (fallback)
    
    Returns format like "4.3/day (this month)"
    """
    from ai.utils.db import get_connection
    
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Primary source: vasomotor_logs - real tracked data
            cursor.execute("""
                SELECT 
                    SUM(total_episodes) as total,
                    COUNT(*) as days_logged
                FROM vasomotor_logs
                WHERE user_id = %s 
                  AND log_date >= %s 
                  AND log_date <= %s
            """, (user_id, start_date, end_date))
            
            result = cursor.fetchone()
            
            if result and result.get("total") and result.get("days_logged", 0) > 0:
                total_episodes = result["total"]
                days_logged = result["days_logged"]
                
                # Calculate average over days WITH data (more accurate)
                avg_per_day = total_episodes / days_logged
                
                # Format period label
                period_label = {
                    "7d": "this week",
                    "30d": "this month",
                    "90d": "past 3 months"
                }.get(period, "selected period")
                
                return f"{avg_per_day:.1f}/day ({period_label})"
            
            # Fallback: perimenopause_profiles (pre-computed value)
            cursor.execute("""
                SELECT avg_hot_flashes_per_day
                FROM perimenopause_profiles
                WHERE user_id = %s
                LIMIT 1
            """, (user_id,))
            
            profile = cursor.fetchone()
            if profile and profile.get("avg_hot_flashes_per_day"):
                avg = profile["avg_hot_flashes_per_day"]
                period_label = {
                    "7d": "this week",
                    "30d": "this month", 
                    "90d": "past 3 months"
                }.get(period, "selected period")
                return f"{avg:.1f}/day ({period_label})"
            
            return None
            
    except Exception as e:
        print(f"[ERROR] _calculate_hot_flash_display failed: {e}")
        return None


def _calculate_sleep_disruption_display(
    user_id: int,
    health_logs: list,
    terra_data: Optional[Dict[str, Any]],
    days_in_period: int
) -> Optional[str]:
    """
    Calculate sleep disruption display for UI Report Preview.
    
    Data sources: health_logs, terra_data, perimenopause_profiles (fallback)
    
    Returns format like "3.2 nights/week"
    """
    from ai.utils.db import get_connection
    
    disrupted_nights = 0
    
    # Count disrupted nights from health logs
    for log in health_logs:
        symptoms = _normalize_symptoms(log.get("symptoms"))
        
        # Check for explicit sleep disruption
        sleep_disruption = symptoms.get("sleep_disruption")
        if sleep_disruption and sleep_disruption not in ("none", "None"):
            disrupted_nights += 1
            continue
        
        # Check for poor sleep quality
        sleep_quality = symptoms.get("sleep_quality")
        if sleep_quality in ("poor", "very_poor"):
            disrupted_nights += 1
            continue
        
        # Check for low sleep hours (< 6 hours = disrupted)
        sleep_hours = symptoms.get("sleep_hours")
        if sleep_hours is not None:
            try:
                if float(sleep_hours) < 6:
                    disrupted_nights += 1
                    continue
            except (ValueError, TypeError):
                pass
        
        # Check for night sweats (implies disrupted sleep)
        night_sweat_val = symptoms.get("night_sweat") or symptoms.get("night_sweats")
        if night_sweat_val and night_sweat_val not in ("none", "None", "0", 0):
            disrupted_nights += 1
    
    # Also check Terra wearable data for sleep score
    if terra_data and terra_data.get("has_data"):
        terra_sleep_score = terra_data.get("sleep_score")
        if terra_sleep_score is not None and terra_sleep_score < 60:
            # Low sleep score from wearable indicates disruption
            pass  # Terra data supplements, doesn't replace log data
    
    if disrupted_nights > 0:
        weeks_in_period = max(1, days_in_period / 7)
        avg_per_week = disrupted_nights / weeks_in_period
        return f"{avg_per_week:.1f} nights/week"
    
    # Fallback: perimenopause_profiles (pre-computed value)
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT sleep_disruption_nights_per_week
                FROM perimenopause_profiles
                WHERE user_id = %s
                LIMIT 1
            """, (user_id,))
            
            profile = cursor.fetchone()
            if profile and profile.get("sleep_disruption_nights_per_week"):
                return f"{profile['sleep_disruption_nights_per_week']:.1f} nights/week"
    except Exception as e:
        print(f"[ERROR] _calculate_sleep_disruption_display fallback failed: {e}")
    
    return None


def _calculate_mood_instability_display(
    health_logs: list,
    mood_stability_percent: int
) -> Optional[str]:
    """
    Calculate mood instability label for UI Report Preview.
    
    Returns format like "Mild", "Mild–Moderate", "Moderate–Severe"
    """
    if not health_logs:
        return None
    
    # Check if any mood data exists
    has_mood_data = any(log.get("mood") for log in health_logs)
    if not has_mood_data:
        return None
    
    # Map stability percentage to instability label
    # Higher stability = lower instability
    if mood_stability_percent >= 80:
        return "Stable"
    elif mood_stability_percent >= 65:
        return "Mild"
    elif mood_stability_percent >= 50:
        return "Mild–Moderate"
    elif mood_stability_percent >= 35:
        return "Moderate"
    elif mood_stability_percent >= 20:
        return "Moderate–Severe"
    else:
        return "Severe"


def _calculate_gsm_symptoms_display(gsm_health: Dict[str, Dict]) -> Optional[str]:
    """
    Calculate GSM symptoms summary for UI Report Preview.
    
    Returns format like "Mild dryness & frequency"
    """
    if not gsm_health:
        return None
    
    active_symptoms = []
    
    # Check each GSM symptom
    symptom_labels = {
        "vaginal_dryness": "dryness",
        "urinary_frequency": "frequency",
        "pelvic_discomfort": "discomfort",
        "libido_impact": "libido changes"
    }
    
    for symptom_key, label in symptom_labels.items():
        symptom_data = gsm_health.get(symptom_key, {})
        level = symptom_data.get("level")
        
        if level and level not in ("not_reported", "none", "None"):
            # Format as "Mild dryness" or "Moderate frequency"
            level_display = level.title()
            active_symptoms.append(f"{level_display} {label}")
    
    if not active_symptoms:
        return None
    
    # Join with " & " for clean display
    if len(active_symptoms) == 1:
        return active_symptoms[0]
    elif len(active_symptoms) == 2:
        return f"{active_symptoms[0]} & {active_symptoms[1]}"
    else:
        # More than 2: "X, Y & Z"
        return f"{', '.join(active_symptoms[:-1])} & {active_symptoms[-1]}"


def _calculate_fsh_reading_display(
    user_id: int,
    fsh_value: Optional[str],
    fsh_status: Optional[str]
) -> Optional[str]:
    """
    Calculate FSH reading display for UI Report Preview.
    
    Data sources: lab_reports.biomarkers (primary), perimenopause_profiles.fsh_level (fallback)
    
    Returns format like "18.4 mIU/mL (elevated)"
    """
    from ai.utils.db import get_connection
    
    # Use lab_reports FSH if available
    if fsh_value:
        value_str = str(fsh_value).strip()
        
        # Check if it already has units
        if "mIU" in value_str or "IU" in value_str:
            display_value = value_str
        else:
            display_value = f"{value_str} mIU/mL"
        
        # Add status if available
        if fsh_status:
            return f"{display_value} ({fsh_status})"
        return display_value
    
    # Fallback: perimenopause_profiles.fsh_level
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT fsh_level
                FROM perimenopause_profiles
                WHERE user_id = %s
                LIMIT 1
            """, (user_id,))
            
            profile = cursor.fetchone()
            if profile and profile.get("fsh_level"):
                fsh_level = profile["fsh_level"]
                # Determine status based on typical FSH ranges
                # Elevated: >25 mIU/mL suggests perimenopause
                # Normal: <10 mIU/mL in reproductive age
                if fsh_level >= 25:
                    status = "elevated"
                elif fsh_level >= 10:
                    status = "borderline"
                else:
                    status = "normal"
                return f"{fsh_level:.1f} mIU/mL ({status})"
    except Exception as e:
        print(f"[ERROR] _calculate_fsh_reading_display fallback failed: {e}")
    
    return None


def _build_report_preview(
    user_id: int,
    journey_created_at: Optional[datetime],
    menopause_stage: str,
    months_since_last_period: Optional[int],
    health_logs: list,
    period: str,
    days_in_period: int,
    start_date: date,
    end_date: date,
    terra_data: Optional[Dict[str, Any]],
    mood_stability_percent: int,
    gsm_health: Dict[str, Dict],
    fsh_value: Optional[str],
    fsh_status: Optional[str],
    user_age: Optional[int] = None
) -> Dict[str, Any]:
    """
    Build the complete Report Preview for UI.
    
    Returns a clean dict with 6 fields, each nullable if data is missing.
    Respects clinical integrity - won't label young users as perimenopause.
    
    Data sources:
    - stage: journey_created_at, menopause_stage, user_age
    - avg_hot_flashes: vasomotor_logs (primary), perimenopause_profiles (fallback)
    - sleep_disruption: health_logs, perimenopause_profiles (fallback)
    - mood_instability: health_logs, mood_stability_percent
    - gsm_symptoms: gsm_health dict
    - last_fsh_reading: lab_reports (primary), perimenopause_profiles (fallback)
    """
    return ReportPreview(
        stage=_calculate_stage_display(
            journey_created_at, menopause_stage, months_since_last_period, user_age
        ),
        avg_hot_flashes=_calculate_hot_flash_display(
            user_id, period, start_date, end_date
        ),
        sleep_disruption=_calculate_sleep_disruption_display(
            user_id, health_logs, terra_data, days_in_period
        ),
        mood_instability=_calculate_mood_instability_display(
            health_logs, mood_stability_percent
        ),
        gsm_symptoms=_calculate_gsm_symptoms_display(gsm_health),
        last_fsh_reading=_calculate_fsh_reading_display(user_id, fsh_value, fsh_status)
    ).model_dump()


def _determine_menopause_stage(
    cycles: list,
    age: Optional[int] = None,
    supporting_symptom_count: int = 0,
) -> tuple:
    """Determine menopause stage based on menstrual cycles, age, and symptom clustering.

    Cycle irregularity alone is not diagnostic - real staging (STRAW+10/ACOG)
    considers age plausibility and clustered vasomotor/sleep/mood/GSM symptoms
    alongside cycle history. age and supporting_symptom_count are optional so
    existing callers without that data still get a safe (insufficient_data)
    result rather than a crash.
    """
    if not cycles:
        return "unknown", None
    
    # Get last completed cycle
    last_period = None
    for cycle in cycles:
        if cycle.get("period_end_date"):
            last_period = cycle.get("period_end_date")
            break
    
    if not last_period:
        return "unknown", None
    
    months_since = (date.today() - last_period).days // 30
    
    # Check cycle regularity. Regularity can only be assessed with >=3 completed
    # cycles - fewer than that means there isn't enough evidence either way.
    completed_cycles = [c for c in cycles if c.get("is_completed")]
    has_enough_data_for_regularity = len(completed_cycles) >= 3
    is_irregular = False
    if has_enough_data_for_regularity:
        cycle_lengths = []
        for i in range(len(completed_cycles) - 1):
            if completed_cycles[i].get("period_end_date") and completed_cycles[i+1].get("period_end_date"):
                length = (completed_cycles[i].get("period_end_date") - 
                         completed_cycles[i+1].get("period_end_date")).days
                if length > 0:
                    cycle_lengths.append(length)
        
        is_irregular = len(cycle_lengths) >= 2 and max(cycle_lengths) - min(cycle_lengths) > 7
    
    # Age-implausible irregular cycles (e.g. a 22-year-old) should not be
    # labeled perimenopause - flag separately rather than silently guessing.
    age_implausible = age is not None and age < MIN_PLAUSIBLE_PERIMENOPAUSE_AGE
    
    has_symptom_cluster = supporting_symptom_count >= MIN_SUPPORTING_SYMPTOMS_FOR_PERIMENOPAUSE
    
    # Determine stage. The previous fallback silently returned "perimenopause"
    # for any case that didn't clearly match menopause/postmenopause, even when
    # there wasn't enough completed-cycle history, wasn't an age-plausible
    # range, or had no supporting symptom cluster - reporting a clinical stage
    # the data couldn't support. Age-implausible cases fold into the existing
    # "insufficient_data" value rather than introducing a new stage string,
    # to keep the response's value space unchanged.
    if months_since >= 60:
        return "postmenopause", months_since
    elif 12 <= months_since < 60:
        return "menopause", months_since
    elif (
        months_since < 12
        and not age_implausible
        and has_enough_data_for_regularity
        and is_irregular
        and has_symptom_cluster
    ):
        return "perimenopause", months_since
    elif (
        months_since < 12
        and not age_implausible
        and has_enough_data_for_regularity
        and not is_irregular
    ):
        return "regular_cycles", months_since
    else:
        return "insufficient_data", months_since


def _determine_cycle_status(cycles: list) -> str:
    """Determine if cycles are regular, irregular, or absent."""
    if not cycles:
        return "absent"
    
    last_period = cycles[0].get("period_end_date") if cycles[0].get("period_end_date") else None
    
    if not last_period:
        return "absent"
    
    months_since = (date.today() - last_period).days // 30
    
    if months_since > 12:
        return "absent"
    
    # Check regularity
    cycle_lengths = []
    for cycle in cycles[:6]:
        if cycle.get("is_completed") and cycle.get("period_end_date"):
            cycle_lengths.append(cycle.get("period_end_date"))
    
    if len(cycle_lengths) >= 2:
        days_between = [(cycle_lengths[i] - cycle_lengths[i+1]).days for i in range(len(cycle_lengths)-1)]
        if days_between and max(days_between) - min(days_between) > 7:
            return "irregular"
        else:
            return "regular"
    
    return "irregular"


def _extract_top_symptoms(health_logs: list, limit: int = 5) -> List[str]:
    """Extract most common symptoms from health logs.

    Returns symptom keys only (e.g. "cramps", "hot_flashes") - this feeds
    user/doctor-facing fields (MenopauseSummary.primary_symptoms,
    ClinicalExport.primary_symptoms), so mood/energy tracking must not leak
    into the output as raw values like "mood_🙂".
    """
    symptom_counts = defaultdict(int)
    
    for log in health_logs:
        symptoms = _normalize_symptoms(log.get("symptoms"))
        
        # Count non-empty symptoms
        for symptom, value in symptoms.items():
            if value and value != "none" and symptom not in ["notes", "sleep_hours", "sleep_quality"]:
                symptom_counts[symptom] += 1
    
    # Sort and return top
    sorted_symptoms = sorted(symptom_counts.items(), key=lambda x: x[1], reverse=True)
    return [s[0] for s in sorted_symptoms[:limit]]


def _generate_perimenopause_alerts(
    avg_hot_flashes: float,
    mood_stability: int,
    avg_sleep: float,
    avg_severity: float
) -> List[str]:
    """Generate alerts based on current metrics."""
    alerts = []
    
    if avg_hot_flashes > 10:
        alerts.append("Severe hot flashes (>10/day) - Consider medical evaluation")
    elif avg_hot_flashes > 5:
        alerts.append("Frequent hot flashes - Lifestyle modifications may help")
    
    if mood_stability < 40:
        alerts.append("Significant mood instability detected - Mental health support recommended")
    
    if avg_sleep < 5:
        alerts.append("Severe sleep disruption (<5 hours) - Priority: Address sleep")
    elif avg_sleep < 6.5:
        alerts.append("Sleep disruption affecting recovery - Prioritize sleep hygiene")
    
    return alerts


def _get_recommendations(menopause_stage: str, symptoms: List[str]) -> List[str]:
    """Get tailored recommendations based on stage and symptoms."""
    if not symptoms:
        symptoms = []
    
    recs = []
    
    if "hot_flash" in symptoms:
        recs.append("Identify and avoid personal triggers (caffeine, spicy food, stress)")
    
    if "mood" in symptoms or "anxiety" in symptoms:
        recs.append("Consider counseling or mental health support")
    
    if "sleep" in symptoms:
        recs.append("Prioritize sleep hygiene and consistent bedtime routine")
    
    if menopause_stage == "perimenopause":
        recs.append("Track cycles and symptoms to monitor progression")
    elif menopause_stage in ("menopause", "postmenopause"):
        recs.append("Focus on long-term bone and cardiovascular health")
    elif menopause_stage == "insufficient_data":
        recs.append("Continue logging cycles to build a clearer picture of your stage")
    else:
        recs.append("Continue tracking your cycle to monitor for changes")
    
    return recs[:3]


def _build_vasomotor_tracker(
    health_logs: list,
    period: str,
    start_date: date,
    end_date: date
) -> Dict[str, Any]:
    """Build vasomotor tracker from health logs."""
    events = []
    total_events = 0
    total_severity = 0
    severity_distribution = defaultdict(int)
    triggers = defaultdict(int)
    times_of_day = defaultdict(int)
    
    hot_flash_events = 0
    hot_flash_severity_sum = 0
    night_sweat_events = 0
    night_sweat_severity_sum = 0
    
    for log in health_logs:
        symptoms = _normalize_symptoms(log.get("symptoms"))
        
        # Parse hot flashes
        if symptoms.get("hot_flash"):
            hot_flash_count = symptoms.get("hot_flash_count", 1)
            severity_map = {"mild": 3, "moderate": 6, "severe": 9}
            severity = severity_map.get(symptoms.get("hot_flash"), 5)
            
            for _ in range(int(hot_flash_count)):
                events.append(VasomotorEvent(
                    event_date=log.get("log_date"),
                    event_time=symptoms.get("hot_flash_time", "Unknown"),
                    event_type="hot_flash",
                    duration_minutes=int(symptoms.get("hot_flash_duration_min", 10)),
                    severity=severity,
                    trigger=symptoms.get("hot_flash_trigger"),
                    location=symptoms.get("hot_flash_location")
                ).model_dump())
                
                total_events += 1
                hot_flash_events += 1
                total_severity += severity
                hot_flash_severity_sum += severity
                
                # Track trigger
                trigger = symptoms.get("hot_flash_trigger", "unknown")
                triggers[trigger] += 1
                
                # Track time of day
                time_hour = symptoms.get("hot_flash_time", "Unknown")
                if time_hour and ":" in str(time_hour):
                    hour = int(str(time_hour).split(":")[0])
                    if 0 <= hour < 6:
                        times_of_day["3-6 AM"] += 1
                    elif 6 <= hour < 12:
                        times_of_day["6-12 PM"] += 1
                    elif 12 <= hour < 18:
                        times_of_day["12-6 PM"] += 1
                    else:
                        times_of_day["6-12 PM"] += 1
                else:
                    times_of_day["Unknown"] += 1
        
        # Parse night sweats
        if symptoms.get("night_sweat"):
            night_sweat_count = symptoms.get("night_sweat_count", 1)
            severity_map = {"mild": 2, "moderate": 5, "severe": 8}
            severity = severity_map.get(symptoms.get("night_sweat"), 4)
            
            night_sweat_events += int(night_sweat_count)
            night_sweat_severity_sum += severity * int(night_sweat_count)
    
    # Calculate averages
    days_in_period = max(1, (end_date - start_date).days)
    avg_daily_frequency = total_events / days_in_period if days_in_period > 0 else 0
    avg_severity = total_severity / max(1, total_events) if total_events > 0 else 0
    
    # Determine trend
    if len(health_logs) >= 2:
        def get_hot_flash_count(log):
            symptoms = log.get("symptoms") or {}
            if isinstance(symptoms, str):
                try:
                    symptoms = json.loads(symptoms)
                except (json.JSONDecodeError, TypeError):
                    return 0
            if isinstance(symptoms, dict):
                return symptoms.get("hot_flash_count", 0)
            return 0
        
        early_events = sum(1 for log in health_logs[:len(health_logs)//2] 
                          if get_hot_flash_count(log) > 0)
        late_events = sum(1 for log in health_logs[len(health_logs)//2:] 
                         if get_hot_flash_count(log) > 0)
        
        if late_events < early_events:
            trend = "improving"
            trend_desc = "Hot flashes decreasing over time"
        elif late_events > early_events:
            trend = "worsening"
            trend_desc = "Hot flashes increasing over time"
        else:
            trend = "stable"
            trend_desc = "Hot flashes remaining consistent"
    else:
        trend = "stable"
        trend_desc = "Insufficient data for trend analysis"
    
    # Build severity distribution
    severity_distribution["mild (1-3)"] = sum(1 for e in events if e["severity"] <= 3)
    severity_distribution["moderate (4-7)"] = sum(1 for e in events if 4 <= e["severity"] <= 7)
    severity_distribution["severe (8-10)"] = sum(1 for e in events if e["severity"] >= 8)
    
    # Format peak times
    peak_times = [{"time": time, "frequency": count} for time, count in sorted(
        times_of_day.items(), key=lambda x: x[1], reverse=True)[:3]]
    
    return {
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "total_events": total_events,
        "avg_daily_frequency": round(avg_daily_frequency, 2),
        "avg_severity": round(avg_severity, 1),
        "hot_flash_events": hot_flash_events,
        "hot_flash_avg_severity": round(hot_flash_severity_sum / max(1, hot_flash_events), 1),
        "night_sweat_events": night_sweat_events,
        "night_sweat_avg_severity": round(night_sweat_severity_sum / max(1, night_sweat_events), 1),
        "peak_times": peak_times,
        "common_triggers": dict(sorted(triggers.items(), key=lambda x: x[1], reverse=True)),
        "severity_distribution": dict(severity_distribution),
        "trend": trend,
        "trend_description": trend_desc,
        "events": events
    }


def _build_symptom_matrix(
    health_logs: list,
    period: str,
    start_date: date,
    end_date: date,
    terra_data: Optional[Dict[str, Any]] = None,
    user_id: Optional[int] = None
) -> Dict[str, Any]:
    """Build symptom matrix from health logs + Terra wearable data."""
    symptom_frequency = defaultdict(int)
    symptom_severity = defaultdict(lambda: defaultdict(int))
    entries = []
    
    for log in health_logs:
        entry = SymptomEntry(
            log_date=log.get("log_date"),
            mood=log.get("mood"),
            energy_level=log.get("energy_level")
        )
        
        symptoms = _normalize_symptoms(log.get("symptoms"))
        
        # Parse all symptoms
        for symptom, value in symptoms.items():
            if value and value != "none":
                symptom_frequency[symptom] += 1
                if isinstance(value, str):
                    symptom_severity[symptom][value] += 1
        
        # Set entry fields.
        # _normalize_symptoms() keys are derived from the exact logged text
        # (e.g. "Hot flashes" -> "hot_flashes", "Headache" -> "headache"), so
        # these must match that output rather than assumed singular/plural forms.
        entry.hot_flash = symptoms.get("hot_flashes") or symptoms.get("hot_flash")
        entry.hot_flash_count = symptoms.get("hot_flash_count")
        entry.night_sweat = symptoms.get("night_sweats") or symptoms.get("night_sweat")
        entry.sleep_disruption = "moderate" if symptoms.get("sleep_hours", 8) < 6 else "none"
        entry.sleep_hours = symptoms.get("sleep_hours")
        entry.brain_fog = symptoms.get("brain_fog")
        entry.joint_pain = symptoms.get("joint_pain")
        entry.vaginal_dryness = symptoms.get("vaginal_dryness")
        entry.weight_change_lbs = symptoms.get("weight_change_lbs")
        entry.headaches = symptoms.get("headache") or symptoms.get("headaches")
        entry.fatigue = symptoms.get("fatigue")
        
        entries.append(entry.model_dump())
    
    # Calculate frequencies
    days_in_period = max(1, (end_date - start_date).days)
    frequency_map = {symptom: count / max(1, len(health_logs)) 
                     for symptom, count in symptom_frequency.items()}
    
    # Calculate severity averages
    severity_map = {}
    for symptom, severity_counts in symptom_severity.items():
        if severity_counts:
            most_common = max(severity_counts, key=severity_counts.get)
            severity_map[symptom] = most_common
    
    # Generate symptom matrix insights (3 primary perimenopause correlations)
    symptom_insights = []
    if user_id:
        symptom_insights = _generate_symptom_matrix_insights(
            user_id, start_date, end_date, health_logs, terra_data
        )
    
    # Calculate mood stability (mood is stored as emoji, not English words)
    moods = []
    for log in health_logs:
        if log.get("mood"):
            mood_score = MOOD_EMOJI_SCORES.get(log.get("mood"), 5)
            moods.append(mood_score)
    mood_stability = int((sum(moods) / len(moods) / 10 * 100)) if moods else 50
    
    # Calculate energy
    energy_map = {"Very Low": 10, "Low": 30, "Moderate": 50, "High": 70, "Very High": 90}
    energy_scores = [energy_map.get(log.get("energy_level"), 50) for log in health_logs if log.get("energy_level")]
    avg_energy = int(sum(energy_scores) / len(energy_scores)) if energy_scores else 50
    
    # Calculate sleep - prefer Terra wearable data, fallback to health_logs
    avg_sleep = None
    
    # First try Terra data (wearable)
    if terra_data and terra_data.get("has_data") and terra_data.get("avg_sleep_hours") is not None:
        avg_sleep = terra_data["avg_sleep_hours"]
    
    # Fallback to health_logs if no Terra data
    if avg_sleep is None:
        sleep_hours = []
        for log in health_logs:
            symptoms = _normalize_symptoms(log.get("symptoms"))
            if symptoms.get("sleep_hours"):
                sleep_hours.append(symptoms.get("sleep_hours"))
        avg_sleep = sum(sleep_hours) / len(sleep_hours) if sleep_hours else None
    
    # Only use default if no data from any source
    if avg_sleep is None:
        avg_sleep = 7  # default fallback
    
    return {
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "entries": entries,
        "symptom_frequency": dict(frequency_map),
        "symptom_severity": dict(severity_map),
        "symptom_matrix_insights": symptom_insights,
        "most_common_symptoms": [s[0] for s in sorted(
            frequency_map.items(), key=lambda x: x[1], reverse=True)[:5]],
        "avg_energy_level_percent": avg_energy,
        "avg_sleep_hours": round(avg_sleep, 1),
        "avg_mood_stability_percent": mood_stability,
        "symptom_trends": {}
    }


def _calculate_gsm_health(health_logs: list) -> Dict[str, Dict]:
    """
    Calculate GSM (Genitourinary Syndrome of Menopause) health metrics from actual health logs.
    
    Extracts: vaginal_dryness, urinary_frequency, pelvic_discomfort, libido_impact
    from symptoms JSON instead of using hardcoded values.
    
    Handles both formats:
    - Dict format: {"vaginal_dryness": "moderate", ...}
    - List format: ["Symptom 1", "Symptom 2", ...] (returns not_reported)
    """
    gsm_fields = {
        "vaginal_dryness": [],
        "urinary_frequency": [],
        "pelvic_discomfort": [],
        "libido_impact": []
    }
    
    # Parse symptoms from all logs
    for log in health_logs:
        symptoms = _normalize_symptoms(log.get("symptoms"))
        
        for field in gsm_fields.keys():
            if symptoms.get(field):
                gsm_fields[field].append(symptoms.get(field))
    
    # Calculate aggregates for each GSM symptom
    gsm_health = {}
    severity_map = {"none": 0, "mild": 3, "moderate": 5, "severe": 8}
    
    for field, values in gsm_fields.items():
        if not values:
            # No data reported - return neutral
            gsm_health[field] = {
                "level": "not_reported",
                "value": 0,
                "percentage": 0
            }
        else:
            # Find most common severity level
            severity_counts = defaultdict(int)
            for val in values:
                severity_counts[val] += 1
            
            most_common = max(severity_counts, key=severity_counts.get)
            value = severity_map.get(most_common, 0)
            percentage = int((value / 10) * 100)  # Convert to percentage
            
            gsm_health[field] = {
                "level": most_common,
                "value": value,
                "percentage": percentage
            }
    
    return gsm_health


def _generate_correlation_descriptions_llm(correlations: List[Dict]) -> List[Dict]:
    """
    Use LLM to generate personalized, insightful descriptions for symptom correlations.
    Falls back to static descriptions if LLM fails.
    """
    if not correlations:
        return correlations
    
    try:
        from ai.utils.llm_call import llm_call
        
        # Build correlation summary for LLM
        correlation_summary = "\n".join([
            f"- {c['from']} ↔ {c['to']}: {c['percentage']}% co-occurrence"
            for c in correlations
        ])
        
        prompt = f"""You are a perimenopause health insights assistant. Generate short, helpful descriptions for these symptom correlations.

Correlations found in user's health logs:
{correlation_summary}

For each correlation, write a brief 1-line description (max 15 words) explaining:
- What this pattern might mean for the user
- Use empathetic, supportive tone
- Focus on perimenopause context

Return ONLY a valid JSON array with this exact structure (no markdown, no extra text):
[
  {{"from": "Symptom1", "to": "Symptom2", "description": "Your brief insight here."}}
]

Important: Return descriptions for ALL {len(correlations)} correlations in the same order."""

        response = llm_call(prompt, max_tokens=500, temperature=0.7)
        
        # Parse LLM response
        # Handle potential markdown code blocks
        response = response.strip()
        if response.startswith("```"):
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
        response = response.strip()
        
        llm_descriptions = json.loads(response)
        
        # Update correlations with LLM descriptions
        if isinstance(llm_descriptions, list) and len(llm_descriptions) == len(correlations):
            for i, desc_item in enumerate(llm_descriptions):
                if isinstance(desc_item, dict) and "description" in desc_item:
                    correlations[i]["description"] = desc_item["description"]
        
        return correlations
        
    except Exception as e:
        # Fallback: keep existing static descriptions
        import logging
        logging.warning(f"LLM correlation description failed, using static: {e}")
        return correlations


def _generate_insight_description_llm(insight_type: str, stats: Dict[str, Any]) -> str:
    """
    Generate personalized one-liner insight description using Claude LLM.
    
    Args:
        insight_type: One of 'hot_flash_sleep', 'sleep_mood', 'hot_flash_mood'
        stats: Dictionary with calculated statistics for the insight
    
    Returns:
        Personalized one-liner description string
    """
    try:
        from ai.utils.llm_call import llm_call
        
        if insight_type == "hot_flash_sleep":
            prompt = f"""Generate a single personalized insight sentence (max 20 words) about hot flashes affecting sleep.

User's data:
- Hot flash days correlate with {stats.get('reduction_pct', 0)}% reduction in sleep duration
- Average sleep on hot flash days: {stats.get('avg_sleep_hf', 0)}hrs
- Average sleep on normal days: {stats.get('avg_sleep_no_hf', 7)}hrs
- Correlation strength: {stats.get('correlation_pct', 0)}%

Write ONE short, empathetic sentence like: "Hot flash episodes after 10pm directly correlate with 47% reduction in deep sleep duration."
Return ONLY the sentence, no quotes, no explanation."""

        elif insight_type == "sleep_mood":
            prompt = f"""Generate a single personalized insight sentence (max 20 words) about sleep affecting mood.

User's data:
- Poor sleep (<6hrs) leads to {stats.get('mood_drop_pct', 0)}% mood drop next day
- Days with poor sleep analyzed: {stats.get('poor_sleep_days', 0)}
- Correlation strength: {stats.get('correlation_pct', 0)}%

Write ONE short, empathetic sentence like: "Under 6hrs sleep raises irritability and anxiety scores by 34% the following day."
Return ONLY the sentence, no quotes, no explanation."""

        elif insight_type == "hot_flash_mood":
            prompt = f"""Generate a single personalized insight sentence (max 20 words) about hot flashes affecting mood.

User's data:
- Days with 5+ hot flash episodes show mood disruption in {stats.get('disruption_pct', 0)}% of entries
- High hot flash days analyzed: {stats.get('high_hf_days', 0)}
- Correlation strength: {stats.get('correlation_pct', 0)}%

Write ONE short, empathetic sentence like: "Days with 5+ episodes show elevated mood disruption in 83% of logged entries."
Return ONLY the sentence, no quotes, no explanation."""
        
        else:
            return "Correlation detected in your health data."
        
        response = llm_call(prompt, max_tokens=100, temperature=0.7)
        
        # Clean up response
        if response:
            response = response.strip().strip('"').strip("'")
            if len(response) > 10:
                return response
        
        # Fallback descriptions if LLM fails
        fallbacks = {
            "hot_flash_sleep": f"Hot flash episodes correlate with {stats.get('reduction_pct', 0)}% reduction in your sleep duration.",
            "sleep_mood": f"Under 6hrs sleep raises your irritability scores by {stats.get('mood_drop_pct', 0)}% the following day.",
            "hot_flash_mood": f"Days with 5+ episodes show mood disruption in {stats.get('disruption_pct', 0)}% of your entries."
        }
        return fallbacks.get(insight_type, "Correlation detected in your health data.")
        
    except Exception as e:
        print(f"[ERROR] _generate_insight_description_llm failed: {e}")
        # Return simple fallback on error
        fallbacks = {
            "hot_flash_sleep": f"Hot flash episodes correlate with {stats.get('reduction_pct', 0)}% reduction in your sleep duration.",
            "sleep_mood": f"Under 6hrs sleep raises your irritability scores by {stats.get('mood_drop_pct', 0)}% the following day.",
            "hot_flash_mood": f"Days with 5+ episodes show mood disruption in {stats.get('disruption_pct', 0)}% of your entries."
        }
        return fallbacks.get(insight_type, "Correlation detected in your health data.")


def _generate_symptom_matrix_insights(
    user_id: int, 
    start_date: date, 
    end_date: date, 
    health_logs: list,
    terra_data: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Generate the 3 primary perimenopause insight cards for UI.
    
    Cards:
    1. Hot Flashes → Sleep - correlation between hot flash timing and sleep quality
    2. Sleep → Mood - correlation between sleep duration and next-day mood
    3. Hot Flashes → Mood - correlation between hot flash days and mood disruption
    
    Returns insights ONLY when sufficient real data exists.
    Returns empty list when data is insufficient - NO fallbacks.
    Uses Claude LLM for personalized one-liner descriptions.
    """
    from ai.utils.db import get_connection
    
    insights = []
    MIN_DATA_POINTS = 3  # Minimum days of overlapping data for insights
    
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Fetch vasomotor_logs for hot flash data
            cursor.execute("""
                SELECT log_date, total_episodes, mild_count, moderate_count, 
                       intense_count, avg_intensity, peak_time
                FROM vasomotor_logs
                WHERE user_id = %s AND log_date >= %s AND log_date <= %s
                ORDER BY log_date ASC
            """, (user_id, start_date, end_date))
            vasomotor_logs = cursor.fetchall()
            
            # Fetch Terra sleep data with daily breakdown
            cursor.execute("""
                SELECT payload, DATE(created_at) as log_date
                FROM terra_activity_data
                WHERE user_id = %s 
                  AND type = 'sleep'
                  AND created_at >= %s 
                  AND created_at <= %s
                ORDER BY created_at ASC
            """, (user_id, start_date.isoformat(), (end_date + timedelta(days=1)).isoformat()))
            terra_sleep_rows = cursor.fetchall()
            
            # Parse Terra sleep data into daily dict
            sleep_by_date = {}
            for row in terra_sleep_rows:
                try:
                    payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
                    sleep_hours = None
                    sleep_quality = None
                    
                    if payload.get("sleep"):
                        sleep_hours = payload["sleep"].get("hours")
                        sleep_quality = payload["sleep"].get("quality")
                    
                    if sleep_hours is None:
                        data_list = payload.get("data", [])
                        if data_list and isinstance(data_list, list):
                            for item in data_list:
                                scores = item.get("scores", {})
                                if scores.get("sleep") is not None:
                                    sleep_hours = float(scores["sleep"])
                    
                    if sleep_hours is not None:
                        sleep_by_date[row["log_date"]] = {
                            "hours": sleep_hours,
                            "quality": sleep_quality
                        }
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
            
            # Parse health_logs into daily dict for mood
            mood_by_date = {}
            for log in health_logs:
                log_date = log.get("log_date")
                mood = log.get("mood")
                if log_date and mood:
                    mood_score = MOOD_EMOJI_SCORES.get(mood, 5)
                    mood_by_date[log_date] = {
                        "mood": mood,
                        "score": mood_score,
                        "energy": log.get("energy_level")
                    }
            
            # Parse vasomotor_logs into daily dict
            hotflash_by_date = {}
            for vlog in vasomotor_logs:
                log_date = vlog.get("log_date")
                if log_date:
                    hotflash_by_date[log_date] = {
                        "episodes": vlog.get("total_episodes", 0),
                        "intensity": float(vlog.get("avg_intensity", 0) or 0),
                        "peak_time": vlog.get("peak_time")
                    }
            
            # Calculate insights - only add if data exists
            hf_sleep = _calculate_hotflash_sleep_insight(hotflash_by_date, sleep_by_date, MIN_DATA_POINTS)
            if hf_sleep:
                insights.append(hf_sleep)
            
            sleep_mood = _calculate_sleep_mood_insight(sleep_by_date, mood_by_date, MIN_DATA_POINTS)
            if sleep_mood:
                insights.append(sleep_mood)
            
            hf_mood = _calculate_hotflash_mood_insight(hotflash_by_date, mood_by_date, MIN_DATA_POINTS)
            if hf_mood:
                insights.append(hf_mood)
            
    except Exception as e:
        print(f"[ERROR] _generate_symptom_matrix_insights failed: {e}")
        return []  # Return empty on error - no fallbacks
    
    return insights


def _calculate_hotflash_sleep_insight(
    hotflash_by_date: Dict, 
    sleep_by_date: Dict, 
    min_points: int
) -> Optional[Dict[str, Any]]:
    """Calculate Hot Flashes → Sleep correlation insight. Returns None if insufficient data."""
    
    overlapping_dates = set(hotflash_by_date.keys()) & set(sleep_by_date.keys())
    
    if len(overlapping_dates) < min_points:
        return None  # No fallback - insufficient data
    
    days_with_hf = 0
    days_hf_poor_sleep = 0
    total_sleep_hf_days = 0
    total_sleep_no_hf_days = 0
    count_hf_days = 0
    count_no_hf_days = 0
    
    for dt in overlapping_dates:
        hf = hotflash_by_date[dt]
        sleep = sleep_by_date[dt]
        has_hot_flashes = hf.get("episodes", 0) > 0
        sleep_hours = sleep.get("hours", 7)
        
        if has_hot_flashes:
            days_with_hf += 1
            total_sleep_hf_days += sleep_hours
            count_hf_days += 1
            if sleep_hours < 6:
                days_hf_poor_sleep += 1
        else:
            total_sleep_no_hf_days += sleep_hours
            count_no_hf_days += 1
    
    if days_with_hf == 0:
        return None  # No hot flash data
    
    correlation_pct = min(95, int((days_hf_poor_sleep / days_with_hf) * 100) + 40)
    avg_sleep_hf = round(total_sleep_hf_days / count_hf_days, 1) if count_hf_days > 0 else 0
    avg_sleep_no_hf = round(total_sleep_no_hf_days / count_no_hf_days, 1) if count_no_hf_days > 0 else 7
    
    reduction_pct = 0
    if avg_sleep_no_hf > 0 and avg_sleep_hf < avg_sleep_no_hf:
        reduction_pct = int(((avg_sleep_no_hf - avg_sleep_hf) / avg_sleep_no_hf) * 100)
    
    # Generate personalized description via LLM
    description = _generate_insight_description_llm(
        insight_type="hot_flash_sleep",
        stats={
            "correlation_pct": correlation_pct,
            "reduction_pct": reduction_pct,
            "avg_sleep_hf": avg_sleep_hf,
            "avg_sleep_no_hf": avg_sleep_no_hf,
            "days_analyzed": len(overlapping_dates)
        }
    )
    
    return {
        "title": "Hot Flashes → Sleep",
        "percentage": correlation_pct,
        "description": description
    }


def _calculate_sleep_mood_insight(
    sleep_by_date: Dict, 
    mood_by_date: Dict, 
    min_points: int
) -> Optional[Dict[str, Any]]:
    """Calculate Sleep → Mood correlation insight. Returns None if insufficient data."""
    
    sleep_dates = set(sleep_by_date.keys())
    mood_dates = set(mood_by_date.keys())
    
    poor_sleep_poor_mood = 0
    poor_sleep_days = 0
    good_sleep_days = 0
    poor_sleep_mood_total = 0
    good_sleep_mood_total = 0
    
    for mood_date in mood_dates:
        if isinstance(mood_date, date):
            prev_date = mood_date - timedelta(days=1)
        else:
            prev_date = mood_date
            
        if prev_date in sleep_dates:
            sleep_hours = sleep_by_date[prev_date].get("hours", 7)
            mood_score = mood_by_date[mood_date].get("score", 5)
            
            if sleep_hours < 6:
                poor_sleep_days += 1
                poor_sleep_mood_total += mood_score
                if mood_score <= 5:
                    poor_sleep_poor_mood += 1
            else:
                good_sleep_days += 1
                good_sleep_mood_total += mood_score
    
    total_correlations = poor_sleep_days + good_sleep_days
    
    if total_correlations < min_points or poor_sleep_days == 0:
        return None  # No fallback - insufficient data
    
    correlation_pct = min(95, int((poor_sleep_poor_mood / poor_sleep_days) * 100) + 20)
    avg_mood_poor_sleep = round(poor_sleep_mood_total / poor_sleep_days, 1) if poor_sleep_days > 0 else 5
    avg_mood_good_sleep = round(good_sleep_mood_total / good_sleep_days, 1) if good_sleep_days > 0 else 7
    
    mood_drop_pct = 0
    if avg_mood_good_sleep > 0 and avg_mood_poor_sleep < avg_mood_good_sleep:
        mood_drop_pct = int(((avg_mood_good_sleep - avg_mood_poor_sleep) / avg_mood_good_sleep) * 100)
    
    # Generate personalized description via LLM
    description = _generate_insight_description_llm(
        insight_type="sleep_mood",
        stats={
            "correlation_pct": correlation_pct,
            "mood_drop_pct": mood_drop_pct,
            "poor_sleep_days": poor_sleep_days,
            "days_analyzed": total_correlations
        }
    )
    
    return {
        "title": "Sleep → Mood",
        "percentage": correlation_pct,
        "description": description
    }


def _calculate_hotflash_mood_insight(
    hotflash_by_date: Dict, 
    mood_by_date: Dict, 
    min_points: int
) -> Optional[Dict[str, Any]]:
    """Calculate Hot Flashes → Mood correlation insight. Returns None if insufficient data."""
    
    overlapping_dates = set(hotflash_by_date.keys()) & set(mood_by_date.keys())
    
    if len(overlapping_dates) < min_points:
        return None  # No fallback - insufficient data
    
    high_hf_days = 0
    high_hf_poor_mood = 0
    low_hf_days = 0
    
    for dt in overlapping_dates:
        hf = hotflash_by_date[dt]
        mood = mood_by_date[dt]
        episodes = hf.get("episodes", 0)
        mood_score = mood.get("score", 5)
        
        if episodes >= 5:
            high_hf_days += 1
            if mood_score <= 5:
                high_hf_poor_mood += 1
        else:
            low_hf_days += 1
    
    if high_hf_days == 0:
        return None  # No high hot flash days to analyze
    
    correlation_pct = min(95, int((high_hf_poor_mood / high_hf_days) * 100) + 25)
    disruption_pct = int((high_hf_poor_mood / high_hf_days) * 100)
    
    # Generate personalized description via LLM
    description = _generate_insight_description_llm(
        insight_type="hot_flash_mood",
        stats={
            "correlation_pct": correlation_pct,
            "disruption_pct": disruption_pct,
            "high_hf_days": high_hf_days,
            "days_analyzed": len(overlapping_dates)
        }
    )
    
    return {
        "title": "Hot Flashes → Mood",
        "percentage": correlation_pct,
        "description": description
    }


def _calculate_symptom_correlations(health_logs: list) -> List[Dict]:
    """Calculate symptom correlations with percentages and descriptions."""
    from collections import defaultdict
    
    co_occurrences = defaultdict(lambda: defaultdict(int))
    total_days = len(health_logs) if health_logs else 1
    
    for log in health_logs:
        symptoms_present = []
        
        if log.get("mood"):
            symptoms_present.append("mood")
        
        # energy_level is a separate health_logs column, not part of the symptoms
        # JSON, but is still a trackable per-day signal for correlations
        if log.get("energy_level"):
            symptoms_present.append("energy_level")
        
        symptoms = _normalize_symptoms(log.get("symptoms"))
        
        for symptom, value in symptoms.items():
            if value and value not in ["none", "None", 0]:
                symptoms_present.append(symptom)
        
        # Sleep disruption is inferred, not a literal symptom key, so add it
        # separately when sleep_hours indicates disrupted sleep
        if symptoms.get("sleep_hours") is not None and symptoms.get("sleep_hours") < 6:
            symptoms_present.append("sleep_disruption")
        
        # Track co-occurrences
        for i, s1 in enumerate(symptoms_present):
            for s2 in symptoms_present[i+1:]:
                co_occurrences[s1][s2] += 1
    
    # Format as correlation list with percentages.
    # Keys must match the snake_case keys _normalize_symptoms() actually produces
    # from logged symptom text (e.g. "Hot flashes" -> "hot_flashes", plural "s"
    # included) - the previous singular keys here never matched real data.
    correlations = []
    
    # Static fallback descriptions (used if LLM fails)
    correlation_descriptions = {
        ("hot_flashes", "sleep_disruption"): "Hot flash episodes directly correlate with {pct}% reduction in deep sleep duration.",
        ("sleep_disruption", "mood"): "Sleep disruption raises irritability and mood changes in {pct}% of logged entries.",
        ("hot_flashes", "mood"): "Days with hot flashes show elevated mood disruption in {pct}% of logged entries.",
        ("night_sweats", "sleep_disruption"): "Night sweats interrupt sleep with {pct}% co-occurrence with sleep disruption.",
        ("vaginal_dryness", "libido_impact"): "Vaginal dryness correlates with {pct}% reported libido impact.",
        ("fatigue", "energy_level"): "High fatigue scores correspond to {pct}% energy level reduction."
    }
    
    for symptom1, cooccurrs in co_occurrences.items():
        for symptom2, count in cooccurrs.items():
            if count > 0:
                percentage = int((count / total_days) * 100) if total_days > 0 else 0
                
                # Find static description as fallback
                desc = None
                for (s1, s2), desc_template in correlation_descriptions.items():
                    if (symptom1 == s1 and symptom2 == s2) or (symptom1 == s2 and symptom2 == s1):
                        desc = desc_template.format(pct=percentage)
                        break
                
                if desc is None:
                    desc = f"{symptom1.replace('_', ' ').title()} and {symptom2.replace('_', ' ').title()} occur together."
                
                correlations.append({
                    "from": symptom1.replace('_', ' ').title(),
                    "to": symptom2.replace('_', ' ').title(),
                    "percentage": min(percentage, 100),
                    "description": desc
                })
    
    # Sort by percentage descending and return top correlations
    correlations = sorted(correlations, key=lambda x: x["percentage"], reverse=True)[:5]
    
    # Generate LLM-based descriptions (replaces static if successful)
    correlations = _generate_correlation_descriptions_llm(correlations)
    
    return correlations
