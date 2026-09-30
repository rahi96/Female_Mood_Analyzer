"""Pregnancy & Postpartum API service with business logic."""

from datetime import datetime, timedelta, date
from typing import Any, Dict, Optional
from pymysql.cursors import DictCursor
from fastapi import HTTPException

from ai.models.pregnancy_models import (
    PregnancySummary, PregnancyAlert, PregnancyMilestones, ClinicalTest,
    PostpartumRecovery, RecoveryMetrics, MentalHealth, PostpartumAlert,
    SupportGroup, SupportGroupResponse
)


# ============================================================================
# VALIDATION HELPER FUNCTIONS
# ============================================================================

def _validate_pregnancy_start_date(pregnancy_start: date, user_id: int) -> None:
    """
    Validate that pregnancy start date is not in the future.
    
    Args:
        pregnancy_start: The pregnancy start date to validate
        user_id: User ID for error messages
        
    Raises:
        HTTPException: 400 Bad Request if date is in the future
    """
    if isinstance(pregnancy_start, str):
        pregnancy_start = datetime.strptime(pregnancy_start, "%Y-%m-%d").date()
    
    current_date = date.today()
    if pregnancy_start > current_date:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid pregnancy start date: {pregnancy_start} is in the future. "
                   f"Pregnancy cannot start in the future (today is {current_date})."
        )


def _has_pregnancy_data(user_id: int) -> bool:
    """
    Check if user has active pregnancy data (NEW or OLD tables).
    
    This allows users to access pregnancy endpoints if they have an active pregnancy record,
    regardless of their current life_stage_id setting.
    
    Checks both:
    - NEW table: user_pregnancies (status = 'active')
    - OLD table: menstrual_cycles (is_completed = 0)
    
    Args:
        user_id: User ID to check
        
    Returns:
        True if user has active pregnancy, False otherwise
    """
    from ai.utils.db import get_connection
    
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Check NEW table: user_pregnancies
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM user_pregnancies
            WHERE user_id = %s AND status = 'active'
            LIMIT 1
        """, (user_id,))
        result = cursor.fetchone()
        if result and result.get("count", 0) > 0:
            return True
        
        # Check OLD table: menstrual_cycles (backward compatibility)
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM menstrual_cycles
            WHERE user_id = %s AND is_completed = 0 AND period_start_date IS NOT NULL
            LIMIT 1
        """, (user_id,))
        result = cursor.fetchone()
        return result.get("count", 0) > 0 if result else False


def _has_postpartum_data(user_id: int) -> bool:
    """
    Check if user has postpartum data (completed pregnancy with delivery date).
    
    Checks both NEW and OLD tables:
    - NEW: postpartum_recoveries table (has delivery_date)
    - OLD: user_pregnancies (status='completed') or menstrual_cycles (is_completed=1)
    
    Args:
        user_id: User ID to check
        
    Returns:
        True if user has completed pregnancy with delivery date, False otherwise
    """
    from ai.utils.db import get_connection
    
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Check NEW table: postpartum_recoveries (most reliable)
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM postpartum_recoveries
            WHERE user_id = %s AND delivery_date IS NOT NULL
            LIMIT 1
        """, (user_id,))
        result = cursor.fetchone()
        if result and result.get("count", 0) > 0:
            return True
        
        # Check NEW table: user_pregnancies
        cursor.execute("""
            SELECT last_menstrual_period_date, delivery_date
            FROM user_pregnancies
            WHERE user_id = %s 
            AND status = 'completed'
            AND delivery_date IS NOT NULL
            LIMIT 1
        """, (user_id,))
        pregnancy = cursor.fetchone()
        
        if pregnancy and pregnancy.get("delivery_date"):
            return True
        
        # Check OLD table: menstrual_cycles (backward compatibility)
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM menstrual_cycles
            WHERE user_id = %s AND is_completed = 1 AND period_end_date IS NOT NULL
            LIMIT 1
        """, (user_id,))
        result = cursor.fetchone()
        return result.get("count", 0) > 0 if result else False


