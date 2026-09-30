# Data & Tables Requirements Checklist for Life-Arc Enhancements

Please provide the following information so I can implement all features:

---

## 1. MENSTRUAL_CYCLES TABLE

### Schema (Column names & types)
```
Need:
- [ ] List of all column names
- [ ] Data type for each column
- [ ] Example row of data for user 2 and user 10
```

**Questions:**
- [ ] What is the exact column name for menstrual cycle start date? (period_start_date? created_at? start_date?)
- [ ] What is the exact column name for cycle duration? (duration_days? length? cycle_length?)
- [ ] Are there any columns tracking symptoms? (cramps? headache? mood_change?)
- [ ] Is there a column for flow intensity? (light? normal? heavy?)

---

## 2. HEALTH_LOGS TABLE

### Schema (Column names & types)
```
Need:
- [ ] List of all column names
- [ ] Data type for each column
- [ ] Example row(s)
```

**Questions:**
- [ ] What health metrics are tracked? (mood? energy_level? sleep_hours? symptoms?)
- [ ] Is there a notes/description field?
- [ ] What is the date column name?
- [ ] Are there symptom tracking fields? (brain_fog? fatigue? headache?)
- [ ] Is there an "activity" or "exercise" field?

---

## 3. TERRA_ACTIVITY_DATA TABLE

### Schema (Column names & types)
```
Need:
- [ ] List of all column names
- [ ] Data type for each column
- [ ] Example payload structure
```

**Questions:**
- [ ] What fields are in the "payload" JSON? (steps? calories? heart_rate? sleep_duration?)
- [ ] How is sleep data stored? (hours? minutes? quality score?)
- [ ] Is there activity type? (running? walking? strength training?)
- [ ] Date/timestamp format?

---

## 4. HEALTH_TRENDS TABLE

### Schema (Column names & types)
```
Need:
- [ ] List of all column names
- [ ] Data type for each column
- [ ] Example row(s)
```

**Questions:**
- [ ] What trends are tracked? (mood? energy? sleep? activity?)
- [ ] Are there correlation scores?
- [ ] Date range information?

---

## 5. USERS PROFILE TABLE

### Schema (Relevant columns only)
```
Need:
- [ ] user_id column name
- [ ] Any column with user goals/preferences?
- [ ] Any health tracking settings?
```

**Questions:**
- [ ] Does the profile table store user goals? (exercise goal? sleep target?)
- [ ] Any field for preferred cycle length assumptions?
- [ ] Any preferences for milestone types to track?

---

## 6. DATA SAMPLES - User 2

Please run these queries and provide output:

```sql
-- Sample cycle data
SELECT * FROM menstrual_cycles WHERE user_id = 2 LIMIT 5;
```

```sql
-- Sample health logs
SELECT * FROM health_logs WHERE user_id = 2 LIMIT 5;
```

```sql
-- Sample activity data
SELECT id, user_id, payload, created_at FROM terra_activity_data 
WHERE user_id = 2 LIMIT 3;
```

```sql
-- Cycle statistics
SELECT 
  COUNT(*) as total_cycles,
  AVG(duration_days) as avg_duration,
  MIN(period_start_date) as earliest_cycle,
  MAX(period_start_date) as latest_cycle
FROM menstrual_cycles 
WHERE user_id = 2;
```

---

## 7. DATA SAMPLES - User 10

Please run these queries and provide output:

```sql
-- Sample cycle data
SELECT * FROM menstrual_cycles WHERE user_id = 10 LIMIT 5;
```

```sql
-- Sample health logs
SELECT * FROM health_logs WHERE user_id = 10 LIMIT 5;
```

```sql
-- Sample activity data
SELECT id, user_id, payload, created_at FROM terra_activity_data 
WHERE user_id = 10 LIMIT 3;
```

---

## 8. DATA SAMPLES - All Users Statistics

```sql
-- How many users have menstrual cycle data?
SELECT COUNT(DISTINCT user_id) as users_with_cycles 
FROM menstrual_cycles;
```

```sql
-- How many users have health logs?
SELECT COUNT(DISTINCT user_id) as users_with_logs 
FROM health_logs;
```

```sql
-- How many users have terra activity data?
SELECT COUNT(DISTINCT user_id) as users_with_activity 
FROM terra_activity_data;
```

```sql
-- Date range of all data
SELECT 
  MIN(created_at) as earliest_data,
  MAX(created_at) as latest_data
FROM terra_activity_data;
```

---

## 9. SPECIFIC QUESTIONS FOR IMPLEMENTATION

### For "Fill health_context fields":
- [ ] What should "duration" show if user has < 2 cycles? (e.g., "Insufficient data", "N/A", or a default like "28 days"?)
- [ ] Should "progress" be 0-100 percentage or days remaining?
- [ ] What are valid values for "status"? (e.g., "Optimal", "Good", "Caution", "Low"?)

### For "Expand milestone types":
- [ ] Should we detect ALL milestone types or focus on specific ones first?
- [ ] What constitutes a "health achievement"? (3-day activity streak? 7-day? custom user goals?)
- [ ] What's the minimum cycle deviation to flag as "anomaly"? (3 days? 5 days?)

### For "Phase calculation":
- [ ] Standard cycle is 28 days - is this correct for your users?
- [ ] Should ovulation be day 13-15 (standard) or flexible based on user's cycle length?
- [ ] If cycle length is unknown, what's the fallback assumption?

### For "AI insights":
- [ ] Should confidence_score be different for different milestone types?
- [ ] Any specific health areas the AI should emphasize?

---

## 10. OPTIONAL ENHANCEMENTS

- [ ] Do you track any PMS/PMDD symptoms?
- [ ] Do you have basal body temperature (BBT) data?
- [ ] Do you track cervical mucus observations?
- [ ] Do you have ovulation prediction data?
- [ ] Do you track medication/supplement usage?
- [ ] Do you track sexual activity?

---

## SUMMARY TEMPLATE

When you provide data, please format like this:

```
=== MENSTRUAL_CYCLES TABLE ===
Columns: id, user_id, period_start_date, duration_days, flow_intensity, symptoms

Sample User 2 Data:
| id | user_id | period_start_date | duration_days | flow_intensity |
|----+---------+-------------------+---------------+----------------|
| 1  | 2       | 2026-08-15        | 5             | normal         |
| 2  | 2       | 2026-09-12        | 5             | normal         |

Statistics for User 2:
- Total cycles: 2
- Average duration: 5 days
- Earliest: 2026-08-15
- Latest: 2026-09-12

=== HEALTH_LOGS TABLE ===
Columns: id, user_id, log_date, mood (1-10), energy_level (1-10), notes

Sample User 2 Data:
[provide examples]

etc...
```

---

## PRIORITY ORDER

🔴 **CRITICAL** (Must have):
1. menstrual_cycles schema & 3 sample rows
2. Cycle statistics (count, avg duration, date range)

🟡 **IMPORTANT** (Should have):
3. health_logs schema & samples
4. terra_activity_data payload structure
5. Data completeness across users

🟢 **NICE TO HAVE**:
6. Users with specific conditions/symptoms
7. Optional enhancements (BBT, cervical mucus, etc.)

---

Once you provide this information, I'll have everything needed to implement all 7 enhancements!
