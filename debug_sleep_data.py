#!/usr/bin/env python
"""Debug script to check what sleep data exists for user 16"""

import json
from ai.utils.db import get_connection
from datetime import datetime, timedelta

user_id = 16

with get_connection() as conn:
    cur = conn.cursor()
    
    # Check skin scans
    cur.execute("""
        SELECT DATE(created_at) as scan_date, COUNT(*) as count, AVG(overall_score) as avg_score
        FROM skin_scans
        WHERE user_id = %s AND created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        GROUP BY DATE(created_at)
        ORDER BY scan_date DESC
    """, (user_id,))
    
    print("=== SKIN SCANS (Last 7 days) ===")
    skin_rows = cur.fetchall()
    for row in skin_rows:
        print(f"  {row.get('scan_date')}: {row.get('count')} scans, avg score {row.get('avg_score')}")
    
    # Check terra_activity_data - ALL records
    cur.execute("""
        SELECT type, DATE(created_at) as data_date, COUNT(*) as count
        FROM terra_activity_data
        WHERE user_id = %s AND created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        GROUP BY type, DATE(created_at)
        ORDER BY data_date DESC, type
    """, (user_id,))
    
    print("\n=== TERRA_ACTIVITY_DATA by type (Last 7 days) ===")
    terra_rows = cur.fetchall()
    if not terra_rows:
        print("  NO RECORDS FOUND")
    else:
        for row in terra_rows:
            print(f"  {row.get('data_date')} | type={row.get('type')} | count={row.get('count')}")
    
    # Check actual sleep records
    cur.execute("""
        SELECT DATE(created_at) as data_date, type, payload, created_at
        FROM terra_activity_data
        WHERE user_id = %s AND created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        ORDER BY created_at DESC
        LIMIT 20
    """, (user_id,))
    
    print("\n=== TERRA_ACTIVITY_DATA samples (Last 20 records) ===")
    terra_samples = cur.fetchall()
    for i, row in enumerate(terra_samples):
        print(f"\n  Record {i+1}:")
        print(f"    Date: {row.get('data_date')}")
        print(f"    Type: {row.get('type')}")
        print(f"    Created: {row.get('created_at')}")
        
        payload = row.get('payload')
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except:
                pass
        
        if isinstance(payload, dict):
            # Print first level keys
            if 'data' in payload and isinstance(payload['data'], list) and len(payload['data']) > 0:
                first_data = payload['data'][0]
                print(f"    Data[0] keys: {list(first_data.keys()) if isinstance(first_data, dict) else 'N/A'}")
                if 'duration' in first_data:
                    print(f"    Duration: {first_data['duration']}")
            else:
                print(f"    Payload keys: {list(payload.keys())}")

print("\n=== DONE ===")