def _check_miscarriage_history(user_id: int) -> bool:
    """
    Check if user has a miscarriage record in user_pregnancies.
    
    Checks the status field for 'miscarriage' status.
    
    Args:
        user_id: User ID to check
        
    Returns:
        True if miscarriage history found, False otherwise
    """
    from ai.utils.db import get_connection
    
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT status FROM user_pregnancies
                WHERE user_id = %s AND status = 'miscarriage'
                LIMIT 1
            """, (user_id,))
            
            result = cursor.fetchone()
            return result is not None
    except Exception:
        return False


def _get_pregnancy_status(current_week: int, pregnancy_status: str, has_delivered: bool) -> Dict[str, Any]:
    """
    Determine pregnancy journey status and required confirmations.
    
    Args:
        current_week: Current pregnancy week
        pregnancy_status: Status from user_pregnancies table ('active', 'completed', 'miscarriage')
        has_delivered: Whether delivery_date is set (even if not yet confirmed)
        
    Returns:
        Dict with pregnancy_status, requires_confirmation, confirmation_needed_for, confirmation_message
    """
    # Case 1: Miscarriage status recorded
    if pregnancy_status == "miscarriage":
        return {
            "pregnancy_status": "pregnancy_with_loss",
            "requires_confirmation": True,
            "confirmation_needed_for": "miscarriage",
            "confirmation_message": "Have you experienced a miscarriage?"
        }
    
    # Case 2: Completed pregnancy with delivery date
    if pregnancy_status == "completed" and has_delivered:
        return {
            "pregnancy_status": "postpartum",
            "requires_confirmation": False,
            "confirmation_needed_for": None,
            "confirmation_message": None
        }
    
    # Case 3: Completed pregnancy but no delivery date yet, and reached 40 weeks
    if pregnancy_status == "completed" and not has_delivered and current_week >= 40:
        return {
            "pregnancy_status": "postpartum_ready",
            "requires_confirmation": True,
            "confirmation_needed_for": "delivery",
            "confirmation_message": "Have you recently completed your pregnancy?"
        }
    
    # Case 4: Normal active pregnancy (< 40 weeks, no miscarriage)
    return {
        "pregnancy_status": "active_pregnancy",
        "requires_confirmation": False,
        "confirmation_needed_for": None,
        "confirmation_message": None
    }


def _get_next_5_clinical_tests(current_week: int) -> list:
    """
    Get the next 5 major clinical tests for the current pregnancy week.
    
    Args:
        current_week: Current pregnancy week (0-40)
        
    Returns:
        List of next 5 clinical tests with name, week, and date
    """
    # All clinical tests in order
    all_tests = [
        {"name": "Baseline Visit", "week": 0, "display_week": "W0"},
        {"name": "Confirm Pregnancy", "week": 8, "display_week": "W8"},
        {"name": "Ultrasound", "week": 8, "display_week": "W8"},
        {"name": "First Trimester Screening", "week": 12, "display_week": "W12"},
        {"name": "Nuchal Ultrasound", "week": 12, "display_week": "W12"},
        {"name": "Quad Screen", "week": 16, "display_week": "W16"},
        {"name": "AFP Test", "week": 16, "display_week": "W16"},
        {"name": "Anatomy Scan", "week": 20, "display_week": "W20"},
        {"name": "Glucose Tolerance Test", "week": 24, "display_week": "W24"},
        {"name": "Full Blood Count", "week": 24, "display_week": "W24"},
        {"name": "Anti-D Injection", "week": 28, "display_week": "W28"},
        {"name": "Growth Scan", "week": 32, "display_week": "W32"},
        {"name": "GBS Swab & Birth Plan", "week": 36, "display_week": "W36"},
        {"name": "Delivery Prep", "week": 40, "display_week": "W40"},
    ]
    
    # Filter tests that are upcoming (week >= current_week)
    upcoming_tests = [t for t in all_tests if t["week"] >= current_week]
    
    # Take first 5 upcoming tests
    next_5 = upcoming_tests[:5]
    
    # If not enough upcoming tests, include recent past tests
    if len(next_5) < 5:
        past_tests = [t for t in all_tests if t["week"] < current_week]
        past_tests.reverse()  # Start from most recent
        next_5.extend(past_tests[:5 - len(next_5)])
    
    # Format for response
    from datetime import datetime, timedelta
    result = []
    for test in next_5:
        test_week = test["week"]
        result.append({
            "name": test["name"],
            "week": test["display_week"],
            "date": f"Week {test_week}"  # Placeholder - would be calculated from cycle start date
        })
    
    return result


# ============================================================================
# PREGNANCY MILESTONES DATA - UI-ALIGNED NARRATIVE FORMAT
# ============================================================================

PREGNANCY_MILESTONES_DATA = {
    # Format: week: {baby, body, nutrition, exercises, clinical_tests, warning_signs}
    0: {
        "baby": "Conception begins. Sperm fertilizes egg and cell division starts rapidly.",
        "body": "No visible changes yet. Implantation occurs in uterine lining.",
        "nutrition": "Start prenatal vitamins with folic acid. Aim for balanced diet with leafy greens and dairy.",
        "exercises": "Continue your normal routine. Walking, yoga, and swimming are all safe.",
        "clinical_tests": [{"name": "Baseline Visit", "week": "W0", "date": "Sep 24"}],
        "warning_signs": "Contact your doctor if you experience severe abdominal pain or unusual bleeding."
    },
    8: {
        "baby": "Heart forming and beating. Limb buds are visible. Neural tube is closing to form the brain and spinal cord.",
        "body": "Morning sickness may start. Fatigue and breast tenderness are common. You might notice food aversions.",
        "nutrition": "Protein 70g/day, Calcium 1000mg/day essential. Eat eggs, nuts, and yogurt. Avoid high-mercury fish.",
        "exercises": "Walking, swimming, and prenatal yoga are safe. Avoid high-impact activities.",
        "clinical_tests": [{"name": "Confirm Pregnancy", "week": "W8", "date": "Nov 5"}, {"name": "Ultrasound", "week": "W8", "date": "Nov 5"}],
        "warning_signs": "Seek care for severe abdominal pain, heavy bleeding, or signs of ectopic pregnancy."
    },
    12: {
        "baby": "Size of a plum. Fingers and toes are forming. Reflexes are developing and external genitalia are forming.",
        "body": "Your belly is starting to show. Hormonal changes are ongoing. You might urinate more frequently.",
        "nutrition": "Protein 70g/day, Folic Acid 600mcg, Iron 27mg essential. Focus on citrus, broccoli, and lean red meat.",
        "exercises": "Walking, swimming, prenatal yoga, and pelvic floor exercises are all beneficial. Avoid heavy lifting.",
        "clinical_tests": [{"name": "First Trimester Screening", "week": "W12", "date": "Nov 12"}, {"name": "Nuchal Ultrasound", "week": "W12", "date": "Nov 12"}],
        "warning_signs": "Report severe cramping, heavy bleeding, or signs of miscarriage to your doctor immediately."
    },
    16: {
        "baby": "Size of an avocado. Facial features are becoming more defined. Ears are moving to the sides and hair follicles are forming.",
        "body": "Your belly is clearly visible now. Skin changes may appear. You've likely gained 3-5 lbs and nausea should be decreasing.",
        "nutrition": "Salmon, almonds, and sweet potatoes are great. Limit caffeine to less than 200mg/day.",
        "exercises": "30-minute walks, swimming, and prenatal yoga are safe and beneficial. Avoid lying flat on your back.",
        "clinical_tests": [{"name": "Quad Screen", "week": "W16", "date": "Nov 19"}, {"name": "AFP Test", "week": "W16", "date": "Nov 19"}],
        "warning_signs": "Contact doctor for severe headaches, vision changes, or swelling in hands and face."
    },
    20: {
        "baby": "Size of a banana. Unique fingerprints are forming. Baby can swallow and hiccup. Hair and eyebrows are visible.",
        "body": "Your belly is very pronounced. Stretch marks may appear. You've gained about 10 lbs. Back pain and leg cramps are common.",
        "nutrition": "Legumes, whole grains, and leafy greens are essential. Iron 27mg/day supports baby's growth.",
        "exercises": "Walking, swimming, prenatal yoga, and pelvic exercises are all safe. Avoid lifting more than 25 lbs.",
        "clinical_tests": [{"name": "Anatomy Scan", "week": "W20", "date": "Oct 2"}],
        "warning_signs": "Watch for sudden swelling, severe headaches, vision changes, or decreased fetal movement."
    },
    24: {
        "baby": "Lungs developing rapidly. Eyes partially open. Responds to sound. Baby can hear your heartbeat.",
        "body": "Uterus now above belly button. Braxton Hicks contractions may begin. You've gained 12-18 lbs total.",
        "nutrition": "Iron & Omega-3 critical. Aim for 300 extra calories/day. Focus on spinach, beef, yogurt, cheese, eggs, and tofu.",
        "exercises": "Swimming, walking, prenatal yoga all safe and beneficial. Kegel exercises strengthen pelvic floor.",
        "clinical_tests": [{"name": "Glucose Tolerance Test", "week": "W24", "date": "Nov 8 (Today)"}, {"name": "Full Blood Count", "week": "W24", "date": "Nov 8"}],
        "warning_signs": "Seek immediate care for severe headache, vision changes, sudden swelling, decreased fetal movement, or vaginal bleeding."
    },
    28: {
        "baby": "Eyes opening and closing. Responds to sounds and light. Sleep-wake cycles are establishing.",
        "body": "Increased swelling is normal. Darkened skin patches (melasma) may appear. Breasts may leak colostrum.",
        "nutrition": "Fiber 25-35g/day prevents constipation. Whole grain bread, beans, and prunes are excellent choices.",
        "exercises": "Walking 30-40 minutes, prenatal yoga, and pelvic floor exercises. Avoid high-impact activities.",
        "clinical_tests": [{"name": "Anti-D Injection", "week": "W28", "date": "Dec 6"}],
        "warning_signs": "Report signs of preterm labor: regular contractions, pelvic pressure, or vaginal fluid leakage."
    },
    32: {
        "baby": "Fingernails and toenails are fully formed. Baby's coordination is improving. Brain is developing rapidly.",
        "body": "You've gained 20-25 lbs total. Shortness of breath is normal. Sleeping may become difficult due to size.",
        "nutrition": "Omega-3 200-300mg/day from low-mercury fish, nuts, and seeds supports baby's brain development.",
        "exercises": "Gentle walking, swimming, and modified yoga. Avoid lying flat on your back. No heavy lifting.",
        "clinical_tests": [{"name": "Growth Scan", "week": "W32", "date": "Jan 3"}],
        "warning_signs": "Seek care immediately for signs of preeclampsia, placental issues, or decreased baby movement."
    },
    36: {
        "baby": "Baby weighs about 5.5 lbs and is ideally in head-down position. Baby can turn their head side to side.",
        "body": "Your belly may drop (lightening). Braxton Hicks increase. You'll feel more pelvic pressure and need to urinate frequently.",
        "nutrition": "Easy-to-digest proteins and iron-rich foods. Avoid heavy meals before bed to reduce heartburn.",
        "exercises": "Gentle walking, pelvic floor exercises, and relaxation techniques. Avoid strenuous activities.",
        "clinical_tests": [{"name": "GBS Swab & Birth Plan", "week": "W36", "date": "Jan 31"}],
        "warning_signs": "Contact hospital if contractions are regular, water breaks, heavy bleeding, or severe abdominal pain occurs."
    },
    40: {
        "baby": "Your baby is fully developed at 6.5-8.5 lbs and ready for birth. All major organs are functional.",
        "body": "Extreme fatigue, mood swings, and cervical changes signal labor may be near. You're at term!",
        "nutrition": "Light, nutritious meals and plenty of water. Eat 2500-2700 calories daily to maintain energy for labor.",
        "exercises": "Light walking only. Rest, relaxation techniques, and pelvic floor exercises to prepare for birth.",
        "clinical_tests": [{"name": "Delivery Prep", "week": "W40", "date": "Mar 15"}],
        "warning_signs": "Go to hospital if contractions are regular 5 minutes apart, water breaks, heavy bleeding, or severe pain occurs."
    }
}


# ============================================================================
# POSTPARTUM MILESTONES DATA (by Week)
# ============================================================================

POSTPARTUM_ACTIVITIES = {
    0: "Rest and recovery - avoid all strenuous activity",
    1: "Light activity, pelvic floor awareness, rest",
    2: "Gentle walking, continuing recovery",
    3: "Increase walking duration, start pelvic floor exercises",
    4: "Resume gentle stretching, continue exercises",
    6: "Can resume gentle exercise if approved by doctor",
    8: "Can increase exercise intensity if healing well",
    12: "Can resume most activities if cleared by doctor"
}


# ============================================================================
# MAIN API FUNCTIONS
# ============================================================================

def pregnancy_summary(user_id: int) -> Dict[str, Any]:
    """Get pregnancy summary for user (or postpartum if already delivered)."""
    try:
        from ai.utils.db import get_connection, get_user_profile, get_active_journey
        
        # Gate on the Pregnancy & Postpartum journey being active for this user -
        # profiles.life_stage_id and row-presence in user_pregnancies/postpartum_recoveries
        # are not sufficient on their own (a user can have orphaned rows from a
        # deactivated journey, or be on multiple simultaneous journeys).
        journey = get_active_journey(user_id, "Pregnancy & Postpartum")
        if not journey:
            profile = get_user_profile(user_id)
            if not profile:
                raise HTTPException(status_code=404, detail=f"User {user_id} not found")
            raise HTTPException(
                status_code=404,
                detail=f"User {user_id} does not have an active Pregnancy & Postpartum journey."
            )
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # PRIORITY 1: Check if user has postpartum data (already delivered)
            cursor.execute("""
                SELECT id, delivery_date, current_week, physical_recovery_percent,
                       hormonal_balance_percent, sleep_quality_percent, energy_levels_percent,
                       mood_stability, anxiety_level
                FROM postpartum_recoveries
                WHERE user_id = %s
                ORDER BY delivery_date DESC
                LIMIT 1
            """, (user_id,))
            postpartum = cursor.fetchone()
            
            # If postpartum data exists, return a clear indicator - don't duplicate postpartum endpoint
            if postpartum:
                delivery_date = postpartum.get("delivery_date")
                return {
                    "status": "delivery_completed",
                    "phase": "postpartum",
                    "is_pregnant": False,
                    "pregnancy_completed": True,
                    "delivery_completed": True,
                    "delivery_date": delivery_date.isoformat() if delivery_date else None,
                    "profile_id": journey["profile_id"],
                    "journey_id": journey["journey_id"],
                    "journey_title": journey["journey_title"],
                    "message": "Pregnancy delivery completed. Use /api/v1/postpartum/recovery endpoint for postpartum recovery details.",
                    "redirect_to": "/api/v1/postpartum/recovery"
                }
            
            # Try to get active pregnancy from user_pregnancies table (NEW)
            cursor.execute("""
                SELECT id, due_date, last_menstrual_period_date, conception_date, 
                       status, delivery_date, ended_at
                FROM user_pregnancies
                WHERE user_id = %s AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
            """, (user_id,))
            pregnancy = cursor.fetchone()
            
            # If not found in new table, check old menstrual_cycles table (BACKWARD COMPATIBILITY)
            if not pregnancy:
                cursor.execute("""
                    SELECT NULL as id, NULL as due_date, period_start_date as last_menstrual_period_date, 
                           NULL as conception_date, 'active' as status, period_end_date as delivery_date, NULL as ended_at
                    FROM menstrual_cycles
                    WHERE user_id = %s AND is_completed = 0 AND period_start_date IS NOT NULL
                    ORDER BY period_start_date DESC
                    LIMIT 1
                """, (user_id,))
                pregnancy = cursor.fetchone()
            
            if not pregnancy:
                return {
                    "is_pregnant": False,
                    "message": "No active pregnancy found",
                    "profile_id": journey["profile_id"],
                    "journey_id": journey["journey_id"],
                    "journey_title": journey["journey_title"],
                }
            
            # Use LMP date or conception date to calculate pregnancy start
            pregnancy_start = pregnancy.get("last_menstrual_period_date") or pregnancy.get("conception_date")
            
            if not pregnancy_start:
                return {
                    "is_pregnant": False,
                    "message": "No pregnancy start date found",
                    "profile_id": journey["profile_id"],
                    "journey_id": journey["journey_id"],
                    "journey_title": journey["journey_title"],
                }
            
            pregnancy_id = pregnancy.get("id")
            due_date = pregnancy.get("due_date")
            
            # VALIDATION: Check if pregnancy start date is in the future
            _validate_pregnancy_start_date(pregnancy_start, user_id)
            
            current_date = date.today()
            current_week = (current_date - pregnancy_start).days // 7
            
            # Validate week range
            if current_week < 0 or current_week > 40:
                current_week = max(0, min(40, current_week))
            
            # Determine trimester
            if current_week <= 12:
                trimester = "First"
            elif current_week <= 27:
                trimester = "Second"
            else:
                trimester = "Third"
            
            # Calculate days until due date
            current_date = date.today()
            days_until_due = (due_date - current_date).days if due_date else 280 - (current_date - pregnancy_start).days
            
            # Generate alerts based on week
            alerts = _generate_pregnancy_alerts(current_week, trimester)
            
            # Get weekly guide data from pregnancy_weekly_guides table
            cursor.execute("""
                SELECT baby_development, your_body, nutrition_focus, safe_exercise, 
                       clinical_warning_signs, trimester
                FROM pregnancy_weekly_guides
                WHERE week_number = %s
                LIMIT 1
            """, (current_week,))
            guide = cursor.fetchone()
            
            # Fallback to closest milestone week if exact week not found
            if not guide:
                closest_week = _find_closest_milestone_week(current_week)
                cursor.execute("""
                    SELECT baby_development, your_body, nutrition_focus, safe_exercise, 
                           clinical_warning_signs
                    FROM pregnancy_weekly_guides
                    WHERE week_number = %s
                    LIMIT 1
                """, (closest_week,))
                guide = cursor.fetchone()
            
            # Get next 5 clinical tests from pregnancy_milestones table (if pregnancy_id exists)
            clinical_tests = []
            
            if pregnancy_id:
                # NEW TABLE: Query pregnancy_milestones
                cursor.execute("""
                    SELECT title, target_week, scheduled_date, is_completed
                    FROM pregnancy_milestones
                    WHERE pregnancy_id = %s AND target_week >= %s
                    ORDER BY target_week ASC
                    LIMIT 5
                """, (pregnancy_id, current_week))
                tests = cursor.fetchall()
                
                # Format clinical tests from database
                for test in tests:
                    clinical_tests.append({
                        "name": test.get("title", ""),
                        "week": f"W{test.get('target_week', 0)}",
                        "date": test.get("scheduled_date").isoformat() if test.get("scheduled_date") else f"Week {test.get('target_week', 0)}"
                    })
            
            # Fallback to hardcoded tests if pregnancy_id is NULL (OLD TABLE compatibility)
            if not clinical_tests:
                clinical_tests = _get_next_5_clinical_tests(current_week)
            
            # Check pregnancy journey status using user_pregnancies status field
            has_delivered = pregnancy.get("delivery_date") is not None
            
            # Determine pregnancy status and required confirmations
            status_info = _get_pregnancy_status(current_week, pregnancy.get("status"), has_delivered)
            
            # === USE CLAUDE AI TO GENERATE PERSONALIZED PREGNANCY CONTENT ===
            print(f"[DEBUG] pregnancy_summary: Starting Claude generation for week {current_week}")
            try:
                from ai.utils.llm_call import llm_call
                
                # Always generate with Claude (database fields are typically empty)
                # Baby development
                baby_dev_prompt = f"Generate a brief pregnancy update (2-3 sentences) about baby development at week {current_week}. Be warm and empowering."
                print(f"[DEBUG] Calling Claude for baby_development...")
                baby_development = llm_call(baby_dev_prompt, max_tokens=150)
                print(f"[DEBUG] Claude baby_development response length: {len(baby_development) if baby_development else 0}")
                
                # Your body changes
                body_prompt = f"Generate a brief update (2-3 sentences) about mother's body changes at week {current_week}. Be supportive and informative."
                your_body = llm_call(body_prompt, max_tokens=150)
                
                # Nutrition focus
                nutrition_prompt = f"Generate brief nutrition guidance (2-3 sentences) for week {current_week} pregnancy. Be specific and practical."
                nutrition_focus = llm_call(nutrition_prompt, max_tokens=150)
                
                # Safe exercises
                exercise_prompt = f"Generate brief safe exercise recommendations (2-3 sentences) for week {current_week} pregnancy. Be encouraging."
                safe_exercises = llm_call(exercise_prompt, max_tokens=150)
                
                # Clinical warning signs
                warning_prompt = f"Generate brief clinical warning signs (2-3 sentences) to watch for at week {current_week} pregnancy. Be clear and reassuring."
                clinical_warning_signs = llm_call(warning_prompt, max_tokens=150)
                
            except Exception as e:
                print(f"[ERROR] Claude generation FAILED for pregnancy_summary user {user_id}: {e}")
                print(f"[ERROR] Exception type: {type(e).__name__}")
                import traceback
                traceback.print_exc()
                # Fallback to database content (likely empty, but better than errors)
                baby_development = guide.get("baby_development", "") if guide else ""
                your_body = guide.get("your_body", "") if guide else ""
                nutrition_focus = guide.get("nutrition_focus", "") if guide else ""
                safe_exercises = guide.get("safe_exercise", "") if guide else ""
                clinical_warning_signs = guide.get("clinical_warning_signs", "") if guide else ""
                print(f"[ERROR] Falling back to empty strings")
            
            response = PregnancySummary(
                is_pregnant=True,
                current_week=current_week,
                current_trimester=trimester,
                due_date=due_date.isoformat() if due_date else None,
                days_until_due=max(0, days_until_due), 
                last_prenatal_visit=None,
                next_appointment=None,
                health_status="good",
                alerts=alerts,
                baby_development=baby_development,
                your_body=your_body,
                nutrition_focus=nutrition_focus,
                safe_exercises=safe_exercises,
                clinical_monitoring=clinical_tests,
                clinical_warning_signs=clinical_warning_signs,
                pregnancy_status=status_info["pregnancy_status"],
                requires_confirmation=status_info["requires_confirmation"],
                confirmation_needed_for=status_info["confirmation_needed_for"],
                confirmation_message=status_info["confirmation_message"]
            ).model_dump(exclude_none=False)
            
            # Add phase indicator + journey identity for multi-journey correlation
            response["phase"] = "pregnancy"
            response["profile_id"] = journey["profile_id"]
            response["journey_id"] = journey["journey_id"]
            response["journey_title"] = journey["journey_title"]
            response["pregnancy_id"] = pregnancy_id
            return response
    
    except HTTPException:
        raise  # Re-raise HTTPException to propagate to FastAPI
    except Exception as e:
        print(f"[ERROR] pregnancy_summary failed for user {user_id}: {e}")
        return {"status": "error", "message": str(e), "user_id": user_id}


def pregnancy_milestones(user_id: int, week: Optional[int] = None) -> Dict[str, Any]:
    """Get pregnancy milestones for specific week - UI-aligned narrative format."""
    try:
        from ai.utils.db import get_connection, get_user_profile, get_active_journey
        
        journey = get_active_journey(user_id, "Pregnancy & Postpartum")
        if not journey:
            profile = get_user_profile(user_id)
            if not profile:
                raise HTTPException(status_code=404, detail=f"User {user_id} not found")
            raise HTTPException(
                status_code=404,
                detail=f"User {user_id} does not have an active Pregnancy & Postpartum journey."
            )
        
        # Get current week if not specified
        if week is None:
            summary = pregnancy_summary(user_id)
            if summary.get("is_pregnant"):
                week = summary.get("current_week", 20)
            else:
                week = 20  # Default to mid-pregnancy
        
        # Validate week
        week = max(0, min(40, week))
        
        # Find closest milestone data
        milestone_week = _find_closest_milestone_week(week)
        data = PREGNANCY_MILESTONES_DATA.get(milestone_week, PREGNANCY_MILESTONES_DATA[20])
        
        # Determine trimester
        if week <= 12:
            trimester = "First"
        elif week <= 27:
            trimester = "Second"
        else:
            trimester = "Third"
        
        # Get next 5 clinical tests (unified response)
        clinical_tests = _get_next_5_clinical_tests(week)
        
        result = PregnancyMilestones(
            week=week,
            trimester=trimester,
            baby_development=data.get("baby", ""),
            your_body=data.get("body", ""),
            nutrition_focus=data.get("nutrition", ""),
            safe_exercises=data.get("exercises", ""),
            clinical_monitoring=clinical_tests,
            clinical_warning_signs=data.get("warning_signs", "")
        ).model_dump(exclude_none=False)
        result["profile_id"] = journey["profile_id"]
        result["journey_id"] = journey["journey_id"]
        result["journey_title"] = journey["journey_title"]
        return result
    
    except HTTPException:
        raise  # Re-raise HTTPException to propagate to FastAPI
    except Exception as e:
        print(f"[ERROR] pregnancy_milestones failed for user {user_id}, week {week}: {e}")
        return {"status": "error", "message": str(e), "user_id": user_id}


def pregnancy_clinical_timeline(user_id: int, week: Optional[int] = None) -> Dict[str, Any]:
    """Get all clinical tests across entire pregnancy with dates - UI timeline view."""
    try:
        from ai.utils.db import get_connection, get_user_profile, get_active_journey
        
        journey = get_active_journey(user_id, "Pregnancy & Postpartum")
        if not journey:
            profile = get_user_profile(user_id)
            if not profile:
                raise HTTPException(status_code=404, detail=f"User {user_id} not found")
            raise HTTPException(
                status_code=404,
                detail=f"User {user_id} does not have an active Pregnancy & Postpartum journey."
            )
        
        # Get current week if not specified
        if week is None:
            summary = pregnancy_summary(user_id)
            if summary.get("is_pregnant"):
                week = summary.get("current_week", 20)
            else:
                week = 20  # Default to mid-pregnancy
        
        # Validate week
        week = max(0, min(40, week))
        
        # Determine trimester
        if week <= 12:
            trimester = "First"
        elif week <= 27:
            trimester = "Second"
        else:
            trimester = "Third"
        
        # Get next 5 clinical tests (unified response)
        clinical_tests = _get_next_5_clinical_tests(week)
        
        # Get warning signs for current week
        milestone_week = _find_closest_milestone_week(week)
        current_data = PREGNANCY_MILESTONES_DATA.get(milestone_week, PREGNANCY_MILESTONES_DATA[20])
        warning_signs = current_data.get("warning_signs", "")
        
        return {
            "week": week,
            "trimester": trimester,
            "clinical_monitoring": clinical_tests,
            "clinical_warning_signs": warning_signs,
            "profile_id": journey["profile_id"],
            "journey_id": journey["journey_id"],
            "journey_title": journey["journey_title"],
        }
    
    except HTTPException:
        raise  # Re-raise HTTPException to propagate to FastAPI
    except Exception as e:
        print(f"[ERROR] pregnancy_clinical_timeline failed for user {user_id}, week {week}: {e}")
        return {"status": "error", "message": str(e), "user_id": user_id}


def postpartum_recovery(user_id: int) -> Dict[str, Any]:
    """Get postpartum recovery overview."""
    try:
        from ai.utils.db import get_connection, get_user_profile, get_active_journey
        
        # Gate on the Pregnancy & Postpartum journey being active - row presence in
        # postpartum_recoveries/menstrual_cycles alone is not sufficient (orphaned
        # data from a deactivated journey must not be surfaced).
        journey = get_active_journey(user_id, "Pregnancy & Postpartum")
        if not journey:
            profile = get_user_profile(user_id)
            if not profile:
                raise HTTPException(status_code=404, detail=f"User {user_id} not found")
            raise HTTPException(
                status_code=404,
                detail=f"User {user_id} does not have an active Pregnancy & Postpartum journey."
            )
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Try to get postpartum data from NEW postpartum_recoveries table
            cursor.execute("""
                SELECT delivery_date, current_week, physical_recovery_percent, 
                       hormonal_balance_percent, sleep_quality_percent, energy_levels_percent,
                       mood_stability, anxiety_level, screening_name, screening_due_text
                FROM postpartum_recoveries
                WHERE user_id = %s
                ORDER BY delivery_date DESC
                LIMIT 1
            """, (user_id,))
            postpartum_record = cursor.fetchone()
            
            # Fallback to OLD menstrual_cycles table if not found
            if postpartum_record:
                delivery_date = postpartum_record.get("delivery_date")
            else:
                cursor.execute("""
                    SELECT period_end_date as delivery_date
                    FROM menstrual_cycles
                    WHERE user_id = %s AND is_completed = 1
                    ORDER BY period_end_date DESC
                    LIMIT 1
                """, (user_id,))
                cycle = cursor.fetchone()
                
                if not cycle or not cycle.get("delivery_date"):
                    return {
                        "days_postpartum": 0,
                        "postpartum_week": 0,
                        "recovery_status": "no_data",
                        "delivery_method": "unknown",
                        "physical_health": {"physical_recovery_percent": 0, "bleeding_level": "unknown", "pelvic_floor_status": "unknown", "hormonal_balance_percent": 0, "energy_level_percent": 0, "sleep_quality_percent": 0},
                        "mental_health": {"mood_stability": 0, "anxiety_level": 0, "depression_screening": "unknown", "mood_trend": "unknown", "supportive_resources": []},
                        "activity_level": "Consult doctor",
                        "alerts": [],
                        "next_follow_up": None,
                        "message": "No completed pregnancy found",
                        "profile_id": journey["profile_id"],
                        "journey_id": journey["journey_id"],
                        "journey_title": journey["journey_title"],
                    }
                
                delivery_date = cycle.get("delivery_date")
            current_date = date.today()
            postpartum_week = (current_date - delivery_date).days // 7
            postpartum_week = max(0, min(12, postpartum_week))
            
            # Bound the window to this delivery's 12-week postpartum period so logs from a
            # subsequent pregnancy/delivery can't leak into this journey's recovery metrics.
            window_end = delivery_date + timedelta(weeks=12)
            cursor.execute("""
                SELECT mood, energy_level, symptoms, notes, log_date
                FROM health_logs
                WHERE user_id = %s AND log_date >= %s AND log_date <= %s
                ORDER BY log_date DESC
                LIMIT 14
            """, (user_id, delivery_date, window_end))
            health_logs = cursor.fetchall()
            
            # Calculate recovery metrics from health logs
            recovery_metrics = _calculate_recovery_metrics(health_logs, postpartum_week)
            mental_health = _calculate_mental_health(health_logs)
            alerts = _generate_postpartum_alerts(postpartum_week, recovery_metrics, mental_health)
            
            # Determine recovery status based on postpartum week
            if postpartum_week <= 2:
                recovery_status = "early"
            elif postpartum_week <= 6:
                recovery_status = "mid"
            elif postpartum_week <= 10:
                recovery_status = "advanced"
            else:
                recovery_status = "complete"
            
            # Calculate days postpartum
            days_postpartum = (current_date - delivery_date).days
            
            # Convert MentalHealth object to dict for UI generation
            mental_health_dict = mental_health.model_dump() if hasattr(mental_health, 'model_dump') else {
                "mood_stability": 60,
                "anxiety_level": 5,
                "depression_screening": "low_risk",
                "supportive_resources": []
            }
            
            # Generate personalized mental health UI component
            mental_health_ui = _generate_personalized_mental_health_ui(
                user_id, 
                mental_health_dict,
                postpartum_week,
                health_logs
            )
            
            return {
                "phase": "postpartum",
                "profile_id": journey["profile_id"],
                "journey_id": journey["journey_id"],
                "journey_title": journey["journey_title"],
                "delivery_date": delivery_date.isoformat(),
                "days_postpartum": days_postpartum,
                "postpartum_week": postpartum_week,
                "recovery_status": recovery_status,
                "delivery_method": "vaginal",  # Would need separate table to track
                "physical_health": recovery_metrics,
                "mental_health": mental_health_dict,
                "mental_health_ui": mental_health_ui
            }
    
    except HTTPException:
        raise  # Re-raise HTTPException to propagate to FastAPI
    except Exception as e:
        print(f"[ERROR] postpartum_recovery failed for user {user_id}: {e}")
        return {"status": "error", "message": str(e), "user_id": user_id}


def support_groups(life_stage: str, limit: int = 10) -> Dict[str, Any]:
    """Get support communities for pregnancy/postpartum."""
    try:
        from ai.utils.db import get_connection
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Map life stages to community tags
            if life_stage.lower() == "pregnancy":
                tag_filter = "%pregnancy%"
                life_stage_id = 3
            elif life_stage.lower() == "postpartum":
                tag_filter = "%postpartum%"
                life_stage_id = 4
            else:
                return {"groups": [], "total_groups": 0, "user_joined_count": 0}
            
            # Fetch community posts related to life stage
            cursor.execute("""
                SELECT DISTINCT 
                    cp.id,
                    cp.title as name,
                    cp.content as description,
                    COUNT(DISTINCT cp.user_id) as member_count,
                    COUNT(DISTINCT CASE WHEN cp.posted_at >= DATE_SUB(NOW(), INTERVAL 1 DAY) THEN cp.id END) as latest_posts_count,
                    cp.created_at
                FROM community_posts cp
                WHERE cp.tags LIKE %s OR cp.is_approved = 1
                GROUP BY cp.id
                ORDER BY member_count DESC, cp.created_at DESC
                LIMIT %s
            """, (tag_filter, limit))
            
            community_rows = cursor.fetchall()
            
            groups = []
            for row in community_rows:
                groups.append(SupportGroup(
                    id=row.get("id"),
                    name=row.get("name", "Community Group"),
                    description=row.get("description", "Support community"),
                    life_stage=life_stage,
                    member_count=row.get("member_count", 0),
                    active_users_today=max(5, row.get("member_count", 10) // 4),  # Estimate
                    latest_posts_count=row.get("latest_posts_count", 0),
                    is_moderated=True,
                    join_status="not_joined",
                    created_at=row.get("created_at").isoformat() if row.get("created_at") else None
                ))
            
            return SupportGroupResponse(
                groups=groups,
                total_groups=len(groups),
                user_joined_count=0
            ).model_dump(exclude_none=False)
    
    except Exception as e:
        print(f"[ERROR] support_groups failed for {life_stage}: {e}")
        return {"groups": [], "total_groups": 0, "user_joined_count": 0, "error": str(e)}


def miscarriage_support(user_id: int) -> Dict[str, Any]:
    """
    Get miscarriage support resources and mental health information.
    Detects if user has experienced pregnancy loss and provides support.
    """
    try:
        from ai.utils.db import get_connection, get_user_profile
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if user exists
            profile = get_user_profile(user_id)
            if not profile:
                raise HTTPException(status_code=404, detail=f"User {user_id} not found")
            
            # Detect miscarriage from health logs symptoms
            cursor.execute("""
                SELECT hl.symptoms, hl.notes, hl.log_date, mc.period_start_date
                FROM health_logs hl
                LEFT JOIN menstrual_cycles mc ON hl.user_id = mc.user_id
                WHERE hl.user_id = %s
                ORDER BY hl.log_date DESC
                LIMIT 20
            """, (user_id,))
            
            health_logs = cursor.fetchall()
            
            # Check for miscarriage indicators in symptoms/notes
            miscarriage_keywords = ['miscarriage', 'pregnancy loss', 'lost pregnancy', 'heavy bleeding', 'severe cramping', 'no heartbeat']
            has_miscarriage = False
            miscarriage_date = None
            
            for log in health_logs:
                symptoms = str(log.get('symptoms', '')).lower() if log.get('symptoms') else ''
                notes = str(log.get('notes', '')).lower() if log.get('notes') else ''
                
                for keyword in miscarriage_keywords:
                    if keyword in symptoms or keyword in notes:
                        has_miscarriage = True
                        miscarriage_date = log.get('log_date')
                        break
                
                if has_miscarriage:
                    break
            
            # If miscarriage detected, provide mental support
            if has_miscarriage:
                # Get support groups for pregnancy loss
                cursor.execute("""
                    SELECT DISTINCT 
                        cp.id,
                        cp.title as name,
                        cp.content as description,
                        COUNT(DISTINCT cp.user_id) as member_count,
                        cp.created_at
                    FROM community_posts cp
                    WHERE (cp.tags LIKE '%miscarriage%' OR cp.tags LIKE '%pregnancy loss%' OR cp.tags LIKE '%grief%')
                    AND cp.is_approved = 1
                    GROUP BY cp.id
                    ORDER BY member_count DESC
                    LIMIT 5
                """)
                
                support_community = cursor.fetchall()
                
                support_groups_list = []
                for row in support_community:
                    support_groups_list.append({
                        "id": row.get("id"),
                        "name": row.get("name", "Support Community"),
                        "description": row.get("description", "Community support for pregnancy loss"),
                        "member_count": row.get("member_count", 0),
                        "type": "pregnancy_loss"
                    })
                
                # Mental health resources and professional help
                mental_health_resources = {
                    "immediate_support": {
                        "crisis_hotline": "1-800-273-8255 (24/7 Suicide & Crisis Lifeline)",
                        "pregnancy_loss_hotline": "1-888-495-2288 (MISSCARRIAGE Support)",
                        "whatsapp_support": "Available for chat support"
                    },
                    "professional_help": {
                        "grief_counseling": "Specialized counselors for pregnancy loss grief",
                        "therapy_options": ["Individual counseling", "Couples counseling", "Support groups"],
                        "recommended_timeline": "Contact therapist within 1-2 weeks"
                    },
                    "self_care_tips": [
                        "Allow yourself to grieve without judgment",
                        "Talk to trusted family and friends about your feelings",
                        "Join support groups with others who have experienced pregnancy loss",
                        "Practice self-compassion and patience with recovery",
                        "Avoid blame or guilt - miscarriage is not your fault",
                        "Consider journaling or creative expression",
                        "Follow your doctor's physical recovery guidelines"
                    ],
                    "physical_recovery": {
                        "healing_timeline": "4-6 weeks for physical recovery",
                        "when_to_contact_doctor": [
                            "Heavy bleeding (soaking more than 1 pad per hour)",
                            "Severe or worsening abdominal pain",
                            "Fever above 100.4°F",
                            "Foul-smelling discharge",
                            "Signs of infection"
                        ]
                    }
                }
                
                # Generate personalized supportive text using Claude LLM
                supportive_message = _generate_miscarriage_support_text(user_id, profile, miscarriage_date)
                
                return {
                    "has_miscarriage": True,
                    "miscarriage_detected_date": miscarriage_date.isoformat() if miscarriage_date else None,
                    "status": "support_needed",
                    "supportive_message": supportive_message,
                    "support_communities": support_groups_list,
                    "mental_health_resources": mental_health_resources,
                    "next_steps": [
                        "Allow time for emotional and physical healing",
                        "Connect with support communities of others who understand",
                        "Consider professional grief counseling",
                        "Follow up with your doctor at recommended timeline",
                        "When ready, discuss future pregnancy options with your healthcare provider"
                    ]
                }
            else:
                # Return complete structure even when no miscarriage (for consistency)
                return {
                    "has_miscarriage": False,
                    "supportive_message": "You are not showing signs of pregnancy loss. Continue your regular prenatal care and reach out to your healthcare provider if you have any concerns.",
                    "support_communities": [],
                    "mental_health_resources": {
                        "general_support": "If you experience emotional challenges, various support resources are available",
                        "professional_help": ["Prenatal mental health screening", "Counseling services", "Support groups"],
                        "recommended_action": "Regular prenatal mental health check-ins are recommended"
                    },
                    "next_steps": [
                        "Continue regular prenatal appointments",
                        "Monitor for any changes in pregnancy symptoms",
                        "Reach out if you develop concerning symptoms",
                        "Maintain healthy lifestyle habits",
                        "Report any unusual bleeding or pain to your provider"
                    ]
                }
    
    except HTTPException:
        raise  # Re-raise HTTPException to propagate to FastAPI
    except Exception as e:
        print(f"[ERROR] miscarriage_support failed for user {user_id}: {e}")
        return {"status": "error", "message": str(e), "user_id": user_id}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _find_closest_milestone_week(target_week: int) -> int:
    """Find closest milestone week from available data."""
    available_weeks = [0, 8, 12, 16, 20, 24, 28, 32, 36, 40]
    return min(available_weeks, key=lambda x: abs(x - target_week))


def _generate_pregnancy_alerts(week: int, trimester: str) -> list:
    """Generate relevant alerts based on pregnancy week."""
    alerts = []
    
    if week < 12:
        alerts.append(PregnancyAlert(
            message="Ensure adequate folic acid intake (600 mcg/day)",
            severity="low",
            action_required=False
        ))
    
    if 24 <= week < 28:
        alerts.append(PregnancyAlert(
            message="Glucose tolerance test due this week",
            severity="medium",
            action_required=True
        ))
    
    if week >= 36:
        alerts.append(PregnancyAlert(
            message="Monitor for signs of labor (contractions, bloody show)",
            severity="medium",
            action_required=False
        ))
    
    return alerts


def _generate_postpartum_alerts(week: int, recovery: RecoveryMetrics, mental_health: MentalHealth) -> list:
    """Generate postpartum alerts based on recovery status."""
    alerts = []
    
    if recovery.bleeding_level == "heavy":
        alerts.append(PostpartumAlert(
            type="bleeding",
            level="high",
            message="Excessive bleeding detected. Contact doctor if more than 1 pad/hour"
        ))
    
    if mental_health.depression_screening == "moderate_risk":
        alerts.append(PostpartumAlert(
            type="mental_health",
            level="moderate",
            message="Depression risk detected. Consider speaking with mental health professional"
        ))
    
    if mental_health.anxiety_level > 7:
        alerts.append(PostpartumAlert(
            type="mental_health",
            level="high",
            message="High anxiety levels. Professional support recommended"
        ))
    
    return alerts


def _calculate_recovery_metrics(logs: list, postpartum_week: int) -> RecoveryMetrics:
    """Calculate recovery metrics from health logs."""
    # Estimate recovery based on week (20% baseline + 10% per week)
    recovery_percent = min(100, 20 + (postpartum_week * 10))
    
    # Calculate hormonal balance (improves over time)
    # Week 0-2: 30%, Week 3-6: 50%, Week 7-12: 75%+
    if postpartum_week < 3:
        hormonal_balance = 30
    elif postpartum_week < 7:
        hormonal_balance = 50 + (postpartum_week - 3) * 3
    else:
        hormonal_balance = min(100, 75 + (postpartum_week - 7) * 3)
    
    # Parse energy from logs and convert to percentage
    avg_energy_percent = 40  # Default for week 0
    if logs:
        energy_mapping = {"Very Low": 10, "Low": 30, "Moderate": 50, "High": 70, "Very High": 90}
        energies = [energy_mapping.get(log.get("energy_level"), 50) for log in logs if log.get("energy_level")]
        if energies:
            avg_energy_percent = int(sum(energies) / len(energies))
        else:
            # Estimate based on postpartum week
            avg_energy_percent = min(90, 40 + (postpartum_week * 5))
    else:
        # Default estimate by week
        avg_energy_percent = min(90, 40 + (postpartum_week * 5))
    
    # Calculate sleep quality percentage (4.5 hours = 45%, 8 hours = 100%)
    sleep_quality_percent = min(100, 45 + (postpartum_week * 5))
    
    return RecoveryMetrics(
        physical_recovery_percent=int(recovery_percent),
        bleeding_level="light" if postpartum_week > 2 else "moderate",
        pelvic_floor_status="healing" if postpartum_week < 6 else "recovered",
        hormonal_balance_percent=int(hormonal_balance),
        energy_level_percent=avg_energy_percent,
        sleep_quality_percent=int(sleep_quality_percent)
    )


def _calculate_mental_health(logs: list) -> MentalHealth:
    """Calculate mental health metrics from health logs."""
    if not logs:
        return MentalHealth(
            mood_stability=60,
            anxiety_level=5,
            depression_screening="low_risk",
            mood_trend="stable",
            supportive_resources=["Postpartum Support Group", "Mental Health Hotline"]
        )
    
    # Parse mood from logs
    mood_mapping = {"Happy": 8, "Neutral": 5, "Sad": 2, "Anxious": 3, "Overwhelmed": 2}
    moods = [mood_mapping.get(log.get("mood"), 5) for log in logs if log.get("mood")]
    
    avg_mood = sum(moods) / len(moods) if moods else 5
    mood_stability = int((avg_mood / 10) * 100)
    
    # Detect trend
    if len(moods) >= 2:
        trend = "improving" if moods[-1] > moods[0] else "declining" if moods[-1] < moods[0] else "stable"
    else:
        trend = "stable"
    
    return MentalHealth(
        mood_stability=mood_stability,
        anxiety_level=5,  # Would need specific anxiety tracking
        depression_screening="low_risk" if mood_stability > 70 else "moderate_risk",
        last_mood_entry=logs[0].get("log_date").isoformat() if logs else None,
        mood_trend=trend,
        supportive_resources=["Postpartum Support Group", "Mental Health Helpline", "Partner Support"]
    )


def _score_to_label(score: int, metric_type: str) -> str:
    """Convert numeric score to readable label."""
    if metric_type == "mood":
        if score >= 71:
            return "Excellent"
        elif score >= 51:
            return "Stable"
        elif score >= 31:
            return "Concerning"
        else:
            return "Critical"
    elif metric_type == "anxiety":
        if score <= 3:
            return "Low"
        elif score <= 6:
            return "Mild"
        elif score <= 10:
            return "Moderate"
        else:
            return "Severe"
    return "Unknown"


def _calculate_trend(history: list) -> str:
    """Compare current vs previous to show if improving/declining."""
    if not history or len(history) < 2:
        return "new"
    
    current = history[-1].get("mood_stability", 60)
    previous = history[-2].get("mood_stability", 60)
    
    if current > previous + 10:
        return "improving"
    elif current < previous - 10:
        return "declining"
    else:
        return "stable"


def _assess_risk_level(mental_health_data: dict, postpartum_week: int) -> str:
    """Dynamic risk scoring based on postpartum week + scores."""
    score = 0
    
    # Postpartum weeks 2-4 = highest risk period for PPD/PPA
    if 2 <= postpartum_week <= 4:
        score += 2
    
    # Anxiety threshold changes by week
    anxiety_thresholds = {
        1: 12, 2: 10, 3: 9, 4: 8, 6: 6, 8: 5, 12: 4
    }
    threshold = anxiety_thresholds.get(postpartum_week, 4)
    if mental_health_data.get("anxiety_level", 5) > threshold:
        score += 3
    
    # Mood below 40 = concern
    if mental_health_data.get("mood_stability", 60) < 40:
        score += 3
    
    # Depression screening
    depression_screen = mental_health_data.get("depression_screening", "low_risk")
    if depression_screen in ["moderate_risk", "high_risk"]:
        score += 2
    
    if score >= 6:
        return "critical"
    elif score >= 4:
        return "high"
    elif score >= 2:
        return "moderate"
    else:
        return "low"


def _get_personalized_recommendations(user_id: int, postpartum_week: int, risk_level: str, mental_health_data: dict) -> list:
    """Generate brief, personalized recommendations using Claude LLM."""
    try:
        from ai.utils.llm_call import call_claude
        
        prompt = f"""Generate 1-2 brief, actionable mental health recommendations (one short line each) for a postpartum woman:
