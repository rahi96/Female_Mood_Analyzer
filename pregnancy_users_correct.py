#!/usr/bin/env python3
"""Correct script to view pregnancy users and explain the schema."""

import sys
sys.path.insert(0, '/app')

from ai.utils.db import get_connection
from datetime import datetime, date

print("\n" + "="*130)
print(f"{'PREGNANCY USERS - DATABASE SCHEMA & DATA':^130}")
print("="*130)

print("\n📚 SCHEMA EXPLANATION:")
print("-"*130)
print("""
PREGNANT USERS are found by combining data from 3 tables:

1. 👤 users TABLE
   - Contains: user account info
   - Key column: id (user identifier)

2. 📋 profiles TABLE  
   - Contains: user profile info including life_stage_id
   - Key column: user_id (links to users.id)
   - life_stage_id: 3=pregnancy, 4=postpartum, etc.

3. 🔴 menstrual_cycles TABLE
   - Contains: cycle/pregnancy tracking data
   - Key columns: user_id, is_completed, period_start_date, period_end_date
   - Active pregnancy = is_completed=0 AND period_start_date IS NOT NULL

QUERY: Joins all 3 tables WHERE menstrual_cycles.is_completed=0 AND period_start_date IS NOT NULL
""")

print("\n" + "="*130)
print("🔍 DISCOVERING ACTUAL COLUMN NAMES IN DATABASE:")
print("-"*130)

try:
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Check users table columns
        print("\n📦 users table columns:")
        cursor.execute("DESCRIBE users")
        users_cols = cursor.fetchall()
        for col in users_cols:
            print(f"   - {col['Field']} ({col['Type']})")
        
        # Check if specific columns exist
        user_col_names = [col['Field'] for col in users_cols]
        print(f"\n   ✓ Available: {', '.join(user_col_names[:5])}")
        
        print("\n📦 profiles table columns:")
        cursor.execute("DESCRIBE profiles")
        profile_cols = cursor.fetchall()
        for col in profile_cols:
            print(f"   - {col['Field']} ({col['Type']})")
        
        print("\n📦 menstrual_cycles table columns:")
        cursor.execute("DESCRIBE menstrual_cycles")
        cycle_cols = cursor.fetchall()
        for col in cycle_cols:
            print(f"   - {col['Field']} ({col['Type']})")

except Exception as e:
    print(f"❌ Schema error: {e}")

print("\n" + "="*130)
print("👶 ACTIVE PREGNANCY USERS - DATA VIEW:")
print("-"*130)

try:
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Query with safe column selection
        cursor.execute("""
            SELECT 
                u.id as user_id,
                p.life_stage_id,
                mc.period_start_date,
                mc.period_end_date,
                mc.is_completed,
                mc.created_at
            FROM users u
            LEFT JOIN profiles p ON u.id = p.user_id
            LEFT JOIN menstrual_cycles mc ON u.id = mc.user_id
            WHERE mc.is_completed = 0 AND mc.period_start_date IS NOT NULL
            ORDER BY mc.period_start_date DESC
        """)
        
        pregnancy_users = cursor.fetchall()
        
        print(f"\n✅ TOTAL ACTIVE PREGNANCY RECORDS: {len(pregnancy_users)}\n")
        
        print(f"{'User ID':<10} {'Life Stage':<12} {'Pregnancy Start':<18} {'Days Pregnant':<15} {'Status'}")
        print("-"*130)
        
        today = datetime.now().date()
        
        for user in pregnancy_users:
            user_id = user['user_id']
            stage = str(user['life_stage_id']) if user['life_stage_id'] else "NULL"
            p_start = user['period_start_date']
            
            if p_start:
                d = p_start.date() if isinstance(p_start, datetime) else p_start
                days_diff = (today - d).days
                weeks = days_diff // 7
                status = f"✅ Week {weeks}"
            else:
                days_diff = "N/A"
                status = "N/A"
            
            print(f"{user_id:<10} {stage:<12} {str(p_start):<18} {str(days_diff):<15} {status}")
        
        # Summary stats
        print("\n" + "="*130)
        print("📊 SUMMARY:")
        cursor.execute("""
            SELECT COUNT(DISTINCT user_id) as total_pregnant
            FROM menstrual_cycles
            WHERE is_completed = 0 AND period_start_date IS NOT NULL
        """)
        result = cursor.fetchone()
        print(f"   Total pregnant users: {result['total_pregnant']}")
        
        cursor.execute("""
            SELECT 
                p.life_stage_id,
                COUNT(DISTINCT u.id) as count
            FROM users u
            LEFT JOIN profiles p ON u.id = p.user_id
            LEFT JOIN menstrual_cycles mc ON u.id = mc.user_id
            WHERE mc.is_completed = 0 AND mc.period_start_date IS NOT NULL
            GROUP BY p.life_stage_id
            ORDER BY count DESC
        """)
        
        stages = cursor.fetchall()
        print(f"\n   By Life Stage ID:")
        for s in stages:
            print(f"      - Stage {s['life_stage_id']}: {s['count']} users")
        
        print("\n" + "="*130 + "\n")

except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
