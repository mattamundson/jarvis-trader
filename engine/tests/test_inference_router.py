#!/usr/bin/env python3
"""
Test the hybrid inference router.
Run with: python engine/tests/test_inference_router.py
"""

import asyncio
import json
from engine.utils.inference_router import get_inference_router, InferenceProvider


async def test_ollama_connection():
    """Test if Ollama is reachable."""
    print("\n[TEST 1] Ollama Connection")
    print("─" * 60)
    
    router = get_inference_router()
    status = await router.test_connection()
    
    print(f"Ollama available: {status['ollama']['available']}")
    print(f"  Host: {status['ollama']['host']}")
    print(f"  Model: {status['ollama']['model']}")
    print(f"Anthropic available: {status['anthropic']['available']}")
    print(f"  Model: {status['anthropic']['model']}")
    
    return status['ollama']['available']


async def test_ollama_generate():
    """Test generating text with Ollama."""
    print("\n[TEST 2] Ollama Generation")
    print("─" * 60)
    
    router = get_inference_router()
    
    test_prompt = "Respond with exactly 10 words about trading. Be concise."
    print(f"Prompt: {test_prompt}")
    print("Generating...")
    
    response = await router.route_task(
        task_name="test_prompt",
        prompt=test_prompt,
        force_provider=InferenceProvider.OLLAMA,
    )
    
    if response:
        print(f"\nResponse ({len(response)} chars):")
        print(f"  {response[:200]}...")
        return True
    else:
        print("✗ Generation failed")
        return False


async def test_metrics():
    """Check recorded metrics."""
    print("\n[TEST 3] Metrics Recording")
    print("─" * 60)
    
    router = get_inference_router()
    
    # Run a few tasks to generate metrics
    for i in range(3):
        await router.route_task(
            task_name="metric_test",
            prompt=f"Response #{i+1}: Say 'OK' and stop.",
            force_provider=InferenceProvider.OLLAMA,
        )
    
    metrics = router.get_metrics()
    if metrics:
        print("Metrics recorded:")
        print(json.dumps(metrics, indent=2))
        return True
    else:
        print("✗ No metrics recorded")
        return False


async def main():
    """Run all tests."""
    print("=" * 60)
    print("HERMES INFERENCE ROUTER TEST SUITE")
    print("=" * 60)
    
    try:
        # Test 1: Connection
        ollama_ok = await test_ollama_connection()
        
        if not ollama_ok:
            print("\n⚠ Ollama not available. Skipping generation tests.")
            return
        
        # Test 2: Generation
        gen_ok = await test_ollama_generate()
        
        # Test 3: Metrics
        metrics_ok = await test_metrics()
        
        # Summary
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        print(f"Connection: {'✓ PASS' if ollama_ok else '✗ FAIL'}")
        print(f"Generation: {'✓ PASS' if gen_ok else '✗ FAIL'}")
        print(f"Metrics:    {'✓ PASS' if metrics_ok else '✗ FAIL'}")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