- Week: {postpartum_week}
- Anxiety: {mental_health_data.get('anxiety_level', 5)}/15
- Mood: {mental_health_data.get('mood_stability', 60)}/100
- Risk: {risk_level}

Format as JSON: [{{"priority": "high|moderate|low", "action": "short recommendation"}}]"""
        
        response = call_claude(prompt, max_tokens=150)
        
        # Parse JSON response
        import json
        try:
            recs = json.loads(response)
            return recs if isinstance(recs, list) else []
        except:
            return [{"priority": "routine", "action": "Continue self-care practices that work for you"}]
    
    except Exception as e:
        print(f"[ERROR] LLM recommendation failed: {e}")
        return [{"priority": "routine", "action": "Prioritize rest and reach out for support if needed"}]


def _generate_personalized_mental_health_ui(user_id: int, mental_health_data: dict, postpartum_week: int, health_logs: list) -> dict:
    """Generate personalized mental health UI component with dynamic risk assessment."""
    
    # Calculate trend
    trend = _calculate_trend(health_logs)
    
    # Assess risk level
    risk_level = _assess_risk_level(mental_health_data, postpartum_week)
    
    # Get LLM recommendations (brief, one line each)
    recommendations = _get_personalized_recommendations(user_id, postpartum_week, risk_level, mental_health_data)
    
    return {
        "screening_type": "mental_health_check_in",
        "title": "Postpartum Wellness Screening",
        "week": postpartum_week,
        "risk_level": risk_level,
        "trend": trend,
        "metrics": [
            {
                "label": "Mood stability",
                "value": _score_to_label(mental_health_data.get("mood_stability", 60), "mood"),
                "score": mental_health_data.get("mood_stability", 60),
                "trend_arrow": "↑" if trend == "improving" else "↓" if trend == "declining" else "→"
            },
            {
                "label": "Anxiety levels",
                "value": _score_to_label(mental_health_data.get("anxiety_level", 5), "anxiety"),
                "score": mental_health_data.get("anxiety_level", 5),
                "warning": mental_health_data.get("anxiety_level", 5) > 8
            },
            {
                "label": "Depression risk",
                "value": mental_health_data.get("depression_screening", "low_risk"),
                "risk_increased": risk_level in ["high", "critical"]
            }
        ]
    }


def _generate_miscarriage_support_text(user_id: int, profile: dict, miscarriage_date: date) -> str:
    """
    Generate personalized, compassionate support message using Claude LLM.
    This message appears in the Support tab of the UI.
    """
    try:
        from ai.utils.llm_call import llm_call
        
        user_name = profile.get("full_name", "there").split()[0] if profile.get("full_name") else "there"
        days_since = (date.today() - miscarriage_date).days if isinstance(miscarriage_date, date) else 0
        
        prompt = f"""
