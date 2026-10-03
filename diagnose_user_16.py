#!/usr/bin/env python3
"""Diagnose user 16 postpartum issue - using correct schema."""

import sys
sys.path.insert(0, '/app')

from ai.utils.db import get_connection

user_id = 16

print("\n" + "="*90)
print(f"USER {user_id} POSTPARTUM ISSUE DIAGNOSIS")
print("="*90)

try:
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # 1. User existence
        print(f"\n1️⃣  USER {user_id} EXISTENCE CHECK:")
        print("-" * 90)
        cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if user:
            print(f"   ✅ User {user_id} exists")
        else:
            print(f"   ❌ User {user_id} NOT FOUND")
            sys.exit(1)
        
        # 2. Life stage in profile
        print(f"\n2️⃣  PROFILE LIFE STAGE:")
        print("-" * 90)
        cursor.execute("SELECT life_stage_id FROM profiles WHERE user_id = %s", (user_id,))
        profile = cursor.fetchone()
        if profile:
            life_stage = profile['life_stage_id']
            print(f"   life_stage_id = {life_stage}")
            if life_stage == 4:
                print(f"   ✅ Correctly set to POSTPARTUM (4)")
            elif life_stage == 3:
                print(f"   ⚠️  Set to PREGNANCY (3), not postpartum")
            else:
                print(f"   ❌ Set to {life_stage}, expected 3 or 4")
        else:
            print(f"   ❌ No profile found")
        
        # 3. Menstrual cycles data
        print(f"\n3️⃣  MENSTRUAL CYCLES DATA:")
        print("-" * 90)
        cursor.execute("""
            SELECT id, period_start_date, period_end_date, is_completed
            FROM menstrual_cycles
            WHERE user_id = %s
            ORDER BY period_start_date DESC
        """, (user_id,))
        cycles = cursor.fetchall()
        
        print(f"   Total cycles: {len(cycles)}\n")
        
        completed_cycles = []
        active_cycles = []
        
        for i, cycle in enumerate(cycles, 1):
            status = "COMPLETED" if cycle['is_completed'] else "ACTIVE"
            print(f"   Cycle {i} [{status}]:")
            print(f"      period_start_date: {cycle['period_start_date']}")
            print(f"      period_end_date: {cycle['period_end_date']}")
            
            if cycle['is_completed'] and cycle['period_end_date']:
                completed_cycles.append(cycle)
                print(f"      ✅ Has delivery date (postpartum data)")
            elif not cycle['is_completed'] and cycle['period_start_date']:
                active_cycles.append(cycle)
                print(f"      ✅ Active pregnancy")
            print()
        
        # 4. Problem diagnosis
        print(f"4️⃣  PROBLEM DIAGNOSIS:")
        print("-" * 90)
        
        has_postpartum_data = len(completed_cycles) > 0
        profile_is_postpartum = profile and profile['life_stage_id'] == 4
        
        print(f"   Has postpartum data (completed cycle): {has_postpartum_data}")
        print(f"   Profile life_stage_id = 4: {profile_is_postpartum}")
        
        if has_postpartum_data and not profile_is_postpartum:
            print(f"\n   🔴 MISMATCH FOUND!")
            print(f"      - User {user_id} has postpartum data in menstrual_cycles")
            print(f"      - But profile.life_stage_id ≠ 4")
            print(f"      - API check: 'if profile.life_stage_id != 4' → 404 ERROR")
            print(f"\n   SOLUTION: Update profile.life_stage_id to 4")
            print(f"   OR: Use data-driven check instead of life_stage_id only")
        elif has_postpartum_data and profile_is_postpartum:
            print(f"\n   ✅ CORRECT SETUP")
            print(f"      - User has postpartum data")
            print(f"      - Profile is marked as postpartum")
            print(f"      - API should work ✅")
        elif not has_postpartum_data:
            print(f"\n   ⚠️  NO POSTPARTUM DATA")
            print(f"      - User {user_id} has no completed cycles")
            print(f"      - Cannot access postpartum endpoints")
        
        # 5. Health logs
        print(f"\n5️⃣  HEALTH LOGS:")
        print("-" * 90)
        cursor.execute("""
            SELECT COUNT(*) as count FROM health_logs WHERE user_id = %s
        """, (user_id,))
        result = cursor.fetchone()
        log_count = result['count']
        print(f"   Total health logs: {log_count}")
        
        if log_count > 0 and has_postpartum_data:
            delivery_date = completed_cycles[0]['period_end_date']
            cursor.execute("""
                SELECT COUNT(*) as count FROM health_logs
                WHERE user_id = %s AND log_date >= %s
            """, (user_id, delivery_date))
            result = cursor.fetchone()
            post_delivery_logs = result['count']
            print(f"   Health logs after delivery: {post_delivery_logs}")
        
        # 6. API Status
        print(f"\n6️⃣  API ENDPOINT STATUS:")
        print("-" * 90)
        
        if profile_is_postpartum:
            print(f"   ✅ POST /postpartum/recovery?user_id={user_id}")
            print(f"      Status: Should work (life_stage_id = 4)")
        else:
            if has_postpartum_data:
                print(f"   ❌ POST /postpartum/recovery?user_id={user_id}")
                print(f"      Status: FAILS with 404")
                print(f"      Reason: life_stage_id ≠ 4, but has delivery data")
                print(f"      FIX: Set life_stage_id=4 OR use helper functions")
            else:
                print(f"   ❌ POST /postpartum/recovery?user_id={user_id}")
                print(f"      Status: FAILS with 404")
                print(f"      Reason: No postpartum data found")
        
        if len(active_cycles) > 0:
            print(f"   ✅ GET /pregnancy/summary?user_id={user_id}")
            print(f"      Status: Should work (has active cycle)")
        else:
            print(f"   ❌ GET /pregnancy/summary?user_id={user_id}")
            print(f"      Status: FAILS (no active pregnancy)")
        
        print("\n" + "="*90 + "\n")

except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
