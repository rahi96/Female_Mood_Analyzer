# Life-Arc Endpoint: Client Requirements & Enhancement Plan

## Current Response Analysis

### ✅ What's Working
- ✅ Endpoint accessible and returns 200 OK
- ✅ JSON structure valid (matches VitalityResponse model)
- ✅ Milestones array populated with menstrual cycle data
- ✅ Timeline summary calculates aggregates

### ❌ What Needs Improvement (WITHOUT Changing JSON Structure)

---

## Enhancement 1: Fill Missing Data Fields

### Current Issue
```json
"health_context": {
  "cycle_day": 1,
  "phase": "follicular",
  "duration": "None days average",    // ❌ Shows "None"
  "progress": null,                    // ❌ null
  "status": null,                      // ❌ null
  "key_findings": null,                // ❌ null
  "goal_progress": null                // ❌ null
}
```

### Solution: Calculate & Populate These Fields

**Without adding new fields, populate existing ones:**

#### `duration` 
- **Current:** "None days average"
- **Should be:** Calculate from menstrual_cycles table
  - Query: `SELECT AVG(duration_days) FROM menstrual_cycles WHERE user_id = ?`
  - Format: "28 days average" (standard cycle length)

#### `progress`
- **Current:** null
- **Should be:** Days into current cycle (0-100%)
  - Example: If cycle is 28 days and today is cycle day 14, progress = 50
  - Formula: `(cycle_day / typical_duration) * 100`

#### `status`
- **Current:** null  
- **Should be:** Health status during this phase
  - "Optimal" (energy peaks during ovulation)
  - "Good" (follicular or luteal)
  - "Caution" (early luteal with low energy)
  - Based on vitality scores + cycle phase

#### `key_findings`
- **Current:** null
- **Should be:** Specific observations about this cycle/phase
  - Examples:
    - "Ovulation detected on cycle day 14"
    - "Cycle 2 days longer than average"
    - "Sleep quality improved in follicular phase"
    - "High energy during ovulation phase"

#### `goal_progress`
- **Current:** null
- **Should be:** Track toward user health goals
  - Examples:
    - "30-min exercise 3/7 days this week"
    - "Sleep target: 7hrs/night, achieved 5/7 nights"
    - "Stress management: meditation 2/4 sessions"

---

## Enhancement 2: Expand Milestone Types

### Current State
**Only detects:** `cycle_start`

### Should Also Detect

#### A. **Vitality Milestones** (Major health events)
```json
{
  "milestone_type": "vitality_surge",
  "title": "Energy Peak Detected",
  "description": "Vitality jumped to 78/100 - excellent recovery period",
  "significance": 0.8,
  "icon": "lightning"
}
```
- Trigger: Vitality index increases 15+ points in a week
- Significance: 0.7-0.9 based on magnitude

#### B. **Phase Transition Milestones**
```json
{
  "milestone_type": "phase_transition",
  "title": "Luteal Phase Begins",
  "description": "Transition to luteal phase. Energy may dip, focus on self-care.",
  "significance": 0.5,
  "icon": "moon"
}
```
- Trigger: Calculated mid-cycle (ovulation typically day 14 of 28-day cycle)
- Significance: 0.5 (regular occurrence)

#### C. **Health Achievement Milestones**
```json
{
  "milestone_type": "health_achievement",
  "title": "7-Day Activity Streak",
  "description": "Completed 7 consecutive days of 30+ min activity",
  "significance": 0.75,
  "icon": "checkmark"
}
```
- Trigger: User meets health goals (activity, sleep, meditation)
- Significance: 0.6-0.9 based on difficulty

#### D. **Symptom Milestones**
```json
{
  "milestone_type": "symptom_resolution",
  "title": "Brain Fog Resolved",
  "description": "No brain fog reports in past 5 days (was daily last week)",
  "significance": 0.6,
  "icon": "clarity"
}
```
- Trigger: Improvement in tracked symptoms
- Significance: 0.5-0.7 based on severity change

#### E. **Cycle Anomaly Milestones**
```json
{
  "milestone_type": "cycle_anomaly",
  "title": "Cycle Length Variation",
  "description": "This cycle 5 days shorter than average - monitor next cycle",
  "significance": 0.4,
  "icon": "alert"
}
```
- Trigger: Cycle deviation > 3 days from average
- Significance: 0.3-0.6 (informational)