You are a compassionate mental health support specialist providing emotional support to a woman experiencing pregnancy loss.

User Context:
- Name: {user_name}
- Loss Date: {miscarriage_date}
- Days Since Loss: {days_since} days
- User ID: {user_id}

Generate a warm, personalized, deeply empathetic support message that:
1. Acknowledges her loss with genuine compassion
2. Validates her emotions and grief
3. Reminds her that miscarriage is NOT her fault
4. Provides gentle encouragement for her healing journey
5. Offers hope while respecting her current pain

Requirements:
- Keep the tone warm, human, and genuine (NOT clinical or robotic)
- 200-400 words of heartfelt support
- Personalize with her name naturally
- Include practical emotional coping suggestions
- Emphasize that seeking help is a sign of strength
- End with an uplifting message about moving forward at her own pace

Format: Plain text paragraph, no markdown or special formatting.
"""
        
        supportive_message = llm_call(
            prompt=prompt,
            max_tokens=500,
            system_prompt="You are a compassionate grief counselor providing emotional support to women experiencing pregnancy loss. Your messages are deeply empathetic, non-judgmental, and healing-focused."
        )
        
        return supportive_message
    
    except Exception as e:
        print(f"[ERROR] Failed to generate Claude support message for user {user_id}: {e}")
        # Fallback message if Claude fails
        user_name = profile.get("full_name", "there").split()[0] if profile.get("full_name") else "there"
        return f"""Dear {user_name},

