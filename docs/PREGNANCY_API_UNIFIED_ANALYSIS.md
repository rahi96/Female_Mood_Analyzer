# Pregnancy & Postpartum API - Unified Design Analysis

## 📱 UI Requirements Analysis
Based on the UI screenshots you provided, the app shows:

### Tab 1: Pregnancy (Overview)
- **Week 24** (Second Trimester)
- Due date & countdown
- Current status & alerts
- Recovery metrics (charts)
- Quick navigation tabs

### Tab 2: Postpartum (Recovery)
- **Week 6** (Postpartum recovery)
- Recovery metrics (72%, 58%, 45%, 61%)
- Mental health check-in
- Care community support
- Support groups listed

### Key UI Elements Needed:
1. **Current Week Display** ✅
2. **Trimester Info** ✅
3. **Due Date Countdown** ✅
4. **Health Status/Alerts** ✅
5. **Clinical Monitoring Schedule** → **NEEDS UNIFICATION**
6. **Next 5 Tests Only** (not all tests)

---

## ❌ Current API Problem

### Issue: Inconsistent Clinical Test Responses

**Endpoint 1: `/pregnancy/summary?user_id=6`**
```json
{
  "is_pregnant": true,
  "current_week": 7,
  "current_trimester": "First",
  "due_date": "2027-05-16",
  "days_until_due": 230,
  "alerts": [...]
  // ❌ MISSING: clinical_monitoring tests
}
```

**Endpoint 2: `/pregnancy/milestones?user_id=6`**
```json
{
  "week": 7,
  "trimester": "First",
  "baby_development": "...",
  "your_body": "...",
  "nutrition_focus": "...",
  "safe_exercises": "...",
  "clinical_monitoring": [
    // ✅ HAS TESTS but shows all tests from this milestone week
    {"name": "Confirm Pregnancy", "week": "W8", "date": "Nov 5"},
    {"name": "Ultrasound", "week": "W8", "date": "Nov 5"}
  ],
  "clinical_warning_signs": "..."
}
```

**Endpoint 3: `/pregnancy/clinical-timeline?user_id=6`**
```json
{
  "week": 7,
  "trimester": "First",
  "clinical_tests": [
    // ❌ DIFFERENT FIELD NAME: "clinical_tests" not "clinical_monitoring"
    // ❌ SHOWS ALL 14 TESTS from entire pregnancy
    {"name": "Baseline Visit", "week": "W0", "date": "Sep 24"},
    {"name": "Confirm Pregnancy", "week": "W8", "date": "Nov 5"},
    // ... ALL 14 tests included
  ],
  "clinical_warning_signs": "..."
}
```

### Problems Identified:
1. **Inconsistent field names**: `clinical_tests` vs `clinical_monitoring`
2. **Inconsistent data**: summary has no tests, milestones has week tests, timeline has all tests
3. **Too many tests**: 14 tests shown, UI only needs next 5
4. **Different formats**: Each endpoint returns different structure

---

## ✅ Solution: Unified API Response

### New Unified Structure

