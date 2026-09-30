"""
Diagnostic script to check pregnancy/postpartum API data consistency.
Traces profile_id, journey_id, and titles across pregnancy/postpartum life journey.
"""

import json
from ai.utils.db import get_connection

def diagnose_tables():
    """Check table structures and find profile_id/journey_id issues."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        print("\n" + "="*80)
        print("PREGNANCY/POSTPARTUM SCHEMA DIAGNOSIS")
        print("="*80)
        
        # 1. Check user_pregnancies table structure
        print("\n[TABLE 1] user_pregnancies - STRUCTURE")
        print("-" * 80)
        cursor.execute("DESCRIBE user_pregnancies")
        columns = cursor.fetchall()
        for col in columns:
            print(f"  {col}")
        
        # Check if profile_id exists
        has_profile_id = any(col.get('Field') == 'profile_id' for col in columns)
        has_journey_id = any(col.get('Field') == 'journey_id' for col in columns)
        print(f"\n  ✓ Has profile_id: {has_profile_id}")
        print(f"  ✓ Has journey_id: {has_journey_id}")
        
        # 2. Check postpartum_recoveries table structure
        print("\n[TABLE 2] postpartum_recoveries - STRUCTURE")
        print("-" * 80)
        cursor.execute("DESCRIBE postpartum_recoveries")
        columns = cursor.fetchall()
        for col in columns:
            print(f"  {col}")
        
        # Check if profile_id exists
        has_profile_id = any(col.get('Field') == 'profile_id' for col in columns)
        has_journey_id = any(col.get('Field') == 'journey_id' for col in columns)
        print(f"\n  ✓ Has profile_id: {has_profile_id}")
        print(f"  ✓ Has journey_id: {has_journey_id}")
        
        # 3. Check user 6 pregnancy data
        print("\n[USER 6] Pregnancy Journey - DATA TRACE")
        print("-" * 80)
        cursor.execute("""
            SELECT id, user_id, profile_id, journey_id, status, due_date, delivery_date
            FROM user_pregnancies
            WHERE user_id = 6
        """)
        pregnancies = cursor.fetchall()
        if pregnancies:
            for preg in pregnancies:
                print(f"  Pregnancy ID: {preg.get('id')}")
                print(f"    - user_id: {preg.get('user_id')}")
                print(f"    - profile_id: {preg.get('profile_id')} {'[MISSING!]' if not preg.get('profile_id') else ''}")
                print(f"    - journey_id: {preg.get('journey_id')} {'[MISSING!]' if not preg.get('journey_id') else ''}")
                print(f"    - status: {preg.get('status')}")
                print(f"    - due_date: {preg.get('due_date')}")
                print(f"    - delivery_date: {preg.get('delivery_date')}")
        else:
            print("  [NO USER_PREGNANCIES RECORDS FOUND]")
        
        # 4. Check postpartum recovery data for user 6
        print("\n[USER 6] Postpartum Recovery - DATA TRACE")
        print("-" * 80)
        cursor.execute("""
            SELECT id, user_id, profile_id, journey_id, delivery_date, current_week
            FROM postpartum_recoveries
            WHERE user_id = 6
        """)
        postpartums = cursor.fetchall()
        if postpartums:
            for pp in postpartums:
                print(f"  Postpartum ID: {pp.get('id')}")
                print(f"    - user_id: {pp.get('user_id')}")
                print(f"    - profile_id: {pp.get('profile_id')} {'[MISSING!]' if not pp.get('profile_id') else ''}")
                print(f"    - journey_id: {pp.get('journey_id')} {'[MISSING!]' if not pp.get('journey_id') else ''}")
                print(f"    - delivery_date: {pp.get('delivery_date')}")
                print(f"    - current_week: {pp.get('current_week')}")
        else:
            print("  [NO POSTPARTUM_RECOVERIES RECORDS FOUND]")
        
        # 5. Check user 6 profile data
        print("\n[USER 6] Profile - REFERENCE DATA")
        print("-" * 80)
        cursor.execute("""
            SELECT u.id as user_id, p.id as profile_id, p.life_stage_id, u.email
            FROM users u
            LEFT JOIN profiles p ON u.id = p.user_id
            WHERE u.id = 6
        """)
        profile = cursor.fetchone()
        if profile:
            print(f"  user_id: {profile.get('user_id')}")
            print(f"  profile_id: {profile.get('profile_id')}")
            print(f"  life_stage_id: {profile.get('life_stage_id')}")
            print(f"  email: {profile.get('email')}")
        else:
            print("  [USER 6 NOT FOUND]")
        
        # 6. Check how pregnancy API is returning data
        print("\n[API RESPONSE] Pregnancy Summary for User 6")
        print("-" * 80)
        from ai.services.pregnancy_service import pregnancy_summary
        try:
            response = pregnancy_summary(6)
            print(f"  Response keys: {list(response.keys())}")
            if 'profile_id' in response:
                print(f"  ✓ profile_id IS in response: {response['profile_id']}")
            else:
                print(f"  ✗ profile_id NOT in response [MISSING!]")
            if 'journey_id' in response:
                print(f"  ✓ journey_id IS in response: {response['journey_id']}")
            else:
                print(f"  ✗ journey_id NOT in response [MISSING!]")
            # Show first few keys
            for key in list(response.keys())[:5]:
                print(f"    - {key}: {response.get(key)}")
        except Exception as e:
            print(f"  Error: {e}")
        
        # 7. Check profile_id connection to other life journeys
        print("\n[CROSS-JOURNEY] Profile Connections")
        print("-" * 80)
        cursor.execute("""
            SELECT 
                p.id as profile_id,
                (SELECT COUNT(*) FROM user_pregnancies WHERE profile_id = p.id) as pregnancy_journeys,
                (SELECT COUNT(*) FROM postpartum_recoveries WHERE profile_id = p.id) as postpartum_journeys
            FROM profiles p
            WHERE p.user_id = 6
        """)
        cross = cursor.fetchone()
        if cross:
            print(f"  profile_id {cross.get('profile_id')}:")
            print(f"    - Linked pregnancy journeys: {cross.get('pregnancy_journeys')}")
            print(f"    - Linked postpartum journeys: {cross.get('postpartum_journeys')}")
        
        print("\n" + "="*80)

if __name__ == "__main__":
    diagnose_tables()