We are deeply sorry for your loss. Miscarriage is a profound loss that deserves to be grieved. What you're feeling right now - whether it's sadness, anger, guilt, or emptiness - is completely valid and understandable.

Please know that miscarriage is NOT your fault. There is nothing you did or didn't do that caused this. Your body did not fail you - sometimes pregnancies end for reasons beyond our control, and that's not a reflection of your strength or capability as a person or mother.

You deserve support during this time. Whether it's through talking with trusted loved ones, connecting with others who understand, or seeking professional counseling, reaching out is an act of strength, not weakness.

Your grief is valid. Your loss matters. And your healing will happen at your own pace. We're here to support you every step of the way.

With compassion and care."""


# ============================================================================
# SUPPORT INSIGHTS API - Context-aware insight generation
# ============================================================================

def _determine_user_phase(user_id: int) -> tuple[str, dict]:
    """
    Determine user's current phase: pregnancy, postpartum, or loss.
    Returns (phase, relevant_data).
    Uses existing helper functions for consistency.
    """
    try:
        from ai.utils.db import get_connection, get_user_profile, get_active_journey
        
        profile = get_user_profile(user_id)
        if not profile:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found")
        
        # Gate on the Pregnancy & Postpartum journey being active - without this,
        # orphaned rows in postpartum_recoveries/user_pregnancies from a deactivated
        # or never-linked journey get surfaced as if the journey were live.
        if not get_active_journey(user_id, "Pregnancy & Postpartum"):
            return ("unknown", {})
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # DEBUG
            print(f"[PHASE_DEBUG] Checking phase for user {user_id}")
            
            # PRIORITY 1: Check for postpartum data from NEW postpartum_recoveries table
            cursor.execute("""
                SELECT delivery_date, current_week
                FROM postpartum_recoveries
                WHERE user_id = %s
                ORDER BY delivery_date DESC
                LIMIT 1
            """, (user_id,))
            postpartum = cursor.fetchone()
            print(f"[PHASE_DEBUG] postpartum_recoveries check: {postpartum}")
            
            if postpartum:
                print(f"[PHASE_DEBUG] FOUND in postpartum_recoveries, returning postpartum")
                return ("postpartum", postpartum)
            
            # PRIORITY 1B: Fallback to menstrual_cycles (OLD TABLE) for completed pregnancies
            cursor.execute("""
                SELECT period_end_date as delivery_date, NULL as current_week
                FROM menstrual_cycles
                WHERE user_id = %s AND is_completed = 1 AND period_end_date IS NOT NULL
                ORDER BY period_end_date DESC
                LIMIT 1
            """, (user_id,))
            postpartum_old = cursor.fetchone()
            print(f"[PHASE_DEBUG] menstrual_cycles (is_completed=1) check: {postpartum_old}")
            
            if postpartum_old:
                print(f"[PHASE_DEBUG] FOUND in menstrual_cycles (completed), returning postpartum")
                return ("postpartum", postpartum_old)
            
            # PRIORITY 2: Check for miscarriage in user_pregnancies
            cursor.execute("""
                SELECT status, delivery_date
                FROM user_pregnancies
                WHERE user_id = %s AND status = 'miscarriage'
                ORDER BY delivery_date DESC
                LIMIT 1
            """, (user_id,))
            miscarriage = cursor.fetchone()
            print(f"[PHASE_DEBUG] miscarriage check: {miscarriage}")
            
            if miscarriage:
                print(f"[PHASE_DEBUG] FOUND miscarriage, returning loss")
                return ("loss", {"type": "miscarriage", "date": miscarriage.get("delivery_date")})
            
            # PRIORITY 3: Check for active pregnancy in user_pregnancies (NEW TABLE)
            cursor.execute("""
                SELECT due_date, last_menstrual_period_date, status, id
                FROM user_pregnancies
                WHERE user_id = %s AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
            """, (user_id,))
            pregnancy = cursor.fetchone()
            print(f"[PHASE_DEBUG] active pregnancy check: {pregnancy}")
            
            if pregnancy:
                print(f"[PHASE_DEBUG] FOUND active pregnancy, returning pregnancy")
                return ("pregnancy", pregnancy)
            
            # PRIORITY 4: Fallback to menstrual_cycles (OLD TABLE for backward compatibility)
            # Must match pregnancy_summary() query exactly
            cursor.execute("""
                SELECT NULL as id, NULL as due_date, period_start_date as last_menstrual_period_date, 
                       NULL as status, period_end_date as delivery_date
                FROM menstrual_cycles
                WHERE user_id = %s AND is_completed = 0 AND period_start_date IS NOT NULL
                ORDER BY period_start_date DESC
                LIMIT 1
            """, (user_id,))
            cycle = cursor.fetchone()
            print(f"[PHASE_DEBUG] active cycle (is_completed=0) check: {cycle}")
            
            if cycle:
                print(f"[PHASE_DEBUG] FOUND active cycle, returning pregnancy")
                return ("pregnancy", cycle)
            
            print(f"[PHASE_DEBUG] NO DATA FOUND FOR USER {user_id} - returning unknown")
            return ("unknown", {})
    
    except Exception as e:
        print(f"[ERROR] _determine_user_phase for user {user_id}: {e}")
        import traceback
        traceback.print_exc()
        return ("unknown", {"error": str(e)})


def _generate_pregnancy_insights(pregnancy_data: dict, current_week: int, user_id: int) -> list:
    """Generate AI-POWERED pregnancy insights using Claude.
    
    Claude analyzes:
    - pregnancy_weekly_guides: Week-specific development data (baby_development, your_body, nutrition_focus)
    - health_logs: Symptoms, mood, and warning signs
    - Creates personalized insights per trimester
    """
    insights = []
    
    try:
        from ai.utils.db import get_connection
        from ai.utils.llm_call import llm_call
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # === DEVELOPMENT TRACKER: Fetch and analyze weekly data ===
            cursor.execute("""
                SELECT baby_development, your_body, nutrition_focus, safe_exercise, clinical_warning_signs
                FROM pregnancy_weekly_guides
                WHERE week_number = %s
                LIMIT 1
            """, (current_week,))
            weekly_guide = cursor.fetchone()
            
            # Generate baby development insight (with or without weekly guide data)
            baby_info = weekly_guide.get('baby_development', '') if weekly_guide else ''
            body_info = weekly_guide.get('your_body', '') if weekly_guide else ''
            
            dev_prompt = f"""Generate ONE personalized baby development insight for week {current_week} of pregnancy:

