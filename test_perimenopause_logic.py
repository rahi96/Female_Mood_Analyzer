"""
Offline unit tests for perimenopause_service.py pure functions.

These functions take plain Python lists/dicts (health_logs, cycles) as input -
no database connection required. This lets us verify all the recent fixes
(mood emoji mapping, symptom key matching, menopause stage fallback, GSM
severity, Pydantic validation) using fabricated data, without touching the
real database.

Run: python test_perimenopause_logic.py
"""

from datetime import date, timedelta

from ai.models.perimenopause_models import ClinicalExport
from ai.services.perimenopause_service import (
    _normalize_symptoms,
    _determine_menopause_stage,
    _determine_cycle_status,
    _build_vasomotor_tracker,
    _build_symptom_matrix,
    _calculate_gsm_health,
    _calculate_symptom_correlations,
    _extract_top_symptoms,
    _get_recommendations,
    MOOD_EMOJI_SCORES,
)


PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        try:
            print(f"[PASS] {name}")
        except UnicodeEncodeError:
            print(f"[PASS] {name.encode('utf-8', errors='replace').decode('utf-8')}")
    else:
        FAIL += 1
        try:
            print(f"[FAIL] {name}" + (f" - {detail}" if detail else ""))
        except UnicodeEncodeError:
            print(f"[FAIL] {name.encode('utf-8', errors='replace').decode('utf-8')}" + (f" - {detail}" if detail else ""))


# ============================================================================
# 1. Mood emoji scoring
# ============================================================================

print("\n--- Mood emoji scoring ---")
check("Known emoji 😊 scores 8", MOOD_EMOJI_SCORES.get("😊") == 8)
check("Known emoji 🙁 scores 3", MOOD_EMOJI_SCORES.get("🙁") == 3)
check("Unseen emoji falls back to 5 via .get default", MOOD_EMOJI_SCORES.get("🤔", 5) == 5)


# ============================================================================
# 2. _normalize_symptoms - list format (real logged data shape)
# ============================================================================

print("\n--- _normalize_symptoms (list format) ---")
symptoms = _normalize_symptoms(["Hot flashes", "Headache", "Insomnia", "Cramps"])
check("hot_flashes key present (plural)", symptoms.get("hot_flashes") == "moderate", str(symptoms))
check("headache key present (singular)", symptoms.get("headache") == "mild", str(symptoms))
check("insomnia key present", symptoms.get("insomnia") == "severe", str(symptoms))
check("cramps key present", symptoms.get("cramps") == "moderate", str(symptoms))

symptoms_singular = _normalize_symptoms(["Hot flash", "Night sweat"])
check("hot_flash (singular variant) maps too", symptoms_singular.get("hot_flash") == "moderate")
check("night_sweat (singular variant) maps too", symptoms_singular.get("night_sweat") == "moderate")

empty = _normalize_symptoms(None)
check("None symptoms returns empty dict", empty == {})

passthrough = _normalize_symptoms({"vaginal_dryness": "moderate", "libido_impact": "mild"})
check("dict format passes through unchanged", passthrough == {"vaginal_dryness": "moderate", "libido_impact": "mild"})


# ============================================================================
# 3. _determine_menopause_stage - all branches
# ============================================================================

print("\n--- _determine_menopause_stage ---")

today = date.today()

# No cycles at all
stage, months = _determine_menopause_stage([])
check("No cycles -> unknown", stage == "unknown" and months is None, f"got {stage}, {months}")

# Postmenopause: last period > 60 months ago
old_cycle = [{"period_end_date": today - timedelta(days=61 * 30), "is_completed": True}]
stage, months = _determine_menopause_stage(old_cycle)
check("61 months since last period -> postmenopause", stage == "postmenopause", f"got {stage}")

# Menopause: 12-59 months since last period
mid_cycle = [{"period_end_date": today - timedelta(days=20 * 30), "is_completed": True}]
stage, months = _determine_menopause_stage(mid_cycle)
check("20 months since last period -> menopause", stage == "menopause", f"got {stage}")

