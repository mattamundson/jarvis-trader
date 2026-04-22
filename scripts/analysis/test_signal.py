#!/usr/bin/env python3
"""
Quick test: send a signal through the full pipeline.
Usage: python scripts/test_signal.py [symbol] [action]
Example: python scripts/test_signal.py MES LONG
"""
import sys
import json
import urllib.request
import urllib.error

ENGINE_URL = "http://localhost:8010"

def send_signal(symbol="MES", action="LONG", price=5000.0):
    """Send a signal via POST /pipeline/run-signal and print result."""
    payload = json.dumps({"symbol": symbol, "action": action, "price": price, "source": "test_script"}).encode()
    req = urllib.request.Request(
        f"{ENGINE_URL}/pipeline/run-signal",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            print(f"✓ Signal sent: {symbol} {action}")
            print(json.dumps(result, indent=2))
            return result
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"✗ HTTP {e.code}: {body}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"✗ Cannot connect to engine at {ENGINE_URL}")
        print(f"  Start the engine: start_jarvis.bat")
        sys.exit(1)

def check_health():
    """Quick health check before sending signal."""
    try:
        with urllib.request.urlopen(f"{ENGINE_URL}/health", timeout=5) as resp:
            data = json.loads(resp.read())
            status = data.get("status", "unknown")
            print(f"Engine: {status}")
            return True
    except Exception:
        return False

if __name__ == "__main__":
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "MES"
    action = sys.argv[2].upper() if len(sys.argv) > 2 else "LONG"
    price = float(sys.argv[3]) if len(sys.argv) > 3 else 5000.0

    if action not in ("LONG", "SHORT", "CLOSE"):
        print(f"Invalid action: {action}. Must be LONG, SHORT, or CLOSE.")
        sys.exit(1)

    print(f"Testing signal: {symbol} {action} @ {price}")
    print(f"Engine: {ENGINE_URL}")
    print()

    if not check_health():
        print("Engine is not running. Start with: start_jarvis.bat")
        sys.exit(1)

    send_signal(symbol, action, price)
