#!/usr/bin/env python3
"""Find users with BOTH pregnancy and postpartum data."""

import sys
sys.path.insert(0, '/app')

from ai.utils.db import get_connection

print("\n" + "="*90)
print("USERS WITH BOTH PREGNANCY AND POSTPARTUM DATA")
print("="*90)

try:
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Find users with BOTH pregnancy and postpartum cycles
        print("\n1️⃣  FINDING USERS WITH BOTH DATA TYPES:")
        print("-" * 90)
        
        cursor.execute("""
            SELECT 
                u.id as user_id,
                COUNT(DISTINCT CASE WHEN mc.is_completed = 0 AND mc.period_start_date IS NOT NULL THEN mc.id END) as active_pregnancy_count,
                COUNT(DISTINCT CASE WHEN mc.is_completed = 1 AND mc.period_end_date IS NOT NULL THEN mc.id END) as completed_pregnancy_count,
                p.life_stage_id,
                GROUP_CONCAT(DISTINCT CASE WHEN mc.is_completed = 0 THEN mc.period_start_date END) as pregnancy_dates,
                GROUP_CONCAT(DISTINCT CASE WHEN mc.is_completed = 1 THEN mc.period_end_date END) as delivery_dates
            FROM users u
            LEFT JOIN menstrual_cycles mc ON u.id = mc.user_id
            LEFT JOIN profiles p ON u.id = p.user_id
            GROUP BY u.id, p.life_stage_id
            HAVING active_pregnancy_count > 0 AND completed_pregnancy_count > 0
            ORDER BY u.id
        """)
        
        users_both = cursor.fetchall()
        print(f"Total users with BOTH pregnancy and postpartum data: {len(users_both)}\n")
        
        if users_both:
            print(f"{'User ID':<10} {'Active Preg':<15} {'Completed':<15} {'Life Stage':<15} {'Pregnancy Dates':<30} {'Delivery Dates':<30}")
            print("-" * 115)
            
            for user in users_both:
                print(f"{user['user_id']:<10} {user['active_pregnancy_count']:<15} {user['completed_pregnancy_count']:<15} {user['life_stage_id']:<15} {str(user['pregnancy_dates']):<30} {str(user['delivery_dates']):<30}")
        else:
            print("❌ NO USERS found with both pregnancy and postpartum data\n")
        
        # Summary statistics
        print("\n2️⃣  SUMMARY STATISTICS:")
        print("-" * 90)
        
        # Total users with active pregnancies
        cursor.execute("""
            SELECT COUNT(DISTINCT user_id) as count
            FROM menstrual_cycles
            WHERE is_completed = 0 AND period_start_date IS NOT NULL
        """)
        result = cursor.fetchone()
        active_pregnancy_users = result['count']
        
        # Total users with completed pregnancies (postpartum)
        cursor.execute("""
            SELECT COUNT(DISTINCT user_id) as count
            FROM menstrual_cycles
            WHERE is_completed = 1 AND period_end_date IS NOT NULL
        """)
        result = cursor.fetchone()
        postpartum_users = result['count']
        
        print(f"   Users with ACTIVE pregnancies:        {active_pregnancy_users}")
        print(f"   Users with POSTPARTUM data:           {postpartum_users}")
        print(f"   Users with BOTH:                      {len(users_both)}")
        
        if len(users_both) == 0:
            print(f"\n   📊 ANALYSIS:")
            print(f"      Active pregnancy users and postpartum users are DIFFERENT groups")
            print(f"      No user has progressed from active pregnancy to postpartum")
            print(f"      This is EXPECTED in test data (pregnancies aren't completed to delivery)")
        else:
            print(f"\n   📊 ANALYSIS:")
            print(f"      {len(users_both)} user(s) have realistic pregnancy progression")
            print(f"      These users have gone from active pregnancy to delivery to postpartum")
        
        # Show detailed data for users with both
        if len(users_both) > 0:
            print(f"\n3️⃣  DETAILED CYCLE DATA FOR USERS WITH BOTH:")
            print("-" * 90)
            
            for user in users_both:
                user_id = user['user_id']
                print(f"\n   USER {user_id}:")
                
                # Get active pregnancies
                cursor.execute("""
                    SELECT id, period_start_date, is_completed
                    FROM menstrual_cycles
                    WHERE user_id = %s AND is_completed = 0 AND period_start_date IS NOT NULL
                    ORDER BY period_start_date DESC
                """, (user_id,))
                active = cursor.fetchall()
                print(f"      Active pregnancies: {len(active)}")
                for cycle in active:
                    print(f"         - Cycle {cycle['id']}: Started {cycle['period_start_date']}")
                
                # Get completed pregnancies
                cursor.execute("""
                    SELECT id, period_start_date, period_end_date, is_completed
                    FROM menstrual_cycles
                    WHERE user_id = %s AND is_completed = 1 AND period_end_date IS NOT NULL
                    ORDER BY period_end_date DESC
                """, (user_id,))
                completed = cursor.fetchall()
                print(f"      Completed pregnancies (postpartum): {len(completed)}")
                for cycle in completed:
                    print(f"         - Cycle {cycle['id']}: {cycle['period_start_date']} → {cycle['period_end_date']}")
        
        print("\n" + "="*90 + "\n")

except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