# Insufficient data: <12 months, fewer than 3 completed cycles (mirrors real user 9 case)
low_data_cycle = [{"period_end_date": today - timedelta(days=30), "is_completed": False}]
stage, months = _determine_menopause_stage(low_data_cycle)
check(
    "1 incomplete cycle, 1 month since -> insufficient_data (not fake perimenopause)",
    stage == "insufficient_data",
    f"got {stage}",
)

# Perimenopause: <12 months, >=3 completed cycles, irregular lengths, age >= 35, >=2 supporting symptoms
irregular_cycles = [
    {"period_end_date": today - timedelta(days=10), "is_completed": True},
    {"period_end_date": today - timedelta(days=45), "is_completed": True},
    {"period_end_date": today - timedelta(days=100), "is_completed": True},
]
stage, months = _determine_menopause_stage(irregular_cycles, age=45, supporting_symptom_count=2)
check("3+ completed cycles with irregular gaps -> perimenopause", stage == "perimenopause", f"got {stage}")

# Regular cycles: <12 months, >=3 completed cycles, consistent lengths
regular_cycles = [
    {"period_end_date": today - timedelta(days=1), "is_completed": True},
    {"period_end_date": today - timedelta(days=29), "is_completed": True},
    {"period_end_date": today - timedelta(days=57), "is_completed": True},
]
stage, months = _determine_menopause_stage(regular_cycles)
check("3+ completed cycles with consistent ~28-day gaps -> regular_cycles", stage == "regular_cycles", f"got {stage}")


# ============================================================================
# 4. _get_recommendations - all stage branches produce sensible advice
# ============================================================================

print("\n--- _get_recommendations ---")
check(
    "perimenopause gets cycle-tracking advice",
    "Track cycles" in _get_recommendations("perimenopause", [])[-1],
)
check(
    "menopause gets bone/cardio advice",
    "bone and cardiovascular" in _get_recommendations("menopause", [])[-1],
)
check(
    "insufficient_data gets its own advice (not bone/cardio)",
    "bone and cardiovascular" not in _get_recommendations("insufficient_data", [])[-1],
)
check(
    "regular_cycles gets its own advice (not bone/cardio)",
    "bone and cardiovascular" not in _get_recommendations("regular_cycles", [])[-1],
)


# ============================================================================
# 5. _build_symptom_matrix - entries reflect real logged symptoms
# ============================================================================

print("\n--- _build_symptom_matrix ---")
fake_logs = [
    {
        "log_date": today - timedelta(days=5),
        "mood": "😊",
        "energy_level": "High",
        "symptoms": ["Hot flashes", "Headache", "Brain fog"],
        "notes": "test log 1",
    },
    {
        "log_date": today - timedelta(days=3),
        "mood": "🙁",
        "energy_level": "Very Low",
        "symptoms": ["Night sweats", "Fatigue"],
        "notes": "test log 2",
    },
]
matrix = _build_symptom_matrix(fake_logs, "30d", today - timedelta(days=30), today)
entries = matrix["entries"]
check("2 entries returned", len(entries) == 2, str(len(entries)))
check("entry 1 hot_flash populated (not null)", entries[0]["hot_flash"] == "moderate", str(entries[0]))
check("entry 1 headaches populated (not null)", entries[0]["headaches"] == "mild", str(entries[0]))
check("entry 2 night_sweat populated (not null)", entries[1]["night_sweat"] == "moderate", str(entries[1]))
check(
    "mood stability differs from flat 50 default (real emoji mapping applied)",
    matrix["avg_mood_stability_percent"] != 50,
    str(matrix["avg_mood_stability_percent"]),
)


# ============================================================================
# 6. _calculate_symptom_correlations - real keys produce curated descriptions
# ============================================================================

print("\n--- _calculate_symptom_correlations ---")
correlation_logs = [
    {
        "log_date": today - timedelta(days=i),
        "mood": "🙁",
        "energy_level": "Low",
        "symptoms": ["Hot flashes"],
        "notes": "",
    }
    for i in range(5)
]
correlations = _calculate_symptom_correlations(correlation_logs)
hot_flash_mood = next((c for c in correlations if {c["from"], c["to"]} == {"Hot Flashes", "Mood"}), None)
check("Hot Flashes <-> Mood correlation found", hot_flash_mood is not None, str(correlations))
if hot_flash_mood:
    check(
        "Correlation uses curated description, not generic fallback",
        "occur together" not in hot_flash_mood["description"],
        hot_flash_mood["description"],
    )