---

## Enhancement 3: Improve Significance Scoring

### Current Issue
All milestones show `significance: 0.6` (uniform)

### Solution: Dynamic Significance Calculation

```python
def calculate_significance(milestone_type, context_data):
    base_significance = {
        "cycle_start": 0.5,
        "phase_transition": 0.5,
        "vitality_surge": 0.8,
        "health_achievement": 0.75,
        "symptom_resolution": 0.6,
        "cycle_anomaly": 0.4
    }
    
    score = base_significance.get(milestone_type, 0.5)
    
    # Boost for major improvements
    if context_data.get("vitality_change", 0) > 20:
        score += 0.2
    
    # Reduce for routine events
    if milestone_type == "cycle_start" and user_has_regular_cycles:
        score = 0.4  # Expected, less significant
    
    return min(score, 1.0)
```

**Result:** Significance ranges 0.3-1.0 based on importance to user

---

## Enhancement 4: Add AI Insights to Life-Arc

### Current Response
- Shows milestones and timeline summary
- Missing: `ai_insights` field (mentioned in endpoint but not populated)

### Should Include (using same structure as vitality endpoint)

```json
"ai_insights": {
  "summary": "Your health timeline shows strong cycle regularity with 2 complete cycles documented. Energy levels remain stable across phases, indicating good hormonal balance.",
  "strengths": [
    "Regular menstrual cycles - predictable pattern supports planning",
    "Stable follicular phases - consistent energy foundations",
    "Achievement milestones indicate sustained wellness efforts"
  ],
  "areas_to_focus": [
    "Luteal phase energy management - tracking shows dips",
    "Milestone detection limited to cycle data - expand to symptom tracking",
    "Historical data collection - only 2 months available"
  ],
  "recommendations": [
    "Log daily energy/mood during luteal phase to detect patterns",
    "Schedule important tasks during ovulatory phases (higher energy)",
    "Continue activity tracking - data shows positive correlation with mood"
  ],
  "confidence_score": 75
}
```

**Why populate it:**
- Claude can analyze trends across the timeline
- Provide personalized health guidance based on phase patterns
- Increase engagement with historical insights

---

## Enhancement 5: Richer Timeline Summary

### Current
```json
"timeline_summary": {
  "total_milestones": 1,
  "major_events": 0,
  "avg_monthly_milestones": 1,
  "date_range": {
    "start": "2026-09-18",
    "end": "2026-09-18"
  }
}
```

### Enhanced (without new fields, just populated)

```json
"timeline_summary": {
  "total_milestones": 8,              // All milestone types included
  "major_events": 2,                  // Count milestones with significance > 0.7
  "avg_monthly_milestones": 4,        // (total / months_of_data)
  "date_range": {
    "start": "2026-08-09",            // Earliest data point
    "end": "2026-09-29"               // Most recent
  }
}
```

---

## Enhancement 6: Proper Phase Calculation

### Current Issue
```json
"phase": "ovulatory"  // But cycle_day: 1 (should be follicular)
```

### Solution: Calculate Correct Phase

```python
def calculate_phase(cycle_day, cycle_length=28):
    """Map cycle day to reproductive phase"""
    if 1 <= cycle_day <= 5:
        return "menstrual"
    elif 6 <= cycle_day <= 12:
        return "follicular"
    elif 13 <= cycle_day <= 15:
        return "ovulatory"
    else:
        return "luteal"

# For user with last_period: 2026-09-18
# Today: 2026-09-29
# cycle_day = 11
# phase = "follicular" (not "ovulatory")
```

**Result:** Accurate phase information for better health context

---

## Enhancement 7: Add Data Sources to Milestones

### Current
```json
"milestone_type": "cycle_start"  // No indication where data came from
```

### Solution: Track Data Source (within existing structure)

**Option A:** Use `description` field to mention source
```json
"description": "New menstrual cycle began (from menstrual_cycles table). Phase: follicular."
```

**Option B:** Use `health_context` to track
```json
"health_context": {
  "data_source": "menstrual_cycles",
  ...
}
```

**Result:** Transparency about data quality and source confidence

---

## Implementation Priority

