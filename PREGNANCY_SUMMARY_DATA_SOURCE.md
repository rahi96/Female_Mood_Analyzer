# Pregnancy Summary API - Data Source Documentation

## 📡 API Endpoint Updated
```
GET /api/v1/pregnancy/summary?user_id=6
```

## 📊 Response Structure (New)

```json
{
  "is_pregnant": true,
  "current_week": 7,
  "current_trimester": "First",
  "due_date": "2027-05-16",
  "days_until_due": 230,
  "last_prenatal_visit": null,
  "next_appointment": null,
  "health_status": "good",
  "alerts": [...],
  
  "baby_development": "Heart forming and beating. Limb buds are visible. Neural tube is closing to form the brain and spinal cord.",
  "your_body": "Morning sickness may start. Fatigue and breast tenderness are common. You might notice food aversions.",
  "nutrition_focus": "Protein 70g/day, Calcium 1000mg/day essential. Eat eggs, nuts, and yogurt. Avoid high-mercury fish.",
  "safe_exercises": "Walking, swimming, and prenatal yoga are safe. Avoid high-impact activities.",
  
  "clinical_monitoring": [
    {"name": "Confirm Pregnancy", "week": "W8", "date": "Week 8"},
    {"name": "Ultrasound", "week": "W8", "date": "Week 8"},
    {"name": "First Trimester Screening", "week": "W12", "date": "Week 12"},
    {"name": "Nuchal Ultrasound", "week": "W12", "date": "Week 12"},
    {"name": "Quad Screen", "week": "W16", "date": "Week 16"}
  ]
}
```

---

## 🔄 Data Flow

### Step 1: Get User's Current Pregnancy Week
**Source**: `menstrual_cycles` table (DATABASE)
```sql
SELECT period_start_date, period_end_date
FROM menstrual_cycles
WHERE user_id = 6 AND is_completed = 0
LIMIT 1
```
**Result**: `period_start_date = 2026-09-20`

### Step 2: Calculate Current Week
**Calculation**: `(today - period_start_date) / 7`
```python
current_date = 2026-09-28
pregnancy_start = 2026-09-20
current_week = (2026-09-28 - 2026-09-20).days // 7 = 1 week (approx 7 days)
```
**Result**: `current_week = 1`

### Step 3: Find Closest Milestone Week
**Source**: Hardcoded milestone weeks in code
```python
available_weeks = [0, 8, 12, 16, 20, 24, 28, 32, 36, 40]
closest_week = min(available_weeks, key=lambda x: abs(x - current_week))
# Closest to week 1 is week 0
```
**Result**: `milestone_week = 0` (closest to week 1)

### Step 4: Get Personalized Milestone Data
**Source**: `PREGNANCY_MILESTONES_DATA` dict (HARDCODED IN CODE)
```python
milestone_data = PREGNANCY_MILESTONES_DATA[0]
# Returns all narrative content for week 0:
{
  "baby": "Conception begins. Sperm fertilizes egg and cell division starts rapidly.",
  "body": "No visible changes yet. Implantation occurs in uterine lining.",
  "nutrition": "Start prenatal vitamins with folic acid. Aim for balanced diet with leafy greens and dairy.",
  "exercises": "Continue your normal routine. Walking, yoga, and swimming are all safe.",
  "clinical_tests": [...],
  "warning_signs": "..."
}
```

### Step 5: Build Summary Response
**Combine**:
- User data (week, trimester, due date) from `menstrual_cycles` table
- Personalized milestones from hardcoded `PREGNANCY_MILESTONES_DATA`
- Alerts from generation logic
- Clinical tests from helper function

**Result**: Complete PregnancySummary response

---

## 📍 Data Sources Breakdown

| Field | Source | Type | Table/File |
|-------|--------|------|-----------|
| `is_pregnant` | Logic | Calculated | (based on menstrual_cycles) |
| `current_week` | Calculation | `(today - period_start_date) // 7` | `menstrual_cycles.period_start_date` |
| `current_trimester` | Logic | Weeks 0-12 (First), 13-27 (Second), 28+ (Third) | Calculated |
| `due_date` | Calculation | `period_start_date + 280 days` | `menstrual_cycles.period_start_date` |
| `days_until_due` | Calculation | `due_date - today` | Calculated |
| `last_prenatal_visit` | Database | `NULL` | Could be in `health_logs` or custom table |
| `next_appointment` | Database | `NULL` | Could be in `appointments` or custom table |
| `health_status` | Logic | Hardcoded "good" | Calculated (could be from health_logs) |
| `alerts` | Logic | Generated based on week | Calculated |
| **`baby_development`** | **Hardcoded Dict** | **Text narrative** | **`PREGNANCY_MILESTONES_DATA`** |
| **`your_body`** | **Hardcoded Dict** | **Text narrative** | **`PREGNANCY_MILESTONES_DATA`** |
| **`nutrition_focus`** | **Hardcoded Dict** | **Text narrative** | **`PREGNANCY_MILESTONES_DATA`** |
| **`safe_exercises`** | **Hardcoded Dict** | **Text narrative** | **`PREGNANCY_MILESTONES_DATA`** |
| `clinical_monitoring` | Logic | List of tests | Calculated (from PREGNANCY_MILESTONES_DATA) |

---

## 🎯 How It's Personalized

### Dynamic Personalization:
1. **Per User**: Each user's `current_week` is calculated from their unique `period_start_date`
2. **Week-Based**: The milestones shown match the user's actual pregnancy week
3. **Automatic Matching**: System finds closest milestone week (0, 8, 12, 16, 20, 24, 28, 32, 36, 40)