Baby development info: {baby_info if baby_info else 'Use general knowledge of week ' + str(current_week) + ' development'}
Mother's body changes: {body_info if body_info else 'Use general knowledge of week ' + str(current_week) + ' changes'}

Create a brief, empowering insight (2-3 sentences) about what's happening with baby and mother this week.
Make it personal, warm, and exciting. Mention specific pregnancy milestones if you know them for this week.
Format: Just the insight text, no labels."""
            
            dev_content = llm_call(dev_prompt, max_tokens=200)
            
            insights.append({
                "type": "baby_development",
                "category": "baby",
                "title": f"Week {current_week}: Baby's Journey",
                "content": dev_content,
                "sentiment": "positive",
                "priority": "high"
            })
            
            # Add care/nutrition guidance
            nutrition_info = weekly_guide.get('nutrition_focus', '') if weekly_guide else ''
            exercise_info = weekly_guide.get('safe_exercise', '') if weekly_guide else ''
            
            care_prompt = f"""Generate ONE pregnancy wellness insight for week {current_week}:

Nutrition focus: {nutrition_info if nutrition_info else 'Use general pregnancy nutrition knowledge for this week'}
Safe exercises: {exercise_info if exercise_info else 'Use general pregnancy exercise knowledge for this week'}

Create brief guidance (2-3 sentences) about nutrition and safe activity this week.
Be practical and encouraging.
Format: Just the insight text, no labels."""
            
            care_content = llm_call(care_prompt, max_tokens=200)
            
            insights.append({
                "type": "care_timeline",
                "category": "clinical",
                "title": "Your Week Ahead: Nutrition & Activity",
                "content": care_content,
                "sentiment": "informative",
                "priority": "high"
            })
            
            # === CLINICAL WARNING ROUTING: AI analyzes symptoms ===
            cursor.execute("""
                SELECT symptoms, log_date
                FROM health_logs
                WHERE user_id = %s AND log_date >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                ORDER BY log_date DESC
                LIMIT 14
            """, (user_id,))
            recent_logs = cursor.fetchall()
            
            if recent_logs:
                symptoms_list = [log.get("symptoms") for log in recent_logs if log.get("symptoms")]
                
                warning_prompt = f"""Analyze her recent pregnancy symptoms and generate ONE clinical insight:

