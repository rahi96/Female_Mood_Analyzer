#!/usr/bin/env python3
"""Check user 16's data in database."""

import pymysql
from datetime import datetime

DB_CONFIG = {
    "host": "mysql-database.cc98ouaycdke.us-east-1.rds.amazonaws.com",
    "port": 3306,
    "user": "admin",
    "password": "Shahrul@123",
    "database": "pulse_mysql",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

def check_user_16():
    """Check user 16's pregnancy and postpartum data."""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        user_id = 16
        
        print("\n" + "="*90)
        print(f"CHECKING USER {user_id} DATA")
        print("="*90 + "\n")
        
        # 1. Check if user exists
        print("1️⃣  USER PROFILE:")
        print("-" * 90)
        cursor.execute("""
            SELECT u.user_id, u.username, u.email, p.life_stage_id, p.created_at
            FROM users u
            LEFT JOIN profiles p ON u.user_id = p.user_id
            WHERE u.user_id = %s
        """, (user_id,))
        user = cursor.fetchone()
        
        if user:
            print(f"   User ID: {user['user_id']}")
            print(f"   Username: {user['username']}")
            print(f"   Email: {user['email']}")
            print(f"   Life Stage ID: {user['life_stage_id']}")
            print(f"   Profile Created: {user['created_at']}")
        else:
            print(f"   ❌ User {user_id} NOT FOUND")
            conn.close()
            return
        
        # 2. Check all menstrual cycles
        print(f"\n2️⃣  ALL MENSTRUAL CYCLES FOR USER {user_id}:")
        print("-" * 90)
        cursor.execute("""
            SELECT id, user_id, period_start_date, period_end_date, is_completed, created_at, updated_at
            FROM menstrual_cycles
            WHERE user_id = %s
            ORDER BY period_start_date DESC
        """, (user_id,))
        cycles = cursor.fetchall()
        
        if cycles:
            print(f"   Total cycles: {len(cycles)}\n")
            for i, cycle in enumerate(cycles, 1):
                print(f"   Cycle {i}:")
                print(f"      ID: {cycle['id']}")
                print(f"      Period Start: {cycle['period_start_date']}")
                print(f"      Period End: {cycle['period_end_date']}")
                print(f"      Is Completed: {cycle['is_completed']}")
                print(f"      Created: {cycle['created_at']}")
                print(f"      Updated: {cycle['updated_at']}")
                print()
        else:
            print(f"   ❌ NO CYCLES FOUND")
        
        # 3. Check for completed pregnancies (postpartum data)
        print(f"3️⃣  COMPLETED PREGNANCIES (postpartum data):")
        print("-" * 90)
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM menstrual_cycles
            WHERE user_id = %s AND is_completed = 1 AND period_end_date IS NOT NULL
        """, (user_id,))
        result = cursor.fetchone()
        completed_count = result['count'] if result else 0
        print(f"   Completed cycles with period_end_date: {completed_count}")
        
        if completed_count > 0:
            cursor.execute("""
                SELECT id, period_end_date, DATEDIFF(CURDATE(), period_end_date) as days_postpartum
                FROM menstrual_cycles
                WHERE user_id = %s AND is_completed = 1 AND period_end_date IS NOT NULL
                ORDER BY period_end_date DESC
            """, (user_id,))
            completed = cursor.fetchall()
            for cycle in completed:
                days = cycle['days_postpartum']
                weeks = days // 7
                print(f"   - Cycle ID {cycle['id']}: Delivery {cycle['period_end_date']} ({days} days ago / {weeks} weeks)")
        
        # 4. Check for active pregnancies
        print(f"\n4️⃣  ACTIVE PREGNANCIES (incomplete cycles):")
        print("-" * 90)
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM menstrual_cycles
            WHERE user_id = %s AND is_completed = 0 AND period_start_date IS NOT NULL
        """, (user_id,))
        result = cursor.fetchone()
        active_count = result['count'] if result else 0
        print(f"   Active cycles with period_start_date: {active_count}")
        
        if active_count > 0:
            cursor.execute("""
                SELECT id, period_start_date, DATEDIFF(CURDATE(), period_start_date) as days_pregnant
                FROM menstrual_cycles
                WHERE user_id = %s AND is_completed = 0 AND period_start_date IS NOT NULL
                ORDER BY period_start_date DESC
            """, (user_id,))
            active = cursor.fetchall()
            for cycle in active:
                days = cycle['days_pregnant']
                weeks = days // 7
                print(f"   - Cycle ID {cycle['id']}: Started {cycle['period_start_date']} ({days} days ago / {weeks} weeks)")
        
        # 5. Check health logs
        print(f"\n5️⃣  HEALTH LOGS (for postpartum recovery metrics):")
        print("-" * 90)
        cursor.execute("""
            SELECT COUNT(*) as count FROM health_logs WHERE user_id = %s
        """, (user_id,))
        result = cursor.fetchone()
        log_count = result['count'] if result else 0
        print(f"   Total health logs: {log_count}")
        
        if log_count > 0:
            cursor.execute("""
                SELECT mood, energy_level, symptoms, notes, log_date
                FROM health_logs
                WHERE user_id = %s
                ORDER BY log_date DESC
                LIMIT 5
            """, (user_id,))
            logs = cursor.fetchall()
            for log in logs:
                print(f"   - {log['log_date']}: Mood={log['mood']}, Energy={log['energy_level']}")
        
        # 6. Summary and diagnosis
        print(f"\n6️⃣  DIAGNOSIS:")
        print("-" * 90)
        
        if completed_count > 0:
            print(f"   ✅ User {user_id} HAS POSTPARTUM DATA")
            print(f"      {completed_count} completed pregnancy cycle(s) with delivery date(s)")
        else:
            print(f"   ❌ User {user_id} HAS NO POSTPARTUM DATA")
            print(f"      No completed cycles found")
        
        if active_count > 0:
            print(f"   ✅ User {user_id} HAS ACTIVE PREGNANCY DATA")
            print(f"      {active_count} active pregnancy cycle(s)")
        else:
            print(f"   ⚠️  User {user_id} HAS NO ACTIVE PREGNANCY DATA")
        
        # Check the helper function logic
        print(f"\n7️⃣  API HELPER FUNCTION CHECK:")
        print("-" * 90)
        print(f"   _has_postpartum_data({user_id}) should return: {completed_count > 0}")
        print(f"   _has_pregnancy_data({user_id}) should return: {active_count > 0}")
        
        if completed_count == 0:
            print(f"\n   🔴 PROBLEM: Postpartum endpoint would FAIL for user {user_id}")
            print(f"      Reason: No completed pregnancy with period_end_date found")
        else:
            print(f"\n   🟢 User {user_id} SHOULD work with postpartum endpoint")
        
        conn.close()
        print("\n" + "="*90 + "\n")
        
    except Exception as e:
        print(f"\n❌ DATABASE ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_user_16()
