#!/usr/bin/env python3
"""Quick postpartum analysis using Docker container (simpler version)."""

import pymysql

# Admin credentials from docker setup
DB_CONFIG = {
    "host": "mysql-database.cc98ouaycdke.us-east-1.rds.amazonaws.com",
    "port": 3306,
    "user": "admin",
    "password": "Shahrul@123",
    "database": "pulse_mysql",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

def run_check():
    """Run postpartum check."""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        print("\n" + "="*90)
        print("POSTPARTUM DATA ANALYSIS")
        print("="*90)
        
        # 1. Check actual columns in life_stages
        print("\n1️⃣  LIFE_STAGES TABLE STRUCTURE:")
        print("-" * 90)
        cursor.execute("DESCRIBE life_stages")
        columns = cursor.fetchall()
        column_names = [col['Field'] for col in columns]
        print(f"   Columns: {column_names}")
        
        # 2. Show life_stages data
        print("\n2️⃣  ALL LIFE STAGES:")
        print("-" * 90)
        cursor.execute("SELECT * FROM life_stages ORDER BY id")
        stages = cursor.fetchall()
        for stage in stages:
            print(f"   {stage}")
        
        # 3. Count users by life_stage_id
        print("\n3️⃣  USERS BY LIFE_STAGE_ID (from profiles table):")
        print("-" * 90)
        cursor.execute("""
            SELECT life_stage_id, COUNT(user_id) as count
            FROM profiles
            GROUP BY life_stage_id
            ORDER BY life_stage_id
        """)
        stage_counts = cursor.fetchall()
        for row in stage_counts:
            print(f"   life_stage_id {row['life_stage_id']}: {row['count']} users")
        
        # 4. Users with completed pregnancies
        print("\n4️⃣  USERS WITH COMPLETED PREGNANCIES (is_completed=1):")
        print("-" * 90)
        cursor.execute("""
            SELECT COUNT(DISTINCT user_id) as count FROM menstrual_cycles 
            WHERE is_completed = 1 AND period_end_date IS NOT NULL
        """)
        result = cursor.fetchone()
        print(f"   Total: {result['count']} users with delivery data")
        
        # 5. Show first 10 completed pregnancies
        cursor.execute("""
            SELECT DISTINCT user_id, period_end_date,
                   DATEDIFF(CURDATE(), period_end_date) as days_postpartum
            FROM menstrual_cycles
            WHERE is_completed = 1 AND period_end_date IS NOT NULL
            ORDER BY period_end_date DESC
            LIMIT 10
        """)
        users = cursor.fetchall()
        if users:
            for user in users:
                weeks = user['days_postpartum'] // 7
                print(f"   - User {user['user_id']}: Delivery {user['days_postpartum']} days ago ({weeks} weeks)")
        
        # 6. Users with active pregnancies
        print("\n5️⃣  USERS WITH ACTIVE PREGNANCIES (is_completed=0):")
        print("-" * 90)
        cursor.execute("""
            SELECT COUNT(DISTINCT user_id) as count FROM menstrual_cycles 
            WHERE is_completed = 0 AND period_start_date IS NOT NULL
        """)
        result = cursor.fetchone()
        print(f"   Total: {result['count']} users with active pregnancies")
        
        # 7. Show first 10 active pregnancies
        cursor.execute("""
            SELECT DISTINCT user_id, period_start_date,
                   DATEDIFF(CURDATE(), period_start_date) as days_pregnant
            FROM menstrual_cycles
            WHERE is_completed = 0 AND period_start_date IS NOT NULL
            ORDER BY period_start_date DESC
            LIMIT 10
        """)
        users = cursor.fetchall()
        if users:
            for user in users:
                weeks = user['days_pregnant'] // 7
                print(f"   - User {user['user_id']}: Pregnant {user['days_pregnant']} days ({weeks} weeks)")
        
        # 8. Mismatch: users with delivery data but NOT in postpartum stage
        print("\n6️⃣  MISMATCH ANALYSIS - Delivery data but wrong life_stage:")
        print("-" * 90)
        cursor.execute("""
            SELECT DISTINCT mc.user_id, p.life_stage_id, mc.period_end_date,
                   DATEDIFF(CURDATE(), mc.period_end_date) as days_postpartum
            FROM menstrual_cycles mc
            LEFT JOIN profiles p ON mc.user_id = p.user_id
            WHERE mc.is_completed = 1 AND mc.period_end_date IS NOT NULL
            AND (p.life_stage_id IS NULL OR p.life_stage_id NOT IN (4, 3))
            ORDER BY mc.period_end_date DESC
            LIMIT 10
        """)
        mismatches = cursor.fetchall()
        print(f"   Total: {len(mismatches)} users")
        for user in mismatches:
            weeks = user['days_postpartum'] // 7
            print(f"   - User {user['user_id']}: life_stage_id={user['life_stage_id']}, "
                  f"Delivery {user['days_postpartum']} days ago ({weeks} weeks)")
        
        conn.close()
        print("\n" + "="*90 + "\n")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_check()