### Example Personalization:
- **User 6** (Week 7) → Milestone Week **8** (closest)
  - Shows: "Heart forming and beating" (week 8 data)
  
- **User X** (Week 15) → Milestone Week **16** (closest)
  - Shows: "Facial features are becoming more defined" (week 16 data)
  
- **User Y** (Week 22) → Milestone Week **20** (closest)
  - Shows: "Baby can swallow and hiccup" (week 20 data)

---

## 📚 Where Data is Stored

### Database Tables (`menstrual_cycles`):
```sql
-- This table stores user pregnancy cycles
SELECT * FROM menstrual_cycles WHERE user_id = 6;

+----+---------+------------------+----------------+----+--------+
| id | user_id | period_start_date| period_end_date| ... | is_completed |
+----+---------+------------------+----------------+----+--------+
| 1  | 6       | 2026-09-20       | NULL           | ... | 0       |
+----+---------+------------------+----------------+----+--------+
```

### Python Code (Hardcoded `PREGNANCY_MILESTONES_DATA`):
```python
# File: ai/services/pregnancy_service.py (Lines 100-200+)
PREGNANCY_MILESTONES_DATA = {
    0: {
        "baby": "Conception begins...",
        "body": "No visible changes...",
        "nutrition": "Start prenatal vitamins...",
        "exercises": "Continue your normal routine...",
        "warning_signs": "Contact your doctor..."
    },
    8: {
        "baby": "Heart forming and beating...",
        "body": "Morning sickness may start...",
        "nutrition": "Protein 70g/day...",
        "exercises": "Walking, swimming...",
        "warning_signs": "Seek care for severe..."
    },
    # ... 12, 16, 20, 24, 28, 32, 36, 40
}
```

---

## 🔧 Code Implementation

### File: `ai/services/pregnancy_service.py`
```python
def pregnancy_summary(user_id: int) -> Dict[str, Any]:
    # Step 1: Get cycle from database
    cursor.execute("""
        SELECT period_start_date, period_end_date
        FROM menstrual_cycles
        WHERE user_id = %s AND is_completed = 0
        LIMIT 1
    """, (user_id,))
    cycle = cursor.fetchone()
    
    # Step 2: Calculate week
    pregnancy_start = cycle.get("period_start_date")
    current_week = (date.today() - pregnancy_start).days // 7
    
    # Step 3: Find closest milestone week
    milestone_week = _find_closest_milestone_week(current_week)
    
    # Step 4: Get personalized data from hardcoded dict
    milestone_data = PREGNANCY_MILESTONES_DATA.get(milestone_week, PREGNANCY_MILESTONES_DATA[20])
    
    # Step 5: Build response
    return PregnancySummary(
        is_pregnant=True,
        current_week=current_week,
        baby_development=milestone_data.get("baby", ""),
        your_body=milestone_data.get("body", ""),
        nutrition_focus=milestone_data.get("nutrition", ""),
        safe_exercises=milestone_data.get("exercises", ""),
        # ... other fields
    ).model_dump()
```

---

## 💡 Optional: Move to Database Table

### Current Approach (✅ Good for MVP)
- **Pros**: Fast, no database calls, simple
- **Cons**: Hardcoded content, difficult to update without code change

### Alternative: Database Table Approach
If you want to make milestones editable without code changes, create a table:

```sql
CREATE TABLE pregnancy_milestones (
    id INT PRIMARY KEY,
    week INT NOT NULL,
    baby_development TEXT,
    your_body TEXT,
    nutrition_focus TEXT,
    safe_exercises TEXT,
    warning_signs TEXT,
    UNIQUE KEY (week)
);

INSERT INTO pregnancy_milestones VALUES
(1, 0, "Conception begins...", "No visible changes...", ...),
(2, 8, "Heart forming...", "Morning sickness...", ...),
...
```

Then query:
```python
cursor.execute("""
    SELECT * FROM pregnancy_milestones 
    WHERE week = %s
""", (milestone_week,))
milestone_data = cursor.fetchone()
```

---

## 📋 Summary

| Aspect | Current | Database Alternative |
|--------|---------|----------------------|
| **Storage** | Hardcoded in Python | `pregnancy_milestones` table |
| **Personalization** | Per-user week matching | Per-user week matching |
| **Update Cost** | Redeploy app | Simple database UPDATE |
| **Query Speed** | No database call | 1 database call per request |
| **Flexibility** | Low (code change needed) | High (update via SQL/API) |
| **Recommendation** | ✅ Use for now | 💡 Consider for future |

---

## 🚀 Test the Updated API

```bash
# User 6 (Week 7 → Milestone Week 8)
curl "http://localhost:8002/api/v1/pregnancy/summary?user_id=6"

# Response includes:
# - current_week: 7
# - baby_development: "Heart forming..." (week 8 data)
# - your_body: "Morning sickness..." (week 8 data)
# - nutrition_focus: "Protein 70g/day..." (week 8 data)
# - safe_exercises: "Walking, swimming..." (week 8 data)
```

---

## 📖 Reference Tables Accessed

1. **`users`** - User account (implicitly via get_user_profile)
2. **`profiles`** - User profile including life_stage_id
3. **`menstrual_cycles`** - Pregnancy cycle data (period_start_date, is_completed)
4. **`pregnancy_test_logs`** - Pregnancy test history (optional, not used in summary)

No table is accessed for the new milestone narrative fields - they come from hardcoded `PREGNANCY_MILESTONES_DATA`.
