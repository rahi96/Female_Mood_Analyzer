#!/usr/bin/env python3
"""View all users with pregnancy data - visual display."""

import sys
sys.path.insert(0, '/app')

from ai.utils.db import get_connection
from datetime import datetime

print("\n" + "="*120)
print("👶 PREGNANCY USERS IN DATABASE - DETAILED VIEW")
print("="*120)

try:
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Get all users with active pregnancy
        print("\n📋 FETCHING PREGNANCY DATA...")
        cursor.execute("""
            SELECT 
                u.id,
                u.username,
                u.email,
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
        
        print(f"\n✅ TOTAL USERS WITH ACTIVE PREGNANCY: {len(pregnancy_users)}")
        print("\n" + "-"*120)
        print(f"{'User ID':<8} {'Username':<20} {'Email':<30} {'Life Stage':<12} {'Pregnancy Start':<20} {'Weeks Pregnant':<15}")
        print("-"*120)
        
        for i, user in enumerate(pregnancy_users, 1):
            user_id = user['id']
            username = user['username'][:19] if user['username'] else "N/A"
            email = user['email'][:29] if user['email'] else "N/A"
            life_stage = user['life_stage_id'] if user['life_stage_id'] else "NULL"
            preg_start = user['period_start_date'] if user['period_start_date'] else "N/A"
            
            # Calculate weeks pregnant
            if user['period_start_date']:
                today = datetime.now().date()
                preg_date = user['period_start_date']
                weeks = (today - preg_date).days // 7
                weeks_str = f"{weeks} weeks"
            else:
                weeks_str = "N/A"
            
            print(f"{user_id:<8} {username:<20} {email:<30} {life_stage:<12} {str(preg_start):<20} {weeks_str:<15}")
        
        print("\n" + "="*120)
        print(f"\n📊 SUMMARY:")
        print(f"   Total pregnant users: {len(pregnancy_users)}")
        print(f"   Average weeks pregnant: {sum((datetime.now().date() - u['period_start_date']).days // 7 for u in pregnancy_users if u['period_start_date']) / len(pregnancy_users) if pregnancy_users else 0:.1f} weeks")
        
        # Show life stage distribution
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
        
        life_stages = cursor.fetchall()
        print(f"\n   By Life Stage:")
        for stage in life_stages:
            print(f"      Life Stage {stage['life_stage_id']}: {stage['count']} users")
        
        print("\n" + "="*120 + "\n")

except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
