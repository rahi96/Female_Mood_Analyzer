#!/usr/bin/env python3
import requests
import json

# Test users
test_users = [16, 2, 6]

for user_id in test_users:
    print(f"\n{'='*80}")
    print(f"Testing user {user_id}")
    print(f"{'='*80}")
    try:
        response = requests.get(f'http://localhost:8002/api/v1/support/insights?user_id={user_id}', timeout=15)
        data = response.json()
        print(json.dumps(data, indent=2))
    except Exception as e:
        print(f"ERROR: {e}")
