#!/usr/bin/env python3
"""Debug script to test vitality calculation locally."""
import sys
import os

# Add ai module to path
sys.path.insert(0, os.path.dirname(__file__))

# Set mock data for testing
os.environ['USE_MOCK_DATA'] = '0'  # Use real DB

try:
    from ai.services.lifelong_thriving_service import LifelongThrivingService
    from datetime import datetime
    
    print("✅ Imports successful")
    
    # Test with user 10
    user_id = 10
    service = LifelongThrivingService(user_id)
    print(f"✅ Service created for user {user_id}")
    
    # Try getting vitality overview
    print("\n🔵 Calling get_vitality_overview()...")
    response = service.get_vitality_overview()
    print(f"✅ Response received")
    print(f"  - Vitality Index: {response.vitality_index}")
    print(f"  - Level: {response.vitality_level}")
    print(f"  - Dimensions: {len(response.dimensions)}")
    print(f"  - Eligibility: {response.eligibility_status}")
    print(f"  - Data Completeness: {response.data_completeness}")
    
    if response.dimensions:
        print(f"\n  Dimensions:")
        for dim in response.dimensions:
            print(f"    - {dim.name}: {dim.score}")
    else:
        print(f"\n  ❌ No dimensions returned - calculation may have failed")
        print(f"  - Fallback response suggests exception in pipeline")
        
except Exception as e:
    print(f"❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