Week: {current_week}
Recent symptoms: {', '.join(symptoms_list[-5:]) if symptoms_list else 'None reported'}

Identify any concerning symptoms (severe bleeding, severe pain, fever, etc.).
Generate insight (2-3 sentences): normalize common pregnancy symptoms, flag severe ones.
If severe symptoms detected: strongly recommend contacting doctor.
Format: Just the insight text, no labels."""
                
                warning_content = llm_call(warning_prompt, max_tokens=200)
                
                concerning = any(risk in str(symptoms_list).lower() for risk in ["bleeding", "severe pain", "fever"])
                
                insights.append({
                    "type": "symptom_analysis",
                    "category": "clinical",
                    "title": "Your Health Status",
                    "content": warning_content,
                    "sentiment": "cautionary" if concerning else "informative",
                    "priority": "critical" if concerning else "medium"
                })
            
            # === EMOTIONAL WELLNESS: AI-personalized ===
            cursor.execute("""
                SELECT mood, log_date
                FROM health_logs
                WHERE user_id = %s AND log_date >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                ORDER BY log_date DESC
                LIMIT 14
            """, (user_id,))
            mood_logs = cursor.fetchall()
            
            if mood_logs:
                mood_scores = [log.get("mood") for log in mood_logs if log.get("mood")]
                mood_avg = sum(mood_scores) / len(mood_scores) if mood_scores else 50
                
                emotional_prompt = f"""Generate ONE empathetic emotional wellness insight for pregnancy week {current_week}:

Trimester: {('First' if current_week < 13 else ('Second' if current_week < 27 else 'Third'))}
Recent mood score average: {mood_avg:.0f}/100
Pregnancy stage: {'Early' if current_week < 13 else ('Mid' if current_week < 27 else 'Final')}

Create brief insight (2-3 sentences) validating her emotions.
Acknowledge pregnancy-related mood changes and encourage self-care.
If mood low (<40): suggest support resources.
Format: Just the insight text, no labels."""
                
                emotional_content = llm_call(emotional_prompt, max_tokens=200)
                
                insights.append({
                    "type": "emotional_support",
                    "category": "emotional",
                    "title": "Your Emotional Wellness",
                    "content": emotional_content,
                    "sentiment": "supportive",
                    "priority": "high" if mood_avg < 40 else "medium"
                })
    
    except Exception as e:
        print(f"[ERROR] _generate_pregnancy_insights for user {user_id}: {e}")
        import traceback
        traceback.print_exc()
    
    # Ensure insights exist
    if not insights:
        insights.append({
            "type": "general",
            "category": "general",
            "title": f"Week {current_week} Support",
            "content": "You're doing great in your pregnancy journey. Continue attending prenatal appointments and trusting your body.",
            "sentiment": "supportive",
            "priority": "medium"
        })
    
    return insights

    return insights


def _generate_postpartum_insights(postpartum_data: dict, postpartum_week: int, recovery_metrics: dict, user_id: int) -> list:
    """Generate AI-POWERED postpartum insights using Claude.
    
    Claude analyzes:
    - Real postpartum_recoveries metrics (physical recovery %, sleep %, energy %)
    - Mood and anxiety screening scores
    - Health logs for symptoms and mood trends
    - Creates personalized recommendations per recovery stage
    """
    insights = []
    
    try:
        from ai.utils.db import get_connection
        from ai.utils.llm_call import llm_call
        from datetime import date
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Gather real data for AI analysis
            physical_recovery = postpartum_data.get("physical_recovery_percent", 0)
            sleep_quality = postpartum_data.get("sleep_quality_percent", 0)
            energy_level = postpartum_data.get("energy_levels_percent", 0)
            mood_stability = postpartum_data.get("mood_stability", 0)
            anxiety_level = postpartum_data.get("anxiety_level", 0)
            
            # Fetch recent health logs for trend analysis
            cursor.execute("""
                SELECT symptoms, mood, energy_level, log_date
                FROM health_logs
                WHERE user_id = %s AND log_date >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                ORDER BY log_date DESC
                LIMIT 14
            """, (user_id,))
            recent_logs = cursor.fetchall()
            
            symptoms_data = []
            mood_scores = []
            for log in recent_logs:
                if log.get("symptoms"):
                    symptoms_data.append(log.get("symptoms"))
                if log.get("mood"):
                    mood_scores.append(log.get("mood"))
            
            # === RECOVERY PROGRESS: AI-generated ===
            try:
                recovery_prompt = f"""Based on this postpartum recovery data, generate ONE empathetic and actionable recovery insight:

WEEK: {postpartum_week}
Physical recovery: {physical_recovery}%
Sleep quality: {sleep_quality}%
Energy level: {energy_level}%

Recent symptoms: {', '.join(symptoms_data[-3:]) if symptoms_data else 'None reported'}

Generate a brief, personalized insight (2-3 sentences) about her physical recovery progress.
Focus on her specific metrics, acknowledge challenges, and give next steps.
Format: Just the insight text, no labels."""
                
                recovery_content = llm_call(recovery_prompt, max_tokens=200)
                
                insights.append({
                    "type": "recovery_progress",
                    "category": "physical",
                    "title": "Your Recovery Progress",
                    "content": recovery_content,
                    "sentiment": "supportive",
                    "priority": "high"
                })
            except Exception as e:
                print(f"[WARNING] recovery_progress generation failed: {e}")
            
            # === MENTAL HEALTH: AI-generated screening ===
            try:
                mental_prompt = f"""Analyze her postpartum mental health and generate ONE supportive insight:

WEEK: {postpartum_week}
Mood stability score: {mood_stability}/100
Anxiety level: {anxiety_level}/100

Recent mood entries: {mood_scores if mood_scores else 'No recent data'}

Generate a brief, empathetic insight (2-3 sentences) about her mental wellness.
If mood is low (<40) or anxiety high (>70): suggest professional support.
If stable: validate her feelings and encourage self-care.
Format: Just the insight text, no labels."""
                
                mental_content = llm_call(mental_prompt, max_tokens=200)
                
                # Determine priority based on actual scores
                mental_priority = "critical" if (mood_stability < 40 or anxiety_level > 70) else "high"
                mental_sentiment = "cautionary" if (mood_stability < 40 or anxiety_level > 70) else "supportive"
                
                insights.append({
                    "type": "mental_wellness",
                    "category": "emotional",
                    "title": "Your Mental Health",
                    "content": mental_content,
                    "sentiment": mental_sentiment,
                    "priority": mental_priority
                })
            except Exception as e:
                print(f"[WARNING] mental_wellness generation failed: {e}")
            
            # === CLINICAL WARNING ROUTING: AI analyzes symptoms ===
            try:
                if symptoms_data:
                    warning_prompt = f"""Analyze these postpartum symptoms and generate ONE clinical insight:

WEEK: {postpartum_week}
Recent symptoms: {', '.join(symptoms_data[-5:])}

Identify any concerning symptoms (fever, heavy bleeding, severe pain, infection signs).
Generate a brief insight (2-3 sentences) about whether she needs medical attention.
If symptoms are severe: strongly recommend contacting doctor.
If mild: normalize symptoms and suggest monitoring.
Format: Just the insight text, no labels."""
                    
                    warning_content = llm_call(warning_prompt, max_tokens=200)
                    
                    # Check if symptoms are concerning
                    concerning = any(risk in str(symptoms_data).lower() for risk in ["fever", "infection", "heavy bleeding", "severe pain"])
                    
                    insights.append({
                        "type": "clinical_insight",
                        "category": "clinical",
                        "title": "Your Health Status",
                        "content": warning_content,
                        "sentiment": "cautionary" if concerning else "informative",
                        "priority": "critical" if concerning else "medium"
                    })
            except Exception as e:
                print(f"[WARNING] clinical_insight generation failed: {e}")
            
            # === ACTIVITY & RECOVERY GUIDANCE: AI-personalized ===
            try:
                activity_prompt = f"""Generate ONE personalized activity recommendation for postpartum recovery:

