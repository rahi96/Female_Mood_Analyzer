# Lifelong Thriving — Reminders Feature: Current Status & Required Improvements

Scope: `/api/v1/lifelong-thriving/reminders`, `/preventative-reminders`, `/mobility-stress-indicators`
Service: `RemindersService` in [ai/services/lifelong_thriving_service.py](ai/services/lifelong_thriving_service.py)
Models: [ai/models/lifelong_thriving_models.py](ai/models/lifelong_thriving_models.py)

Response JSON structure is final and should not change. This document tracks only the backing data quality.

---

## 1. Preventative Health Reminders section

**Endpoint field:** `reminders[]`, `summary`

### Current state
- Screening rules (Mammogram, Bone Density Scan, Colonoscopy, Pap Smear, Blood Pressure, Cholesterol Panel, Skin Cancer Check, Eye Exam, Dental Checkup) are hardcoded in `SCREENING_GUIDELINES` — this is intentional (static medical guideline table, not user data) and does not need to change.
- Status (Overdue / Due Soon / Scheduled / Up to Date) is computed dynamically per user from `_get_last_screening_date()` querying `lab_reports`.
- Response is technically dynamic per `user_id`, but currently returns the same result for most users because of the bugs below.

### 🔴 Bug: user age is never read correctly
`_get_user_profile()` queries:
```sql
SELECT u.id, u.date_of_birth, p.activity_level, p.life_stage, p.age_group
FROM users u JOIN profiles p ON u.id = p.user_id WHERE u.id = %s
```
None of `u.date_of_birth`, `p.activity_level`, `p.life_stage`, `p.age_group` exist in the real schema. The real age column is `profiles.age` (int). This query fails silently (caught by a blanket `except: return {}`), so `_get_user_age()` always falls back to the hardcoded default of **40** for every user — meaning screening eligibility (e.g. Mammogram 40+, Bone Density 50+) is calculated with the same fake age for everyone.

**Fix required:** rewrite the query to select `p.age` directly from `profiles`.

### 🔴 Gap: gender/sex is not enforced
`SCREENING_GUIDELINES` has an `"apply_to": "female"` field for Mammogram and Pap Smear, but `_is_screening_applicable()` only checks age — it never checks sex. Confirmed via full database column search: **no `gender`/`sex` column exists anywhere in the 106-table schema.** This means male-only or female-only screenings currently show for all users regardless of applicability.

**Fix required:** add a gender/sex column to `users` or `profiles` (schema change, not a code-only fix), then update `_is_screening_applicable()` to check it.

### ⚠️ Data sparsity
`lab_reports` currently has only 1 row total across all 45 users. Even after the age-query fix, most users will still show `NOT_STARTED` for every screening until real lab/screening history is logged.

### 🟢 Unused resource: `preventative_reminder_snapshots` table
A dedicated snapshot table already exists with a `reminders` (JSON) and `summary` (JSON) column that matches the response shape almost exactly, populated by `last_updated_ai`. It currently has **0 rows** — nothing populates it yet. If a separate job is meant to precompute this, it isn't running. Not currently read by this service.

---

## 2. Mobility & Strength Trends section

**Endpoint field:** `indicators[]` (Hip Flexibility, Grip Strength, Balance Score, Posture Alignment), `overall_mobility_score`, `overall_stress_status`

### Current state
Each of the 4 scores is computed by `_calculate_hip_flexibility_score()`, `_calculate_grip_strength_score()`, `_calculate_balance_score()`, `_calculate_posture_score()` via keyword search against `health_logs.notes` (e.g. `LIKE '%stretch%'`, `LIKE '%yoga%'`) in the last 30 days.

### 🔴 Bug: near-universal fallback to hardcoded values
Because free-text notes almost never contain these exact keyword substrings, `log_count` is virtually always 0, so every user falls through to the hardcoded baseline:
```
Hip Flexibility: 70   Grip Strength: 72   Balance Score: 75   Posture Alignment: 73
```
All labeled `"good"`. Confirmed this is not a deployment/caching issue — verified against 3 different users (2, 9, 18), all returning identical scores.

### 🔴 Deeper problem: no real data source exists for these 4 metrics, even with more data
Investigated all plausible sources:
- `health_logs.notes` — free text, unreliable, effectively unused signal
- `terra_activity_data` (Terra API aggregator over Fitbit/Apple Health/etc.) — full payload schemas inspected for all 3 `type` values (`body`, `daily`, `sleep`). Contains real fields: heart rate, HRV, VO2max, sleep hours/quality/readiness, activity/inactivity seconds, distance, elevation, `total_stress_score_v2`, blood pressure, glucose, body composition. **None of these fields represent grip strength, hip flexibility, balance, or posture** — no wearable in this integration can physically measure them.
- `mobility_stress_snapshots` table — exists, matches response shape, but its 1 existing row contains the *same fallback values* (70/72/75/73), meaning whatever process populates it has the identical flaw.

**Conclusion:** This is not a "wait for more data" situation. More `health_logs` volume or more `terra_activity_data` records will not produce real values for these 4 specific metrics, because no integrated data source measures them. This is a product/data-requirements gap, not a bug that self-resolves.

### Two ways forward (decision needed, not yet implemented)
1. **Replace the 4 metric names** with ones Terra's real fields can honestly support — e.g. Activity Level (`active_durations_data.activity_seconds`), Recovery Score (`readiness_data.readiness`), Sleep Quality (`sleep.hours`/`quality`), Stress Index (`data_enrichment.total_stress_score_v2`). This would make the section genuinely dynamic and personalized using data that already exists.
2. **Keep the current 4 metric names** but treat them as requiring a new data source not yet integrated (e.g. a manual self-assessment form, or a dedicated fitness-test device/integration). Until that exists, this section cannot be made truthfully personalized.

---

## Summary table

| Section | Personalizes today? | Will personalize after more data alone? | Needs code fix? | Needs schema change? |
|---|---|---|---|---|
| Reminders — screening status | No (age always defaults to 40) | No | ✅ Yes (`_get_user_profile()` query) | No |
| Reminders — gender-gated screenings | No (unenforced) | No | ✅ Yes | ✅ Yes (add gender/sex column) |
| Reminders — last screening date | Partially (query is correct) | ✅ Yes, once `lab_reports` has data | No | No |
| Mobility — Hip Flexibility / Grip Strength / Balance / Posture | No (fallback constants) | ❌ No — no data source measures these | Product decision required | Possibly (new data source) |

---

*Investigation performed 2026-09-29 – 2026-09-30. No code changes have been made to `RemindersService` as part of this investigation — findings only.*
