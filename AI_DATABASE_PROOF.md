# AI Engine Database Usage - PROOF

## ⚠️ Backend Developer's Concern
The backend developer says: **"AI is not using database, it's just normal AI responding"**

## ✅ **THIS IS FALSE - Here's the Proof**

---

## 🔍 1. Database Connection Configuration

**File:** [`ai/config.py`](ai/config.py)

```python
class Settings(BaseSettings):
    # MySQL Database
    MYSQL_HOST: str = ""                    # ← AWS RDS mysql-database.cc98ouaycdke...
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = ""                    # ← pulse_user
    MYSQL_PASSWORD: str = ""                # ← real password
    MYSQL_DATABASE: str = ""                # ← pulse_mysql
```

---

## 🔍 2. Actual MySQL Queries Executed

**File:** [`ai/utils/db.py`](ai/utils/db.py)

### Real SQL Queries:

```python
def get_user_profile(user_id: int):
    """Query: SELECT u.*, p.* FROM users u LEFT JOIN profiles p..."""
    cursor.execute("""
        SELECT u.*, p.*
        FROM users u
        LEFT JOIN profiles p ON u.id = p.user_id
        WHERE u.id = %s
    """, (user_id,))

def get_current_cycle(user_id: int):
    """Query: SELECT * FROM menstrual_cycles WHERE user_id = ..."""
    cursor.execute("""
        SELECT * FROM menstrual_cycles
        WHERE user_id = %s AND is_completed = 0
        ORDER BY id DESC LIMIT 1
    """, (user_id,))

def get_bbt_logs(user_id: int):
    """Query: SELECT * FROM bbt_logs WHERE user_id = ..."""
    cursor.execute("""
        SELECT * FROM bbt_logs
        WHERE user_id = %s
        ORDER BY log_date DESC LIMIT 100
    """, (user_id,))

def get_opk_logs(cycle_id: int):
    """Query: SELECT * FROM opk_logs WHERE cycle_id = ..."""
    cursor.execute("""
        SELECT * FROM opk_logs
        WHERE cycle_id = %s
        ORDER BY log_date DESC LIMIT 100
    """, (cycle_id,))

def get_period_logs(user_id: int):
    """Query: SELECT * FROM menstrual_cycles WHERE user_id = ..."""
    cursor.execute("""
        SELECT * FROM menstrual_cycles
        WHERE user_id = %s
        ORDER BY period_start_date DESC LIMIT 12
    """, (user_id,))

def get_health_logs(user_id: int):
    """Query: SELECT * FROM health_logs WHERE user_id = ..."""
    cursor.execute("""
        SELECT * FROM health_logs
        WHERE user_id = %s
        ORDER BY log_date DESC LIMIT 60
    """, (user_id,))
```

---

## 🔍 3. How Cycle Engine Uses Database

**File:** [`ai/services/cycle_engine_v1_service.py`](ai/services/cycle_engine_v1_service.py)

### Line 28: Import database function
```python
from ai.utils.db import get_snapshot as get_db_snapshot
```

### Line 1281: Fetch REAL data from MySQL
```python
def _cycle_state(user_id: int) -> dict[str, Any]:
    # Fetch data directly from MySQL
    db_snapshot = get_db_snapshot(user_id)  # ← Executes SQL queries!
    profile = db_snapshot.get("profile")
    current_cycle = db_snapshot.get("current_cycle")
    
    # Convert MySQL bbt_logs to expected format
    for log in db_snapshot.get("bbt_logs") or []:
        backend_bbt.append({
            "id": log.get("id"),
            "user_id": user_id,
            "date": str(log.get("log_date"))[:10],
            "temperature_f": float(log.get("temperature")),
            ...
        })
```

### Line 1462: Check if REAL data exists
```python
def _has_cycle_data(user_id: int) -> bool:
    """Check if user has any REAL cycle data in database."""
    db_snapshot = get_db_snapshot(user_id)  # ← Queries MySQL!
    
    # Check for actual logged data
    has_periods = calendar_periods and len(calendar_periods) > 0
    has_bbt = db_snapshot.get("bbt_logs") and len(db_snapshot.get("bbt_logs", [])) > 0
    has_opk = db_snapshot.get("opk_logs") and len(db_snapshot.get("opk_logs", [])) > 0
    has_mucus = db_snapshot.get("mucus_logs") and len(db_snapshot.get("mucus_logs", [])) > 0
    
    return has_periods or has_bbt or has_opk or has_mucus
```

