#!/usr/bin/env python3
"""Comprehensive postpartum user analysis."""

import pymysql
from datetime import datetime, date

# Use credentials from the app's actual config
DB_CONFIG = {
    "host": "mysql-database.cc98ouaycdke.us-east-1.rds.amazonaws.com",
    "port": 3306,
    "user": "pulse",  # From .env
    "password": "Pul$$e2026_mysql",  # From .env  
    "database": "pulse_mysql",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

def run_analysis():
    """Run comprehensive postpartum analysis."""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        print("\n" + "="*90)
        print("POSTPARTUM USERS ANALYSIS")
        print("="*90)
        
        # 1. Life stages in database
        print("\n1️⃣  LIFE STAGES IN DATABASE:")
        print("-" * 90)
        cursor.execute("SELECT id, name FROM life_stages ORDER BY id")
        stages = cursor.fetchall()
        for stage in stages:
            print(f"   {stage['id']:2d}: {stage['name']}")
        
        # 2. Count users by life_stage_id
        print("\n2️⃣  USERS COUNT BY LIFE STAGE:")
        print("-" * 90)
        cursor.execute("""
            SELECT p.life_stage_id, ls.name, COUNT(DISTINCT p.user_id) as user_count
            FROM profiles p
            LEFT JOIN life_stages ls ON p.life_stage_id = ls.id
            GROUP BY p.life_stage_id, ls.name
            ORDER BY p.life_stage_id
        """)
        life_stage_counts = cursor.fetchall()
        for row in life_stage_counts:
            stage_id = row['life_stage_id'] if row['life_stage_id'] else 'NULL'
            stage_name = row['name'] if row['name'] else 'Unknown'
            print(f"   Life Stage {stage_id:2s}: {stage_name:30s} → {row['user_count']:4d} users")
        
        # 3. Find postpartum stage ID
        cursor.execute("SELECT id FROM life_stages WHERE LOWER(name) LIKE '%postpartum%'")
        postpartum_result = cursor.fetchone()
        postpartum_id = postpartum_result['id'] if postpartum_result else None
        
        # 4. Users explicitly marked as postpartum
        print(f"\n3️⃣  USERS EXPLICITLY MARKED AS POSTPARTUM (life_stage_id = {postpartum_id}):")
        print("-" * 90)
        cursor.execute("""
            SELECT p.user_id, u.username, u.email, p.created_at
            FROM profiles p
            LEFT JOIN users u ON p.user_id = u.user_id
            WHERE p.life_stage_id = %s
            ORDER BY p.user_id
            LIMIT 50
        """, (postpartum_id,))
        postpartum_users = cursor.fetchall()
        print(f"   Total: {len(postpartum_users)} users")
        if postpartum_users:
            for user in postpartum_users[:10]:
                print(f"   - User {user['user_id']:4d}: {user['username']:20s} ({user['email']})")
            if len(postpartum_users) > 10:
                print(f"   ... and {len(postpartum_users) - 10} more")
        else:
            print("   ❌ No users found!")
        
        # 5. Users with completed pregnancies (actual delivery data)
        print("\n4️⃣  USERS WITH COMPLETED PREGNANCIES (menstrual_cycles.is_completed = 1):")
        print("-" * 90)
        cursor.execute("""
            SELECT DISTINCT mc.user_id, u.username, u.email, 
                   mc.period_end_date as delivery_date,
                   DATEDIFF(CURDATE(), mc.period_end_date) as days_postpartum
            FROM menstrual_cycles mc
            LEFT JOIN users u ON mc.user_id = u.user_id
            WHERE mc.is_completed = 1 AND mc.period_end_date IS NOT NULL
            ORDER BY mc.period_end_date DESC
            LIMIT 50
        """)
        delivery_users = cursor.fetchall()
        print(f"   Total: {len(delivery_users)} users with delivery data")
        if delivery_users:
            for user in delivery_users[:10]:
                days = user['days_postpartum']
                weeks = days // 7 if days else 0
                print(f"   - User {user['user_id']:4d}: {user['username']:20s} | "
                      f"Delivery: {user['delivery_date']} ({days} days / {weeks} weeks ago)")
            if len(delivery_users) > 10:
                print(f"   ... and {len(delivery_users) - 10} more")
        else:
            print("   ❌ No users found!")
        
        # 6. MISMATCH ANALYSIS
        print("\n5️⃣  MISMATCH ANALYSIS - Users with delivery data but NOT in postpartum stage:")
        print("-" * 90)
        cursor.execute("""
            SELECT DISTINCT mc.user_id, u.username, u.email,
                   p.life_stage_id, ls.name as life_stage_name,
                   mc.period_end_date as delivery_date,
                   DATEDIFF(CURDATE(), mc.period_end_date) as days_postpartum
            FROM menstrual_cycles mc
            LEFT JOIN users u ON mc.user_id = u.user_id
            LEFT JOIN profiles p ON mc.user_id = p.user_id
            LEFT JOIN life_stages ls ON p.life_stage_id = ls.id
            WHERE mc.is_completed = 1 AND mc.period_end_date IS NOT NULL
            AND (p.life_stage_id IS NULL OR p.life_stage_id != %s)
            ORDER BY mc.period_end_date DESC
            LIMIT 50
        """, (postpartum_id,))
        mismatched = cursor.fetchall()
        print(f"   Total: {len(mismatched)} users with mismatched stages")
        if mismatched:
            for user in mismatched[:15]:
                current_stage = user['life_stage_name'] if user['life_stage_name'] else 'NULL'
                days = user['days_postpartum']
                weeks = days // 7 if days else 0
                print(f"   - User {user['user_id']:4d}: {user['username']:20s} | "
                      f"Current: {current_stage:15s} | Delivery: {days:3d} days ago ({weeks:2d} weeks)")
            if len(mismatched) > 15:
                print(f"   ... and {len(mismatched) - 15} more")
        else:
            print("   ✅ No mismatches! All users with delivery data are marked as postpartum")
        
        # 7. Active pregnancies (incomplete cycles)
        print("\n6️⃣  ACTIVE PREGNANCIES (menstrual_cycles.is_completed = 0):")
        print("-" * 90)
        cursor.execute("""
            SELECT DISTINCT mc.user_id, u.username, u.email,
                   p.life_stage_id, ls.name as life_stage_name,
                   mc.period_start_date,
                   DATEDIFF(CURDATE(), mc.period_start_date) as days_pregnant
            FROM menstrual_cycles mc
            LEFT JOIN users u ON mc.user_id = u.user_id
            LEFT JOIN profiles p ON mc.user_id = p.user_id
            LEFT JOIN life_stages ls ON p.life_stage_id = ls.id
            WHERE mc.is_completed = 0 AND mc.period_start_date IS NOT NULL
            ORDER BY mc.period_start_date DESC
            LIMIT 50
        """)
        pregnant_users = cursor.fetchall()
        print(f"   Total: {len(pregnant_users)} users with active pregnancies")
        if pregnant_users:
            for user in pregnant_users[:10]:
                stage = user['life_stage_name'] if user['life_stage_name'] else 'NULL'
                days = user['days_pregnant']
                weeks = days // 7 if days else 0
                print(f"   - User {user['user_id']:4d}: {user['username']:20s} | "
                      f"Stage: {stage:15s} | Pregnant: {days:3d} days ({weeks:2d} weeks)")
            if len(pregnant_users) > 10:
                print(f"   ... and {len(pregnant_users) - 10} more")
        else:
            print("   ❌ No users found!")
        
        # 8. Summary statistics
        print("\n7️⃣  SUMMARY STATISTICS:")
        print("-" * 90)
        print(f"   • Users with life_stage_id={postpartum_id} (postpartum):  {len(postpartum_users):4d}")
        print(f"   • Users with completed pregnancies:                       {len(delivery_users):4d}")
        print(f"   • Users with mismatched stages:                           {len(mismatched):4d}")
        print(f"   • Users with active pregnancies:                          {len(pregnant_users):4d}")
        
        # Calculate weeks postpartum ranges
        if mismatched:
            weeks_postpartum = [m['days_postpartum'] // 7 for m in mismatched if m['days_postpartum']]
            if weeks_postpartum:
                print(f"   • Weeks postpartum range:                              {min(weeks_postpartum):2d} - {max(weeks_postpartum):2d} weeks")
        
        conn.close()
        print("\n" + "="*90 + "\n")
        
    except Exception as e:
        print(f"\n❌ DATABASE ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_analysis()
