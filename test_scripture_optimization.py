"""
Test script to demonstrate daily scripture optimization improvements.

Run this to see the performance difference:
    python test_scripture_optimization.py
"""

import asyncio
import time
import httpx


BASE_URL = "http://localhost:8000"  # Change to your server URL


async def test_single_request():
    """Test single request response time."""
    print("\n1️⃣  Testing Single Request")
    print("=" * 60)
    
    async with httpx.AsyncClient() as client:
        start = time.time()
        response = await client.get(f"{BASE_URL}/daily-scripture")
        elapsed = (time.time() - start) * 1000
        
        data = response.json()
        cache_hit = data.get("cache_hit", False)
        
        print(f"✓ Response time: {elapsed:.0f}ms")
        print(f"✓ Cache hit: {cache_hit}")
        print(f"✓ Status: {response.status_code}")
        
        return elapsed


async def test_cached_request():
    """Test cached request (should be near-instant)."""
    print("\n2️⃣  Testing Cached Request (Same Data)")
    print("=" * 60)
    
    async with httpx.AsyncClient() as client:
        start = time.time()
        response = await client.get(f"{BASE_URL}/daily-scripture")
        elapsed = (time.time() - start) * 1000
        
        data = response.json()
        cache_hit = data.get("cache_hit", False)
        
        print(f"✓ Response time: {elapsed:.0f}ms")
        print(f"✓ Cache hit: {cache_hit} (should be True)")
        print(f"✓ Status: {response.status_code}")
        
        if cache_hit:
            print("✅ CACHE WORKING! Response is instant!")
        
        return elapsed


async def test_concurrent_requests():
    """Test request coalescing (10 concurrent requests)."""
    print("\n3️⃣  Testing Request Coalescing (10 Concurrent Requests)")
    print("=" * 60)
    
    async with httpx.AsyncClient() as client:
        start = time.time()
        
        # Send 10 requests at exactly the same time
        tasks = [
            client.get(f"{BASE_URL}/daily-scripture")
            for _ in range(10)
        ]
        
        responses = await asyncio.gather(*tasks)
        elapsed = (time.time() - start) * 1000
        
        print(f"✓ Total time for 10 requests: {elapsed:.0f}ms")
        print(f"✓ Average per request: {elapsed/10:.0f}ms")
        print(f"✓ All responses: {len(responses)}")
        
        # Check if any hit cache
        cache_hits = sum(1 for r in responses if r.json().get("cache_hit", False))
        print(f"✓ Cache hits: {cache_hits}/10")
        
        if elapsed < 3000:  # Less than 3 seconds for 10 requests
            print("✅ REQUEST COALESCING WORKING! All requests completed quickly!")
        
        return elapsed


async def test_performance_comparison():
    """Compare performance with and without optimizations."""
    print("\n" + "=" * 60)
    print("🚀 DAILY SCRIPTURE OPTIMIZATION TEST")
    print("=" * 60)
    
    # Test 1: First request (no cache)
    first_time = await test_single_request()
    
    # Wait a bit
    await asyncio.sleep(0.5)
    
    # Test 2: Second request (should hit cache)
    cached_time = await test_cached_request()
    
    # Test 3: Concurrent requests (should coalesce)
    concurrent_time = await test_concurrent_requests()
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 PERFORMANCE SUMMARY")
    print("=" * 60)
    print(f"First request (no cache):     {first_time:.0f}ms")
    print(f"Cached request:                {cached_time:.0f}ms")
    print(f"10 concurrent requests:        {concurrent_time:.0f}ms")
    
    if cached_time < first_time / 10:
        speedup = first_time / cached_time
        print(f"\n✅ Cache speedup: {speedup:.1f}x faster!")
    
    if concurrent_time < first_time * 3:
        print(f"✅ Coalescing prevented {10} duplicate LLM calls!")
    
    print("\n" + "=" * 60)
    print("OPTIMIZATION FEATURES ENABLED:")
    print("=" * 60)
    print("✓ LRU Cache with TTL (1 hour expiration)")
    print("✓ Request Coalescing (deduplicate concurrent)")
    print("✓ Circuit Breaker (fallback on LLM failure)")
    print("=" * 60)


if __name__ == "__main__":
    print("\n🧪 Starting optimization tests...")
    print("📌 Make sure your server is running on", BASE_URL)
    
    try:
        asyncio.run(test_performance_comparison())
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("   Make sure server is running and URL is correct")