# ============================================================================
# 7. _calculate_gsm_health - dict format passthrough (real popup input shape)
# ============================================================================

print("\n--- _calculate_gsm_health ---")
gsm_logs = [
    {
        "log_date": today,
        "symptoms": {
            "vaginal_dryness": "moderate",
            "urinary_frequency": "mild",
            "pelvic_discomfort": "mild",
            "libido_impact": "moderate",
        },
    }
]
gsm = _calculate_gsm_health(gsm_logs)
check("vaginal_dryness reported as moderate", gsm["vaginal_dryness"]["level"] == "moderate", str(gsm))
check("urinary_frequency reported as mild", gsm["urinary_frequency"]["level"] == "mild", str(gsm))

gsm_empty = _calculate_gsm_health([])
check("No logs -> all fields not_reported", all(v["level"] == "not_reported" for v in gsm_empty.values()))


# ============================================================================
# 8. _build_vasomotor_tracker - zero-event edge case (Pydantic ge=0 fix)
# ============================================================================

print("\n--- _build_vasomotor_tracker (zero events) ---")
no_vasomotor_logs = [
    {"log_date": today, "symptoms": ["Cramps"], "notes": "", "mood": "😊", "energy_level": "High"}
]
vasomotor = _build_vasomotor_tracker(no_vasomotor_logs, "30d", today - timedelta(days=30), today)
check("Zero hot flash events -> avg_severity is 0 (not crashing)", vasomotor["avg_severity"] == 0, str(vasomotor))
check("total_events is 0", vasomotor["total_events"] == 0)


# ============================================================================
# 9. _extract_top_symptoms - mood/energy tracked distinctly (not merged bucket)
# ============================================================================

print("\n--- _extract_top_symptoms ---")
mixed_logs = [
    {"log_date": today, "symptoms": ["Cramps"], "mood": "😊", "energy_level": "High"},
    {"log_date": today, "symptoms": ["Cramps"], "mood": "🙁", "energy_level": "Low"},
]
top = _extract_top_symptoms(mixed_logs)
check(
    "Distinct mood values tracked separately, not one 'mood_changes' bucket",
    "mood_changes" not in top,
    str(top),
)


# ============================================================================
# 10. _determine_menopause_stage - boundary dates (exactly 12mo / 60mo)
# ============================================================================

print("\n--- _determine_menopause_stage (boundary dates) ---")

# Exactly 12 months (360 days) since last period -> should be "menopause" (12 <= months < 60)
boundary_12mo = [{"period_end_date": today - timedelta(days=360), "is_completed": True}]
stage, months = _determine_menopause_stage(boundary_12mo)
check("Exactly 12 months -> menopause (boundary inclusive)", stage == "menopause", f"got {stage}, months={months}")

# Exactly 60 months (1800 days) since last period -> should be "postmenopause" (months >= 60)
boundary_60mo = [{"period_end_date": today - timedelta(days=1800), "is_completed": True}]
stage, months = _determine_menopause_stage(boundary_60mo)
check("Exactly 60 months -> postmenopause (boundary inclusive)", stage == "postmenopause", f"got {stage}, months={months}")

# Exactly 11 months + 3 completed regular cycles -> regular_cycles, not menopause
boundary_11mo_regular = [
    {"period_end_date": today - timedelta(days=330), "is_completed": True},
    {"period_end_date": today - timedelta(days=358), "is_completed": True},
    {"period_end_date": today - timedelta(days=386), "is_completed": True},
]
stage, months = _determine_menopause_stage(boundary_11mo_regular)
check("Just under 12 months with regular cycles -> regular_cycles", stage == "regular_cycles", f"got {stage}")


# ============================================================================
# 11. Multiple different simulated users - verify per-user personalization
# ============================================================================

print("\n--- Multiple simulated users (personalization check) ---")

