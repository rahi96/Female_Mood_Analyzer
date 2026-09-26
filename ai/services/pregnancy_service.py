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
    """Get pregnancy summary for user."""
    try:
        from ai.utils.db import get_connection, get_user_profile
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if user exists
            profile = get_user_profile(user_id)
            if not profile:
                raise HTTPException(status_code=404, detail=f"User {user_id} not found")
            
            # Check if user is in pregnancy life stage
            if profile.get("life_stage_id") != 3:  # 3 = Pregnancy
                raise HTTPException(status_code=404, detail=f"User {user_id} is not currently pregnant")
            
            # Get last positive pregnancy test
            cursor.execute("""
                SELECT test_date 
                FROM pregnancy_test_logs 
                WHERE cycle_id IN (
                    SELECT id FROM menstrual_cycles WHERE user_id = %s
                ) 
                AND result = 'positive'
                ORDER BY test_date DESC
                LIMIT 1
            """, (user_id,))
            test_log = cursor.fetchone()
            
            # Get current cycle/pregnancy period
            cursor.execute("""
                SELECT period_start_date, period_end_date
                FROM menstrual_cycles
                WHERE user_id = %s AND is_completed = 0
                ORDER BY period_start_date DESC
                LIMIT 1
            """, (user_id,))
            cycle = cursor.fetchone()
            
            if not cycle or not cycle.get("period_start_date"):
                return {"is_pregnant": False, "message": "No active pregnancy cycle found"}
            
            # Calculate pregnancy week
            pregnancy_start = cycle.get("period_start_date")
            
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
            
            # Calculate due date
            due_date = pregnancy_start + timedelta(days=280)
            days_until_due = (due_date - current_date).days
            
            # Generate alerts based on week
            alerts = _generate_pregnancy_alerts(current_week, trimester)
            
            return PregnancySummary(
                is_pregnant=True,
                current_week=current_week,
                current_trimester=trimester,
                due_date=due_date.isoformat(),
                days_until_due=max(0, days_until_due),
                last_prenatal_visit=None,
                next_appointment=None,
                health_status="good",
                alerts=alerts
            ).model_dump(exclude_none=False)
    
    except HTTPException:
        raise  # Re-raise HTTPException to propagate to FastAPI
    except Exception as e:
        print(f"[ERROR] pregnancy_summary failed for user {user_id}: {e}")
        return {"status": "error", "message": str(e), "user_id": user_id}


def pregnancy_milestones(user_id: int, week: Optional[int] = None) -> Dict[str, Any]:
    """Get pregnancy milestones for specific week - UI-aligned narrative format."""
    try:
        from ai.utils.db import get_connection, get_user_profile
        
        # Check if user exists
        profile = get_user_profile(user_id)
        if not profile:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found")
        
        if profile.get("life_stage_id") != 3:  # 3 = Pregnancy
            raise HTTPException(status_code=404, detail=f"User {user_id} is not currently pregnant")
        
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
        
        # Parse clinical tests (convert from dict format to ClinicalTest objects)
        from ai.models.pregnancy_models import ClinicalTest
        clinical_tests = [
            ClinicalTest(name=test["name"], week=test["week"], date=test["date"])
            for test in data.get("clinical_tests", [])
        ]
        
        return PregnancyMilestones(
            week=week,
            trimester=trimester,
            baby_development=data.get("baby", ""),
            your_body=data.get("body", ""),
            nutrition_focus=data.get("nutrition", ""),
            safe_exercises=data.get("exercises", ""),
            clinical_monitoring=clinical_tests,
            clinical_warning_signs=data.get("warning_signs", "")
        ).model_dump(exclude_none=False)
    
    except HTTPException:
        raise  # Re-raise HTTPException to propagate to FastAPI
    except Exception as e:
        print(f"[ERROR] pregnancy_milestones failed for user {user_id}, week {week}: {e}")
        return {"status": "error", "message": str(e), "user_id": user_id}


def pregnancy_clinical_timeline(user_id: int, week: Optional[int] = None) -> Dict[str, Any]:
    """Get all clinical tests across entire pregnancy with dates - UI timeline view."""
    try:
        from ai.utils.db import get_connection, get_user_profile
        
        # Check if user exists
        profile = get_user_profile(user_id)
        if not profile:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found")
        
        if profile.get("life_stage_id") != 3:  # 3 = Pregnancy
            raise HTTPException(status_code=404, detail=f"User {user_id} is not currently pregnant")
        
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
        
        # Aggregate all clinical tests from all milestone weeks
        all_clinical_tests = []
        milestone_weeks = [0, 8, 12, 16, 20, 24, 28, 32, 36, 40]
        
        for mweek in milestone_weeks:
            data = PREGNANCY_MILESTONES_DATA.get(mweek, {})
            tests = data.get("clinical_tests", [])
            all_clinical_tests.extend(tests)
        
        # Get warning signs for current week
        milestone_week = _find_closest_milestone_week(week)
        current_data = PREGNANCY_MILESTONES_DATA.get(milestone_week, PREGNANCY_MILESTONES_DATA[20])
        warning_signs = current_data.get("warning_signs", "")
        
        return {
            "week": week,
            "trimester": trimester,
            "clinical_tests": all_clinical_tests,
            "clinical_warning_signs": warning_signs
        }
    
    except HTTPException:
        raise  # Re-raise HTTPException to propagate to FastAPI
    except Exception as e:
        print(f"[ERROR] pregnancy_clinical_timeline failed for user {user_id}, week {week}: {e}")
        return {"status": "error", "message": str(e), "user_id": user_id}


def postpartum_recovery(user_id: int) -> Dict[str, Any]:
    """Get postpartum recovery overview."""
    try:
        from ai.utils.db import get_connection, get_user_profile
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if user exists
            profile = get_user_profile(user_id)
            if not profile:
                raise HTTPException(status_code=404, detail=f"User {user_id} not found")
            
            # Check if user is in postpartum life stage
            if profile.get("life_stage_id") != 4:  # 4 = Postpartum
                raise HTTPException(status_code=404, detail=f"User {user_id} is not postpartum")
            
            # Get completed pregnancy cycle (delivery date)
            cursor.execute("""
                SELECT period_end_date, is_completed
                FROM menstrual_cycles
                WHERE user_id = %s AND is_completed = 1
                ORDER BY period_end_date DESC
                LIMIT 1
            """, (user_id,))
            cycle = cursor.fetchone()
            
            if not cycle or not cycle.get("period_end_date"):
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
                    "message": "No completed pregnancy found"
                }
            
            delivery_date = cycle.get("period_end_date")
            current_date = date.today()
            postpartum_week = (current_date - delivery_date).days // 7
            postpartum_week = max(0, min(12, postpartum_week))
            
            # Fetch health logs for postpartum data
            cursor.execute("""
                SELECT mood, energy_level, symptoms, notes, log_date
                FROM health_logs
                WHERE user_id = %s AND log_date >= %s
                ORDER BY log_date DESC
                LIMIT 14
            """, (user_id, delivery_date))
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
            
            return {
                "days_postpartum": days_postpartum,
                "postpartum_week": postpartum_week,
                "recovery_status": recovery_status,
                "delivery_method": "vaginal",  # Would need separate table to track
                "physical_health": recovery_metrics,
                "mental_health": mental_health,
                "activity_level": POSTPARTUM_ACTIVITIES.get(postpartum_week, "Consult doctor"),
                "alerts": alerts,
                "next_follow_up": (delivery_date + timedelta(days=42)).isoformat()
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
