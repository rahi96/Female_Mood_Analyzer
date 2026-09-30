"""Perimenopause & Menopause API service with business logic."""

from datetime import datetime, date, timedelta
from typing import Any, Dict, Optional, List
import json
from collections import defaultdict

from ai.models.perimenopause_models import (
    MenopauseSummary, VasomotorTracker, VasomotorEvent, SymptomMatrix, 
    SymptomEntry, ClinicalExport, PerimenopauseInsights
)


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

def _empty_dashboard(user_id: int, period: str) -> Dict[str, Any]:
    """Honest empty-state dashboard for users with no data (or who don't exist yet).

    Matches the same top-level shape the UI always expects, instead of an
    ad-hoc {"status": "error", ...} dict that omits every field the frontend
    depends on (transition_stage_tracker, vasomotor_tracker, etc.) and would
    otherwise be returned with a misleading HTTP 200.
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
    }


def get_perimenopause_dashboard(user_id: int, period: str = "7d") -> Dict[str, Any]:
    """
    Get complete perimenopause dashboard - UNIFIED endpoint for UI page with 3 tabs.
    
    Returns all data needed for:
    - Tab 1 (Symptoms): Vasomotor tracker + GSM health
    - Tab 2 (Insights): Symptom matrix with correlations
    - Tab 3 (Export): Clinical export data
    
    Frontend handles tab switching by showing/hiding sections.
    """
    try:
        # Get all three data sections
        summary = get_menopause_summary(user_id)
        if summary.get("status") == "error":
            # User doesn't exist or has no profile yet - return an honest empty
            # dashboard with the correct shape instead of a raw error dict that
            # silently omits every field the UI expects.
            return _empty_dashboard(user_id, period)
        
        # Get insights (vasomotor + symptoms matrix)
        insights = get_perimenopause_insights(user_id, period, include=["vasomotor", "symptoms"])
        if insights.get("status") == "error":
            return _empty_dashboard(user_id, period)
        
        # Get clinical export data (for Export tab)
        from ai.utils.db import get_connection
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Get start/end dates for clinical export
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
            
            # Fetch all health_logs for this period (needed for GSM health calculation)
            cursor.execute("""
                SELECT log_date, mood, energy_level, symptoms, notes
                FROM health_logs
                WHERE user_id = %s AND log_date >= %s AND log_date <= %s
                ORDER BY log_date ASC
            """, (user_id, start_date, end_date))
            health_logs = cursor.fetchall()
        
        # Ensure start_date is not None before calling isoformat()
        start_date_str = start_date.isoformat() if start_date else date.today().isoformat()
        end_date_str = end_date.isoformat()
        clinical_export = get_clinical_export(user_id, start_date_str, end_date_str)
        if clinical_export.get("status") == "error":
            clinical_export = None
        
        # Combine everything into one dashboard response
        dashboard = {
            # Tab 1: Symptoms (Vasomotor Tracker + GSM Health)
            "transition_stage_tracker": {
                "menopause_stage": summary.get("menopause_stage"),
                "is_in_perimenopause": summary.get("is_in_perimenopause"),
                "months_since_last_period": summary.get("months_since_last_period"),
                "last_period_date": summary.get("last_period_date"),
                "cycle_status": summary.get("cycle_status")
            },
            
            # Tab 1: Vasomotor Tracker
            "vasomotor_tracker": insights.get("vasomotor_tracker"),
            
            # Tab 1: GSM Health (Intimate & Urinary Health) - calculated from user data
            "gsm_health": _calculate_gsm_health([
                log for log in health_logs 
                if start_date <= log.get("log_date") <= end_date
            ]),
            
            # Tab 2: Symptom Matrix with Correlations
            "symptom_matrix": insights.get("symptom_matrix"),
            
            # Tab 3: Clinical Export Data
            "clinical_export": clinical_export,
            
            # Metadata
            "period_selected": period,
            "tabs": ["Symptoms", "Insights", "Export"]
        }
        
        return dashboard
    
    except Exception as e:
        print(f"[ERROR] get_perimenopause_dashboard failed for user {user_id}: {e}")
        return {"status": "error", "message": str(e), "user_id": user_id}


def get_menopause_summary(user_id: int) -> Dict[str, Any]:
    """Get quick menopause status overview - UI Dashboard view."""
    try:
        from ai.utils.db import get_connection, get_user_profile
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Verify user is in perimenopause life stage
            profile = get_user_profile(user_id)
            if not profile:
                return {"status": "error", "message": "User not found"}
            
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
            
            return MenopauseSummary(
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
            
            result = {"summary": summary}
            
            # Build vasomotor tracker if requested
            if "vasomotor" in include:
                vasomotor = _build_vasomotor_tracker(health_logs, period, start_date, end_date)
                result["vasomotor_tracker"] = vasomotor
            
            # Build symptom matrix if requested
            if "symptoms" in include:
                symptom_matrix = _build_symptom_matrix(health_logs, period, start_date, end_date)
                result["symptom_matrix"] = symptom_matrix
            
            return result
    
    except Exception as e:
        print(f"[ERROR] get_perimenopause_insights failed for user {user_id}: {e}")
        return {"status": "error", "message": str(e), "user_id": user_id}


def get_clinical_export(
    user_id: int,
    start_date: str,
    end_date: str
) -> Dict[str, Any]:
    """Get clinical export ready for sharing with healthcare provider."""
    try:
        from ai.utils.db import get_connection, get_user_profile
        from ai.utils.llm_call import llm_call
        
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
            
            # Get vasomotor data
            vasomotor = _build_vasomotor_tracker(health_logs, "custom", start, end)
            
            # Get symptom data
            symptom_matrix = _build_symptom_matrix(health_logs, "custom", start, end)
            
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
            
            # Calculate sleep quality
            sleep_hours = []
            sleep_quality_scores = []
            for log in health_logs:
                symptoms = _normalize_symptoms(log.get("symptoms"))
                if symptoms.get("sleep_hours"):
                    sleep_hours.append(symptoms.get("sleep_hours"))
                if symptoms.get("sleep_quality"):
                    sq_map = {"poor": 1, "fair": 2, "good": 3, "excellent": 4}
                    sleep_quality_scores.append(sq_map.get(symptoms.get("sleep_quality"), 2))
            
            avg_sleep_hours = sum(sleep_hours) / len(sleep_hours) if sleep_hours else 7
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
            
            return ClinicalExport(
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
    
    except Exception as e:
        print(f"[ERROR] get_clinical_export failed for user {user_id}: {e}")
        return {"status": "error", "message": str(e), "user_id": user_id}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

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
        
        for biomarker in needs_attention:
            if biomarker.get("name", "").upper() == "FSH":
                return biomarker.get("value"), "elevated"
        
        for biomarker in normal_results:
            if biomarker.get("name", "").upper() == "FSH":
                return biomarker.get("value"), "normal"
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass
    
    return None, None


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
    end_date: date
) -> Dict[str, Any]:
    """Build symptom matrix from health logs."""
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
    
    # Extract correlations
    correlations = _calculate_symptom_correlations(health_logs)
    
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
    
    # Calculate sleep
    sleep_hours = []
    for log in health_logs:
        symptoms = _normalize_symptoms(log.get("symptoms"))
        
        if symptoms.get("sleep_hours"):
            sleep_hours.append(symptoms.get("sleep_hours"))
    avg_sleep = sum(sleep_hours) / len(sleep_hours) if sleep_hours else 7
    
    return {
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "entries": entries,
        "symptom_frequency": dict(frequency_map),
        "symptom_severity": dict(severity_map),
        "symptom_correlations": correlations,
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
                
                # Find description
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
    
    return correlations
