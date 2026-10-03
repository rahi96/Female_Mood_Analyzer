"""
Local, no-database test of the perimenopause staging logic using mock data.

Does NOT touch the real DB or insert anything - just calls
_determine_menopause_stage() and _count_supporting_symptoms() directly with
in-memory mock rows shaped like real menstrual_cycles / health_logs records.

Run: python test_perimenopause_mock_local.py
"""
from datetime import date, timedelta

from ai.services.perimenopause_service import (
    _determine_menopause_stage,
    _count_supporting_symptoms,
)

TODAY = date.today()


def make_cycles(gaps_days: list[int]) -> list[dict]:
    """Build completed menstrual_cycles rows counting back from today using
    the given list of gap lengths (days between consecutive period_end_dates).
    """
    cycles = []
    current_end = TODAY - ti
    medelta(days=20)  # last period ended 20 days ago
    cycles.append({"period_end_date": current_end, "is_completed": True})
    for gap in gaps_days:
        current_end = current_end - timedelta(days=gap)
        cycles.append({"period_end_date": current_end, "is_completed": True})
    return cycles


def make_health_logs(symptom_keys: list[str]) -> list[dict]:
    return [{"symptoms": {key: "moderate" for key in symptom_keys}}]


SCENARIOS = [
    {
        "name": "Only 1 cycle, no symptoms (most common real user right now)",
        "cycles": make_cycles([]),
        "age": 45,
        "symptoms": [],
    },
    {
        "name": "3 regular cycles (gaps ~28d), no symptoms",
        "cycles": make_cycles([28, 28]),
        "age": 45,
        "symptoms": [],
    },
    {
        "name": "3 irregular cycles (gaps vary >7d), but NO supporting symptoms",
        "cycles": make_cycles([20, 40]),
        "age": 45,
        "symptoms": [],
    },
    {
        "name": "3 irregular cycles + symptom cluster + plausible age -> should be PERIMENOPAUSE",
        "cycles": make_cycles([20, 40]),
        "age": 45,
        "symptoms": ["hot_flash", "sleep_disruption", "brain_fog"],
    },
    {
        "name": "3 irregular cycles + symptom cluster but age too young -> should NOT be perimenopause",
        "cycles": make_cycles([20, 40]),
        "age": 24,
        "symptoms": ["hot_flash", "sleep_disruption"],
    },
    {
        "name": "12+ months since last period -> should be MENOPAUSE",
        "cycles": [{"period_end_date": TODAY - timedelta(days=400), "is_completed": True}],
        "age": 50,
        "symptoms": [],
    },
    {
        "name": "60+ months since last period -> should be POSTMENOPAUSE",
        "cycles": [{"period_end_date": TODAY - timedelta(days=2000), "is_completed": True}],
        "age": 58,
        "symptoms": [],
    },
]

print("=" * 90)
print("LOCAL MOCK TEST - perimenopause staging logic (no DB, no writes)")
print("=" * 90)

for scenario in SCENARIOS:
    supporting_count = _count_supporting_symptoms(make_health_logs(scenario["symptoms"]))
    stage, months_since = _determine_menopause_stage(
        scenario["cycles"],
        age=scenario["age"],
        supporting_symptom_count=supporting_count,
    )
    print(f"\n▶ {scenario['name']}")
    print(f"   age={scenario['age']}, cycles={len(scenario['cycles'])}, supporting_symptoms={supporting_count}")
    print(f"   => stage='{stage}', months_since_last_period={months_since}")

print("\n" + "=" * 90)
print("Done. Compare 'stage' results above against the expected outcome in each scenario name.")
print("=" * 90)