All three endpoints will now return:
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
  "clinical_monitoring": [
    // ✅ UNIFIED: Always shows next 5 major tests
    // ✅ CONSISTENT: Same field name in all endpoints
    // ✅ SMART: Filters by current week
    {
      "name": "Confirm Pregnancy",
      "week": "W8",
      "date": "Week 8"
    },
    {
      "name": "Ultrasound",
      "week": "W8",
      "date": "Week 8"
    },
    {
      "name": "First Trimester Screening",
      "week": "W12",
      "date": "Week 12"
    },
    {
      "name": "Nuchal Ultrasound",
      "week": "W12",
      "date": "Week 12"
    },
    {
      "name": "Quad Screen",
      "week": "W16",
      "date": "Week 16"
    }
  ],
  "baby_development": "...",
  "your_body": "...",
  "nutrition_focus": "...",
  "safe_exercises": "...",
  "clinical_warning_signs": "..."
}
```

### Key Improvements:

| Aspect | Before | After |
|--------|--------|-------|
| **Field Name** | `clinical_tests` / `clinical_monitoring` (inconsistent) | `clinical_monitoring` (unified) |
| **# of Tests** | 0-14 tests (inconsistent) | Always 5 tests (predictable) |
| **Test Selection** | All/none/some | Next 5 upcoming + recent |
| **Summary Endpoint** | ❌ No tests | ✅ Includes next 5 |
| **Milestones Endpoint** | ⚠️ Only week tests | ✅ Next 5 global tests |
| **Timeline Endpoint** | ⚠️ All 14 tests | ✅ Next 5 global tests |

---

## 🔧 Implementation Details

### New Helper Function Added
**Function**: `_get_next_5_clinical_tests(current_week: int) -> list`

**Logic**:
1. Create ordered list of all 14 clinical tests with weeks (0, 8, 8, 12, 12, 16, 16, 20, 24, 24, 28, 32, 36, 40)
2. Filter tests where `test_week >= current_week` (upcoming tests)
3. Take first 5 upcoming tests
4. If fewer than 5 upcoming, add recent past tests to fill gap
5. Return formatted list with name, week, and date

**Example for Week 7**:
- Upcoming tests: W8, W8, W12, W12, W16 ✅ (all 5 found)
- Returns first 5 in order

**Example for Week 39**:
- Upcoming tests: W40 (only 1)
- Past tests (most recent): W36, W32, W28, W24 ✅ (fill remaining 4)
- Returns: W24, W24, W28, W32, W36, W40 (last 5)

### Modified Endpoints

#### 1. `/pregnancy/summary?user_id=X`
**Changes**:
- ✅ Added `clinical_monitoring` field with next 5 tests
- Model updated: `PregnancySummary` now includes `clinical_monitoring`
- Calls `_get_next_5_clinical_tests(current_week)`

#### 2. `/pregnancy/milestones?user_id=X`
**Changes**:
- ✅ Changed from showing all tests in current milestone week to showing next 5 global tests
- Updated `clinical_monitoring` to use `_get_next_5_clinical_tests()` instead of `data.get("clinical_tests")`
- Model remains: `PregnancyMilestones` (field clarified to show next 5)

#### 3. `/pregnancy/clinical-timeline?user_id=X`
**Changes**:
- ✅ Changed field name from `clinical_tests` → `clinical_monitoring`
- ✅ Changed from all 14 tests → only next 5 tests
- Calls `_get_next_5_clinical_tests()` instead of aggregating all milestone tests

---

## 📊 API Endpoint Comparison

### Before Unification
```
GET /pregnancy/summary?user_id=6
├── Response: Basic info + alerts
├── clinical_monitoring: ❌ MISSING
└── Format: PregnancySummary

GET /pregnancy/milestones?user_id=6
├── Response: Milestones + tests from this week only
├── clinical_monitoring: ⚠️ [2 tests] (only W8 tests)
└── Format: PregnancyMilestones

GET /pregnancy/clinical-timeline?user_id=6
├── Response: All tests across entire pregnancy
├── clinical_tests: ⚠️ [14 tests] (ALL tests)
└── Format: Dictionary (different schema)
```

### After Unification
```
GET /pregnancy/summary?user_id=6
├── Response: Basic info + alerts + next 5 tests
├── clinical_monitoring: ✅ [5 tests] (unified)
└── Format: PregnancySummary

GET /pregnancy/milestones?user_id=6
├── Response: Milestones + next 5 upcoming tests
├── clinical_monitoring: ✅ [5 tests] (unified)
└── Format: PregnancyMilestones

GET /pregnancy/clinical-timeline?user_id=6
├── Response: Next 5 major tests (unified with other endpoints)
├── clinical_monitoring: ✅ [5 tests] (unified)
└── Format: PregnancyMilestones (consistent schema)
```

---

## 🧪 Test Expectations

### Week 7 User (like your user_id=6)
```
Current: Week 7, First Trimester
Due Date: 2027-05-16 (230 days away)