user_a_logs = [
    {"log_date": today - timedelta(days=2), "mood": "😊", "energy_level": "Very High",
     "symptoms": ["Fatigue"], "notes": ""},
]
user_b_logs = [
    {"log_date": today - timedelta(days=2), "mood": "😢", "energy_level": "Very Low",
     "symptoms": ["Insomnia", "Hot flashes", "Headache"], "notes": ""},
]

matrix_a = _build_symptom_matrix(user_a_logs, "30d", today - timedelta(days=30), today)
matrix_b = _build_symptom_matrix(user_b_logs, "30d", today - timedelta(days=30), today)

check(
    "Different users produce different mood_stability scores",
    matrix_a["avg_mood_stability_percent"] != matrix_b["avg_mood_stability_percent"],
    f"A={matrix_a['avg_mood_stability_percent']}, B={matrix_b['avg_mood_stability_percent']}",
)
check(
    "Different users produce different energy scores",
    matrix_a["avg_energy_level_percent"] != matrix_b["avg_energy_level_percent"],
    f"A={matrix_a['avg_energy_level_percent']}, B={matrix_b['avg_energy_level_percent']}",
)
check(
    "User A (happy, low symptoms) scores higher mood stability than User B (sad, more symptoms)",
    matrix_a["avg_mood_stability_percent"] > matrix_b["avg_mood_stability_percent"],
    f"A={matrix_a['avg_mood_stability_percent']}, B={matrix_b['avg_mood_stability_percent']}",
)


# ============================================================================
# 12. ClinicalExport model validation - the exact crash scenario we fixed
# ============================================================================

print("\n--- ClinicalExport Pydantic validation (previous crash scenario) ---")

try:
    export = ClinicalExport(
        export_date="Sep 30, 2026",
        period_covered="Aug 09 - Sep 30, 2026",
        menopause_stage="insufficient_data",
        months_since_onset=None,
        months_since_last_period=1,
        vasomotor_events_total=0,
        vasomotor_avg_frequency_per_day=0.0,
        vasomotor_avg_severity=0.0,  # this used to violate ge=1 and crash silently
        vasomotor_trend="stable",
        vasomotor_primary_triggers=[],
        primary_symptoms=["cramps", "headache"],
        symptom_severity_breakdown={"cramps": "moderate"},
        avg_sleep_hours=7.0,
        sleep_quality="fair",
        avg_mood_stability=60,
        weight_change_lbs=None,
        clinical_recommendations=["Schedule follow-up"],
        lifestyle_recommendations=["Maintain sleep schedule"],
        warning_flags=[],
        suggested_tests=["FSH"],
        data_points_collected=2,
        data_completeness_percent=3,
    )
    check("vasomotor_avg_severity=0 no longer raises ValidationError", True)
except Exception as e:
    check("vasomotor_avg_severity=0 no longer raises ValidationError", False, str(e))

try:
    ClinicalExport(
        export_date="Sep 30, 2026",
        period_covered="Aug 09 - Sep 30, 2026",
        menopause_stage="insufficient_data",
        months_since_onset=None,
        months_since_last_period=1,
        vasomotor_events_total=0,
        vasomotor_avg_frequency_per_day=0.0,
        vasomotor_avg_severity=0.0,
        vasomotor_trend="stable",
        vasomotor_primary_triggers=[],
        primary_symptoms=[],
        symptom_severity_breakdown={},
        avg_sleep_hours=7.0,
        sleep_quality="fair",
        avg_mood_stability=60,
        weight_change_lbs=None,
        clinical_recommendations=[],
        lifestyle_recommendations=[],
        warning_flags=[],
        suggested_tests=[],
        data_points_collected=1,
        data_completeness_percent=150,  # out-of-range value should still fail validation
    )
    check("data_completeness_percent=150 correctly rejected by ge=0,le=100 constraint", False)
except Exception:
    check("data_completeness_percent=150 correctly rejected by ge=0,le=100 constraint", True)


# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "=" * 60)
print(f"TOTAL: {PASS + FAIL}  PASSED: {PASS}  FAILED: {FAIL}")
print("=" * 60)

if FAIL > 0:
    raise SystemExit(1)
