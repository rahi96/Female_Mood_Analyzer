#!/usr/bin/env python3
"""Quick check for postpartum users in database."""

import pymysql

DB_CONFIG = {
    "host": "mysql-database.cc98ouaycdke.us-east-1.rds.amazonaws.com",
    "port": 3306,
    "user": "pulse",
    "password": "Pul$$e2026_mysql",  # From .env file
    "database": "pulse_mysql",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

def check_postpartum_users():
    """Check postpartum users and their life_stage_id."""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        print("\n" + "="*80)
        print("CHECKING POSTPARTUM USERS")
        print("="*80 + "\n")
        
        # First, check what life_stages exist
        print("1. AVAILABLE LIFE STAGES:")
        cursor.execute("SELECT id, name FROM life_stages ORDER BY id")
        stages = cursor.fetchall()
        for stage in stages:
            print(f"   ID {stage['id']}: {stage['name']}")
        
        # Find postpartum stage ID
        cursor.execute("SELECT id FROM life_stages WHERE LOWER(name) LIKE '%postpartum%'")
        postpartum_result = cursor.fetchone()
        postpartum_id = postpartum_result['id'] if postpartum_result else None
        
        print(f"\n2. POSTPARTUM STAGE ID: {postpartum_id}\n")
        
        # Check users in postpartum stage
        if postpartum_id:
            print(f"3. USERS WITH life_stage_id = {postpartum_id}:")
            cursor.execute(
                "SELECT p.user_id, u.username, p.life_stage_id FROM profiles p "
                "LEFT JOIN users u ON p.user_id = u.user_id "
                "WHERE p.life_stage_id = %s ORDER BY p.user_id",
                (postpartum_id,)
            )
            postpartum_users = cursor.fetchall()
            
            if postpartum_users:
                print(f"   Found {len(postpartum_users)} users in postpartum:\n")
                for user in postpartum_users:
                    print(f"   - User ID: {user['user_id']}, Username: {user['username']}")
            else:
                print(f"   ❌ No users found with life_stage_id = {postpartum_id}")
        
        # Check users with completed pregnancy cycles (has delivery date)
        print(f"\n4. USERS WITH COMPLETED PREGNANCY CYCLES (period_end_date set):")
        cursor.execute(
            "SELECT DISTINCT user_id, period_end_date FROM menstrual_cycles "
            "WHERE is_completed = 1 AND period_end_date IS NOT NULL "
            "ORDER BY user_id"
        )
        pregnancy_users = cursor.fetchall()
        
        if pregnancy_users:
            print(f"   Found {len(pregnancy_users)} users with completed pregnancies:\n")
            for user in pregnancy_users[:20]:  # Show first 20
                print(f"   - User ID: {user['user_id']}, Delivery Date: {user['period_end_date']}")
            if len(pregnancy_users) > 20:
                print(f"   ... and {len(pregnancy_users) - 20} more")
        else:
            print(f"   ❌ No users with completed pregnancies")
        
        # Show the mismatch: users with delivery data but NOT in postpartum stage
        print(f"\n5. MISMATCH - Users with delivery data but NOT in postpartum stage:")
        cursor.execute("""
            SELECT DISTINCT mc.user_id, u.username, p.life_stage_id, ls.name as life_stage_name, mc.period_end_date
            FROM menstrual_cycles mc
            LEFT JOIN users u ON mc.user_id = u.user_id
            LEFT JOIN profiles p ON mc.user_id = p.user_id
            LEFT JOIN life_stages ls ON p.life_stage_id = ls.id
            WHERE mc.is_completed = 1 AND mc.period_end_date IS NOT NULL
            AND (p.life_stage_id IS NULL OR p.life_stage_id != %s)
            ORDER BY mc.user_id
        """, (postpartum_id,))
        mismatch_users = cursor.fetchall()
        
        if mismatch_users:
            print(f"   Found {len(mismatch_users)} users with mismatched stages:\n")
            for user in mismatch_users[:20]:
                print(f"   - User ID: {user['user_id']}, Username: {user['username']}, "
                      f"Current Stage: {user['life_stage_name']} (ID: {user['life_stage_id']}), "
                      f"Delivery Date: {user['period_end_date']}")
            if len(mismatch_users) > 20:
                print(f"   ... and {len(mismatch_users) - 20} more")
        else:
            print(f"   ✅ All users with delivery data are in postpartum stage")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_postpartum_users()