Next 5 Clinical Tests:
1. Confirm Pregnancy (W8) - Nov 5
2. Ultrasound (W8) - Nov 5
3. First Trimester Screening (W12) - Nov 12
4. Nuchal Ultrasound (W12) - Nov 12
5. Quad Screen (W16) - Nov 19
```

### Week 24 User
```
Current: Week 24, Second Trimester
Due Date: 2027-01-15 (estimated)

Next 5 Clinical Tests:
1. Full Blood Count (W24) - Nov 8
2. Anti-D Injection (W28) - Dec 6
3. Growth Scan (W32) - Jan 3
4. GBS Swab & Birth Plan (W36) - Jan 31
5. Delivery Prep (W40) - Mar 15
```

### Week 40+ User (Near Delivery)
```
Current: Week 40+, Third Trimester (At Term)
Due Date: Today or Past

Next 5 Clinical Tests:
1. Delivery Prep (W40) - Mar 15
2. GBS Swab & Birth Plan (W36) - Jan 31
3. Growth Scan (W32) - Jan 3
4. Anti-D Injection (W28) - Dec 6
5. Full Blood Count (W24) - Nov 8
(Shows recent past + delivery prep)
```

---

## 📝 Summary of Changes

### Files Modified:
1. **`ai/services/pregnancy_service.py`**
   - Added `_get_next_5_clinical_tests()` helper function
   - Updated `pregnancy_summary()` to include clinical_monitoring
   - Updated `pregnancy_milestones()` to use unified next 5 tests
   - Updated `pregnancy_clinical_timeline()` to return only next 5 tests

2. **`ai/models/pregnancy_models.py`**
   - Updated `PregnancySummary` model to include `clinical_monitoring` field
   - Updated `PregnancyMilestones` model to clarify `clinical_monitoring` is next 5 tests

### Benefits:
✅ **Consistency**: All endpoints use same `clinical_monitoring` field
✅ **Simplicity**: UI always gets exactly 5 tests (predictable)
✅ **Smartness**: Automatically shows upcoming tests relevant to current week
✅ **Completeness**: summary endpoint now has clinical data
✅ **User-Friendly**: Reduces information overload (5 tests instead of 14)

---

## 🚀 Next Steps

### Testing:
1. Test `/pregnancy/summary?user_id=6` (Week 7)
   - Should now include next 5 clinical tests
   
2. Test `/pregnancy/milestones?user_id=6` (Week 7)
   - Should show same next 5 tests as summary
   
3. Test `/pregnancy/clinical-timeline?user_id=6` (Week 7)
   - Should show same next 5 tests + milestones data

4. Test with different weeks (16, 24, 32, 40) to verify filtering

### UI Integration:
- Display `clinical_monitoring` array in pregnancy dashboard
- Show as clickable/expandable test items
- Each test shows name, week, and calculated date
- Total of 5 tests keeps UI clean and focused

---

## 📌 Notes for Backend Team

1. **Date Calculation**: Currently returning week notation (e.g., "Week 8"). To make it more accurate, calculate actual dates from `menstrual_cycles.period_start_date`:
   ```python
   test_date = pregnancy_start + timedelta(weeks=test_week)
   ```

2. **Test Sorting**: Tests are already sorted chronologically (earliest first in upcoming, latest first in past)

3. **Edge Cases**:
   - Week < 0: Returns first 5 tests (baseline through anatomy scan)
   - Week > 40: Returns last 5 tests (delivery-focused)
   - Week in middle (e.g., 20): Shows next 5 from week 20 onward

4. **Optional Enhancement**: Could add test status (upcoming, passed, pending)
   ```python
   {
     "name": "Confirm Pregnancy",
     "week": "W8",
     "date": "Nov 5",
     "status": "upcoming"  # or "completed", "pending"
   }
   ```