WEEK: {postpartum_week}
Physical recovery: {physical_recovery}%
Energy level: {energy_level}%
Sleep quality: {sleep_quality}%

Recommend safe activities based on her recovery stage and metrics.
Early recovery (<20%): rest focus. Mid recovery (20-70%): gradual activity. Advanced (70%+): return to normal.
Generate a brief insight (2-3 sentences) with specific activity suggestions.
Format: Just the insight text, no labels."""
                
                activity_content = llm_call(activity_prompt, max_tokens=200)
                
                insights.append({
                    "type": "activity_guidance",
                    "category": "physical",
                    "title": "Your Activity Plan",
                    "content": activity_content,
                    "sentiment": "supportive",
                    "priority": "medium"
                })
            except Exception as e:
                print(f"[WARNING] activity_guidance generation failed: {e}")
    
    except Exception as e:
        print(f"[ERROR] _generate_postpartum_insights for user {user_id}: {e}")
        import traceback
        traceback.print_exc()
    
    # Ensure we always return insights
    if not insights:
        insights.append({
            "type": "recovery_status",
            "category": "physical",
            "title": f"Week {postpartum_week} Recovery",
            "content": "You're doing great. Continue following your healthcare provider's guidance and listen to your body.",
            "sentiment": "supportive",
            "priority": "medium"
        })
    
    return insights


def _generate_loss_insights(user_id: int, loss_data: dict) -> list:
    """Generate AI-POWERED compassionate grief support using Claude.
    
    Claude generates personalized support based on:
    - Time since loss (immediate/acute/processing/healing)
    - Loss type (miscarriage, stillbirth, etc.)
    - User's emotional state and needs
    
    CRITICAL: Never asks clinical questions about baby/outcomes.
    Focus: Pure emotional support, grief validation, healing resources.
    """
    insights = []
    
    try:
        from ai.utils.llm_call import llm_call
        from datetime import date
        
        loss_date = loss_data.get("date")
        loss_type = loss_data.get("type", "miscarriage")
        
        # Calculate timeline stage
        days_since = 0
        if loss_date:
            days_since = (date.today() - loss_date).days
        
        if days_since <= 7:
            timeline_stage = "immediate"
        elif days_since <= 30:
            timeline_stage = "acute"
        elif days_since <= 90:
            timeline_stage = "processing"
        else:
            timeline_stage = "healing"
        
        # === PRIMARY GRIEF SUPPORT ===
        grief_prompt = f"""Generate ONE deeply compassionate grief support message for someone {days_since} days after a pregnancy loss ({loss_type}):

Timeline stage: {timeline_stage} (immediate=0-7 days, acute=7-30 days, processing=30-90 days, healing=90+ days)

Create a brief, empathetic message (3-4 sentences) that:
- Validates her grief completely
- Removes ANY guilt (emphasize she did nothing wrong)
- Acknowledges her pain without minimizing
- Never asks about baby details or clinical outcomes
- Uses warm, human language

Format: Just the message text, no labels."""
        
        grief_content = llm_call(grief_prompt, max_tokens=250)
        
        insights.append({
            "type": "grief_support",
            "category": "emotional",
            "title": "You're Not Alone",
            "content": grief_content,
            "sentiment": "empathetic",
            "priority": "critical"
        })
        
        # === HEALING GUIDANCE ===
        healing_prompt = f"""Generate ONE healing guidance insight for stage '{timeline_stage}' of grief (after {loss_type}):

If immediate/acute: Focus on immediate coping, feeling allowed, reaching out.
If processing: Focus on grief not being linear, processing emotions, self-care.
If healing: Focus on moving forward while honoring loss, future possibilities.

Create brief guidance (3-4 sentences) with 1-2 specific coping strategies.
Never minimize her grief or push her to "move on."
Format: Just the insight text, no labels."""
        
        healing_content = llm_call(healing_prompt, max_tokens=250)
        
        insights.append({
            "type": "healing_guidance",
            "category": "emotional",
            "title": "Your Healing Path",
            "content": healing_content,
            "sentiment": "empathetic",
            "priority": "high"
        })
        
        # === PHYSICAL RECOVERY ===
        physical_prompt = f"""Generate ONE insight about physical care after pregnancy loss ({loss_type}):

Create brief guidance (2-3 sentences) about:
- Listening to her body
- Medical follow-up importance  
- Self-care (rest, nutrition)
- Connecting body care to emotional healing

Format: Just the insight text, no labels."""
        
        physical_content = llm_call(physical_prompt, max_tokens=200)
        
        insights.append({
            "type": "physical_care",
            "category": "physical",
            "title": "Caring for Your Body",
            "content": physical_content,
            "sentiment": "supportive",
            "priority": "high"
        })
        
        # === HOPE & FUTURE (stage-appropriate) ===
        if timeline_stage in ["processing", "healing"]:
            hope_prompt = f"""Generate ONE hopeful insight about future after pregnancy loss:

Timeline: {timeline_stage} (processing=30-90 days, healing=90+ days)

Create brief, gentle message (2-3 sentences) about:
- This loss not defining her story
- Future possibilities when ready
- Her strength and resilience
- Never pushing but encouraging hope

Format: Just the insight text, no labels."""
            
            hope_content = llm_call(hope_prompt, max_tokens=200)
            
            insights.append({
                "type": "hope_and_future",
                "category": "emotional",
                "title": "Looking Ahead",
                "content": hope_content,
                "sentiment": "hopeful",
                "priority": "medium"
            })
        
        # === RESOURCES & SUPPORT ===
        resources_prompt = f"""Generate ONE message about grief support resources:

Create brief resource guide (3-4 sentences) listing:
- Hotlines/crisis support
- Support groups for pregnancy loss
- Counseling options
- Online communities
End with warm encouragement to reach out.

Format: Just the message text, no labels."""
        
        resources_content = llm_call(resources_prompt, max_tokens=250)
        
        insights.append({
            "type": "loss_support_resources",
            "category": "emotional",
            "title": "Support & Resources",
            "content": resources_content,
            "sentiment": "supportive",
            "priority": "high"
        })
    
    except Exception as e:
        print(f"[ERROR] _generate_loss_insights for user {user_id}: {e}")
        import traceback
        traceback.print_exc()
        # Fallback
        insights.append({
            "type": "grief_support",
            "category": "emotional",
            "title": "We're Here for You",
            "content": "We're deeply sorry for your loss. Your grief is valid and deserves compassion. You're not alone—please reach out for support when you're ready.",
            "sentiment": "empathetic",
            "priority": "critical"
        })
    
    return insights


def support_insights(user_id: int) -> Dict[str, Any]:
    """
    Generate context-aware support insights based on user's life stage.
    
    Returns personalized insights for:
    - Pregnant users (by week)
    - Postpartum users (by recovery stage)
    - Users experiencing pregnancy loss (empathetic support)
    """
    try:
        from ai.utils.db import get_connection, get_user_profile
        
        # Determine user's phase (already gates on the active journey internally)
        phase, phase_data = _determine_user_phase(user_id)
        
        if phase == "unknown":
            raise HTTPException(
                status_code=404,
                detail=f"User {user_id} is not currently in a tracked pregnancy or postpartum phase."
            )
        
        from ai.utils.db import get_active_journey
        journey = get_active_journey(user_id, "Pregnancy & Postpartum")
        
        # Get current date for calculations
        current_date = date.today()
        insights = []
        meta_data = {
            "user_id": user_id,
            "phase": phase,
            "profile_id": journey["profile_id"] if journey else None,
            "journey_id": journey["journey_id"] if journey else None,
            "journey_title": journey["journey_title"] if journey else None,
        }
        
        # ===== PREGNANCY PHASE =====
        if phase == "pregnancy":
            pregnancy = phase_data
            lmp = pregnancy.get("last_menstrual_period_date") or pregnancy.get("period_start_date")
            
            if lmp:
                current_week = (current_date - lmp).days // 7
            else:
                current_week = 0
            
            meta_data["week"] = current_week
            insights = _generate_pregnancy_insights(pregnancy, current_week, user_id)
        
        # ===== POSTPARTUM PHASE =====
        elif phase == "postpartum":
            delivery_date = phase_data.get("delivery_date")
            
            # Fetch COMPLETE postpartum data with all recovery metrics
            with get_connection() as conn:
                cursor = conn.cursor()
                
                # PRIORITY 1: Try NEW postpartum_recoveries table first
                cursor.execute("""
                    SELECT delivery_date, current_week, physical_recovery_percent, 
                           hormonal_balance_percent, sleep_quality_percent, energy_levels_percent,
                           mood_stability, anxiety_level, screening_name
                    FROM postpartum_recoveries
                    WHERE user_id = %s
                    ORDER BY delivery_date DESC
                    LIMIT 1
                """, (user_id,))
                postpartum = cursor.fetchone()
                
                # If not found, use phase_data from fallback but enrich it
                if not postpartum:
                    postpartum = phase_data
                
                # Use stored week or calculate from delivery date
                if postpartum.get("current_week"):
                    postpartum_week = postpartum.get("current_week")
                elif delivery_date:
                    postpartum_week = ((current_date - delivery_date).days // 7)
                else:
                    postpartum_week = 0
                
                postpartum_week = max(0, min(12, postpartum_week))
                meta_data["week"] = postpartum_week
                
                # Fetch health logs for recovery metrics
                cursor.execute("""
                    SELECT health_logs.mood, health_logs.energy_level, health_logs.log_date
                    FROM health_logs
                    WHERE user_id = %s AND log_date >= %s
                    ORDER BY log_date DESC
                    LIMIT 14
                """, (user_id, delivery_date))
                health_logs = cursor.fetchall()
                
                recovery_metrics = _calculate_recovery_metrics(health_logs, postpartum_week)
            
            insights = _generate_postpartum_insights(postpartum, postpartum_week, recovery_metrics.model_dump() if hasattr(recovery_metrics, 'model_dump') else recovery_metrics, user_id)
        
        # ===== LOSS PHASE =====
        elif phase == "loss":
            meta_data["loss_type"] = phase_data.get("type")
            meta_data["loss_date"] = phase_data.get("date").isoformat() if phase_data.get("date") else None
            insights = _generate_loss_insights(user_id, phase_data)
        
        return {
            **meta_data,
            "insights": insights,
            "generated_at": current_date.isoformat()
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] support_insights failed for user {user_id}: {e}")
        return {"status": "error", "message": str(e), "user_id": user_id}