### Line 111: Engine Summary Endpoint
```python
def engine_summary(user_id: int) -> dict[str, Any]:
    if not _has_cycle_data(user_id):  # ← Checks MySQL database!
        return _empty_state_response(user_id, "engine_summary")
    
    state = _cycle_state(user_id)  # ← Fetches from MySQL!
    ...
```

---

## 🎯 Why `user_id=100` Returns Empty State

### Current Flow:
```
1. Request: GET /api/v1/cycle-engine/engine/summary?user_id=100
        ↓
2. AI queries MySQL:
   - SELECT * FROM menstrual_cycles WHERE user_id = 100  → Empty
   - SELECT * FROM bbt_logs WHERE user_id = 100         → Empty
   - SELECT * FROM opk_logs WHERE cycle_id = NULL       → Empty
        ↓
3. _has_cycle_data(100) returns False
        ↓
4. Response:
   {
     "status": "empty",
     "user_id": 100,
     "message": "No cycle data yet"
   }
```

---

## ✅ **Is This Correct Behavior?**

### YES! Here's why:

**AI Service Responsibility:**
- ✅ Query MySQL for cycle data (menstrual_cycles, bbt_logs, opk_logs)
- ✅ Return empty state if no data found
- ✅ Return AI-generated insights if data exists

**Laravel Backend Responsibility:**
- ✅ Authenticate user with `auth()->user()`
- ✅ Verify user exists in `users` table
- ✅ Only send VALID user_id to AI service
- ❌ AI should NOT re-validate user existence

---

## 🔧 **The Real Question**

### Should AI verify user exists in `users` table?

**Current behavior:**
```python
# user_id=100 (doesn't exist in users table)
→ AI queries MySQL for cycle data
→ Finds no data
→ Returns: {"status": "empty"}
```

**Alternative behavior:**
```python
# user_id=100 (doesn't exist in users table)
→ AI queries: SELECT id FROM users WHERE id = 100
→ User not found
→ Returns: {"status": "error", "message": "User not found"}
```

---

## 💡 **Recommendation**

### Option 1: Keep Current (Recommended)
Laravel validates user, AI focuses on cycle data.

**Laravel Controller:**
```php
$user = auth()->user();  // Already validated
$response = Http::get("http://ai:8000/api/v1/cycle-engine/engine/summary", [
    'user_id' => $user->id  // Only send valid user_id
]);
```

### Option 2: Add User Validation to AI
Add validation in AI service:

```python
def engine_summary(user_id: int) -> dict[str, Any]:
    # Verify user exists
    if not _user_exists(user_id):
        return {
            "status": "error",
            "message": "User not found",
            "user_id": user_id
        }
    
    if not _has_cycle_data(user_id):
        return _empty_state_response(user_id, "engine_summary")
    ...

def _user_exists(user_id: int) -> bool:
    """Check if user exists in users table."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        return cursor.fetchone() is not None
```

---

## 📊 **Test Results**

### Test with user_id=2 (has data):
```bash
curl "http://52.54.164.79:8002/api/v1/cycle-engine/engine/summary?user_id=2"
```
**Response:** Full cycle analysis with REAL database values

### Test with user_id=100 (no data):
```bash
curl "http://52.54.164.79:8002/api/v1/cycle-engine/engine/summary?user_id=100"
```
**Response:** `{"status": "empty", "message": "No cycle data yet"}`

**Both responses come from MySQL database queries!**

---

## 🎯 **Summary**

| Statement | Truth |
|-----------|-------|
| "AI is not using database" | ❌ **FALSE** - Uses MySQL via PyMySQL |
| "It's just normal AI responding" | ❌ **FALSE** - Queries 7+ tables |
| "user_id=100 should error" | ⚠️ **DESIGN CHOICE** - Currently returns empty state |

**The AI IS using your MySQL database on every request.**

---

## 📝 **What Backend Developer Should Do**

1. ✅ Always call AI with authenticated user_id
2. ✅ Don't send random/test user_ids like 100
3. ✅ Handle `{"status": "empty"}` as "user has no data yet"
4. ⚠️ Request user validation feature if needed (Option 2 above)

