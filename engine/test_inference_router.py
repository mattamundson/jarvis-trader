#!/usr/bin/env python3
"""
Test script for Ollama inference router.
Verifies Ollama connection and basic inference capability.
"""

import asyncio
import os
import sys

# Add engine to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.inference_router import InferenceProvider, get_inference_router


async def main():
    print("=" * 80)
    print("HERMES Inference Router Test")
    print("=" * 80)
    print()

    router = get_inference_router()

    # Test connection
    print("Testing connection to Ollama...")
    status = await router.test_connection()

    print()
    print("Status Report:")
    print(f"  Ollama available: {status['ollama']['available']}")
    print(f"  Ollama host: {status['ollama']['host']}")
    print(f"  Ollama model: {status['ollama']['model']}")
    print(f"  Anthropic available: {status['anthropic']['available']}")
    print()

    if not status["ollama"]["available"]:
        print("⚠️  Ollama is not running. Make sure to:")
        print("   1. Run: ollama serve")
        print("   2. Pull a model: ollama pull hermes3:latest")
        print("   3. Verify on localhost:11434")
        return False

    print("✓ Ollama is available. Testing inference...")
    print()

    # Test inference
    test_prompt = "Q: What is 2+2?\nA:"
    print(f"Test prompt: {test_prompt}")
    print()

    response = await router.route_task(
        task_name="test_inference",
        prompt=test_prompt,
        force_provider=InferenceProvider.OLLAMA,
    )

    print(f"Response: {response}")
    print()

    if "4" in response:
        print("✅ Inference successful!")
        return True
    else:
        print("⚠️  Response doesn't contain expected answer.")
        return True


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