| Priority | Enhancement | Impact | Effort |
|----------|-------------|--------|--------|
| 🔴 HIGH | Fill null health_context fields | User sees complete data | Medium |
| 🔴 HIGH | Expand milestone types | Richer timeline | High |
| 🟡 MEDIUM | Dynamic significance scoring | Better UX prioritization | Low |
| 🟡 MEDIUM | Proper phase calculation | Accuracy improvement | Low |
| 🟡 MEDIUM | AI insights | Personalized guidance | Medium |
| 🟢 LOW | Richer timeline summary | Better overview | Low |

---

## JSON Structure Compliance

**✅ All enhancements maintain current structure:**
- No new root-level fields added
- Existing fields populated intelligently
- health_context fields filled (not new)
- milestone_type expanded (string enum)
- significance calculated dynamically (float 0-1)

**✅ Database query cost:**
- Query menstrual_cycles for cycle length → 1 query
- Query health logs for trends → 1 query
- Calculate phases locally → CPU only

---

## Code Changes Needed

### File: `ai/services/lifelong_thriving_service.py`

**LifeArcService class:**
1. `_detect_milestones()` - Expand from cycle detection to multi-type detection
2. `_calculate_cycle_day()` - New helper to calculate current cycle day
3. `_calculate_phase()` - New helper to map day to phase
4. `_calculate_significance()` - Dynamic scoring
5. `_populate_health_context()` - Fill null fields
6. `get_life_arc_timeline()` - Add AI insights generation

### File: `ai/models/lifelong_thriving_models.py`

**Check:**
- `Milestone` model has all required fields
- `HealthContext` model fields are Optional (allow null initially)
- `LifeArcResponse` has ai_insights field

---

## Expected Output After Enhancement

```json
{
  "milestones": [
    {
      "milestone_date": "2026-09-10",
      "milestone_type": "cycle_start",
      "title": "Menstrual Cycle Began",
      "description": "New cycle started - moving into follicular phase",
      "significance": 0.5,
      "icon": "flow",
      "health_context": {
        "cycle_day": 19,
        "phase": "luteal",
        "duration": "28 days average",
        "progress": 68,
        "status": "Good - luteal phase",
        "key_findings": "Cycle 19 of 28, approaching menstruation",
        "goal_progress": "Activity: 5/7 days | Sleep: 6/7 nights"
      }
    },
    {
      "milestone_date": "2026-09-23",
      "milestone_type": "phase_transition",
      "title": "Luteal Phase Transition",
      "description": "Ovulation passed, luteal phase begins. Self-care focus recommended.",
      "significance": 0.5,
      "icon": "moon"
    },
    {
      "milestone_date": "2026-09-26",
      "milestone_type": "health_achievement",
      "title": "7-Day Activity Streak",
      "description": "Completed 7 consecutive days of 30+ min movement",
      "significance": 0.75,
      "icon": "checkmark"
    }
  ],
  "timeline_summary": {
    "total_milestones": 8,
    "major_events": 2,
    "avg_monthly_milestones": 4,
    "date_range": {
      "start": "2026-08-09",
      "end": "2026-09-29"
    }
  },
  "ai_insights": {
    "summary": "Your health timeline shows excellent cycle regularity with consistent energy across phases. Achievement milestones indicate strong wellness commitment.",
    "strengths": [28-day cycle regularity", "Sustained activity tracking"],
    "areas_to_focus": ["Luteal phase symptom management"],
    "recommendations": ["Continue activity during luteal phase", "Log energy levels by phase"],
    "confidence_score": 78
  },
  "eligibility_status": "eligible",
  "data_completeness": 100,
  "last_updated": "2026-09-29T04:47:37.472709"
}
```

---

## Summary

**To meet client requirements:**

1. ✅ **Complete Health Context** - Fill all null fields with calculated data
2. ✅ **Multi-Type Milestones** - Detect cycle, phases, achievements, anomalies
3. ✅ **Dynamic Scoring** - Significance reflects importance
4. ✅ **Accurate Phases** - Calculate from menstrual date + cycle length
5. ✅ **AI Insights** - Add personalized timeline analysis
6. ✅ **Keep JSON Structure** - No breaking changes to response format

**No new fields needed - just intelligent population of existing structure.**
