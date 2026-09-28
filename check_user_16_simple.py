#!/usr/bin/env python3
"""Check user 16 using app's DB utilities."""

import sys
sys.path.insert(0, '/app')

from ai.utils.db import get_connection

user_id = 16

print("\n" + "="*90)
print(f"CHECKING USER {user_id} DATA")
print("="*90 + "\n")

try:
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Check user profile
        print("1️⃣  USER PROFILE:")
        print("-" * 90)
        cursor.execute("""
            SELECT u.id, u.username, p.life_stage_id
            FROM users u
            LEFT JOIN profiles p ON u.id = p.user_id
            WHERE u.id = %s
        """, (user_id,))
        user = cursor.fetchone()
        
        if user:
            print(f"   User ID: {user['id']}")
            print(f"   Username: {user['username']}")
            print(f"   Life Stage ID: {user['life_stage_id']}")
        else:
            print(f"   ❌ User {user_id} NOT FOUND")
            sys.exit(1)
        
        # 2. Check all menstrual cycles
        print(f"\n2️⃣  ALL MENSTRUAL CYCLES:")
        print("-" * 90)
        cursor.execute("""
            SELECT id, period_start_date, period_end_date, is_completed
            FROM menstrual_cycles
            WHERE user_id = %s
            ORDER BY period_start_date DESC
        """, (user_id,))
        cycles = cursor.fetchall()
        
        print(f"   Total cycles: {len(cycles)}\n")
        for i, cycle in enumerate(cycles, 1):
            status = "COMPLETED" if cycle['is_completed'] else "ACTIVE"
            print(f"   Cycle {i} [{status}]:")
            print(f"      Start: {cycle['period_start_date']}")
            print(f"      End: {cycle['period_end_date']}")
            print()
        
        # 3. Check completed pregnancies (postpartum)
        print(f"3️⃣  POSTPARTUM DATA CHECK:")
        print("-" * 90)
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM menstrual_cycles
            WHERE user_id = %s AND is_completed = 1 AND period_end_date IS NOT NULL
        """, (user_id,))
        result = cursor.fetchone()
        completed_count = result['count']
        print(f"   Completed cycles with period_end_date: {completed_count}")
        
        if completed_count > 0:
            cursor.execute("""
                SELECT id, period_end_date
                FROM menstrual_cycles
                WHERE user_id = %s AND is_completed = 1 AND period_end_date IS NOT NULL
            """, (user_id,))
            for cycle in cursor.fetchall():
                print(f"   ✅ Cycle ID {cycle['id']}: {cycle['period_end_date']}")
        
        # 4. Check active pregnancies
        print(f"\n4️⃣  ACTIVE PREGNANCY DATA CHECK:")
        print("-" * 90)
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM menstrual_cycles
            WHERE user_id = %s AND is_completed = 0 AND period_start_date IS NOT NULL
        """, (user_id,))
        result = cursor.fetchone()
        active_count = result['count']
        print(f"   Active cycles with period_start_date: {active_count}")
        
        if active_count > 0:
            cursor.execute("""
                SELECT id, period_start_date
                FROM menstrual_cycles
                WHERE user_id = %s AND is_completed = 0 AND period_start_date IS NOT NULL
            """, (user_id,))
            for cycle in cursor.fetchall():
                print(f"   ✅ Cycle ID {cycle['id']}: {cycle['period_start_date']}")
        
        # 5. Diagnosis
        print(f"\n5️⃣  DIAGNOSIS:")
        print("-" * 90)
        
        if completed_count > 0:
            print(f"   ✅ HAS POSTPARTUM DATA: {completed_count} completed cycle(s)")
        else:
            print(f"   ❌ NO POSTPARTUM DATA: No completed cycles found")
        
        if active_count > 0:
            print(f"   ✅ HAS ACTIVE PREGNANCY DATA: {active_count} active cycle(s)")
        else:
            print(f"   ❌ NO ACTIVE PREGNANCY DATA")
        
        # 6. API Status
        print(f"\n6️⃣  API ENDPOINT STATUS:")
        print("-" * 90)
        
        if completed_count > 0:
            print(f"   POST /postpartum/recovery?user_id={user_id} → Should WORK ✅")
        else:
            print(f"   POST /postpartum/recovery?user_id={user_id} → Should FAIL ❌")
            print(f"      Error: 'User {user_id} is not postpartum'")
        
        if active_count > 0:
            print(f"   GET /pregnancy/summary?user_id={user_id} → Should WORK ✅")
        else:
            print(f"   GET /pregnancy/summary?user_id={user_id} → Should FAIL ❌")
        
        print("\n" + "="*90 + "\n")

except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
