import requests
import json

# Test health trends endpoint
url = "http://52.54.164.79:8002/api/health-trends"
params = {"user_id": 2, "period": "7d"}

print(f"Testing: {url}")
print(f"Params: {params}\n")

try:
    response = requests.get(url, params=params, timeout=30)
    print(f"Status Code: {response.status_code}")
    print(f"Response Length: {len(response.text)} chars\n")
    
    if response.status_code == 200:
        data = response.json()
        print(f"Service: {data.get('service')}")
        print(f"Status: {data.get('status')}")
        print(f"Fetched: {data.get('fetched')}")
        
        if 'health_trends' in data:
            print("\n✅ Has health_trends data")
            health_trends = data['health_trends']
            if 'sleep_energy_correlation_diagram' in health_trends:
                bars = health_trends['sleep_energy_correlation_diagram'].get('bars', [])
                print(f"Bars count: {len(bars)}")
                if bars:
                    values = [b['value'] for b in bars]
                    print(f"Bar values: {values}")
                    
                    # Check if these are the hardcoded fallback values
                    fallback_values = [74, 72, 65, 82, 78, 85, 80]
                    if values == fallback_values:
                        print("\n🚨 PROBLEM FOUND: Using static fallback data!")
                    else:
                        print("\n✅ Values are different from fallback (personalized)")
        else:
            print("\n❌ No health_trends in response")
            print(f"\nFull response:\n{json.dumps(data, indent=2)[:500]}...")
    else:
        print(f"Error: {response.text[:200]}")
        
except Exception as e:
    print(f"Request failed: {e}")
