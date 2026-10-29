#!/usr/bin/env python3
"""
Windows pusher script for live ES order flow.
Reads flow snapshot JSON (default: ~\\tape\\state\\flow-latest.json) every 5s and pushes to Vercel.
Standard library only. Never crashes. Logs failures only.

Environment variables:
  FLOW_SNAPSHOT_PATH  - Path to flow snapshot JSON (default: ~\\tape\\state\\flow-latest.json)
  FLOW_PUSH_URL       - Dashboard ingest endpoint URL (required)
  FLOW_INGEST_TOKEN   - Bearer token for authentication (required)
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
from typing import Any, Optional


def sanitize_flow_data(raw: Any) -> Optional[dict]:
    """Strip sensitive data and validate schema."""
    if not isinstance(raw, dict):
        return None
    
    try:
        es = raw.get("es", {})
        nq = raw.get("nq", {})
        gex = raw.get("gex", {})
        gates = raw.get("gates", [])
        
        sanitized = {
            "ts": str(raw.get("ts", "")),
            "es": {
                "last": float(es.get("last", 0)),
                "vwap": float(es.get("vwap", 0)),
                "onHigh": float(es.get("onHigh", 0)),
                "onLow": float(es.get("onLow", 0)),
                "cvd": float(es.get("cvd", 0)),
                "cvdLow": float(es.get("cvdLow", 0)),
                "bars1m": [
                    {
                        "ts": str(bar.get("ts", "")),
                        "open": float(bar.get("open", 0)),
                        "high": float(bar.get("high", 0)),
                        "low": float(bar.get("low", 0)),
                        "close": float(bar.get("close", 0)),
                        "volume": float(bar.get("volume", 0)),
                    }
                    for bar in es.get("bars1m", [])
                ],
                "deltaAtPrice": [
                    {
                        "price": float(d.get("price", 0)),
                        "bidLots": float(d.get("bidLots", 0)),
                        "askLots": float(d.get("askLots", 0)),
                    }
                    for d in es.get("deltaAtPrice", [])
                ],
                "bigPrints": [
                    {
                        "ts": str(p.get("ts", "")),
                        "price": float(p.get("price", 0)),
                        "lots": float(p.get("lots", 0)),
                        "side": str(p.get("side", "bid")),
                    }
                    for p in es.get("bigPrints", [])
                ],
            },
            "nq": {
                "last": float(nq.get("last", 0)),
                "vwap": float(nq.get("vwap", 0)),
            },
            "gex": {
                "callWall": float(gex.get("callWall", 0)),
                "putWall": float(gex.get("putWall", 0)),
                "flip": float(gex.get("flip", 0)),
                "pin": float(gex.get("pin", 0)),
                "asOf": str(gex.get("asOf", "")),
            },
            "gates": [
                {
                    "level": float(g.get("level", 0)),
                    "status": str(g.get("status", "untested")),
                    "closeCount": int(g.get("closeCount", 0)),
                }
                for g in gates
            ],
        }
        
        return sanitized
    except (KeyError, ValueError, TypeError) as e:
        print(f"[ERROR] Schema validation failed: {e}", flush=True)
        return None


def push_flow(url: str, token: str, data: dict) -> bool:
    """POST sanitized flow to ingest endpoint. Returns True on success."""
    try:
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                return True
            else:
                print(f"[ERROR] Push failed with status {response.status}", flush=True)
                return False
    except urllib.error.HTTPError as e:
        print(f"[ERROR] HTTP {e.code}: {e.reason}", flush=True)
        return False
    except urllib.error.URLError as e:
        print(f"[ERROR] Network error: {e.reason}", flush=True)
        return False
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}", flush=True)
        return False


def retry_push(url: str, token: str, data: dict, max_retries: int = 3) -> bool:
    """Push with exponential backoff."""
    for attempt in range(max_retries):
        if push_flow(url, token, data):
            return True
        if attempt < max_retries - 1:
            wait = 2 ** attempt
            time.sleep(wait)
    return False


def main():
    flow_path = os.environ.get(
        "FLOW_SNAPSHOT_PATH",
        os.path.expanduser(r"~\tape\state\flow-latest.json")
    )
    push_url = os.environ.get("FLOW_PUSH_URL")
    token = os.environ.get("FLOW_INGEST_TOKEN")
    
    if not push_url:
        print("[ERROR] FLOW_PUSH_URL not set in environment", flush=True)
        sys.exit(1)
    
    if not token:
        print("[ERROR] FLOW_INGEST_TOKEN not set in environment", flush=True)
        sys.exit(1)
    
    print(f"[INFO] Watching {flow_path}", flush=True)
    print(f"[INFO] Pushing to {push_url}", flush=True)
    
    while True:
        try:
            if not os.path.exists(flow_path):
                time.sleep(5)
                continue
            
            with open(flow_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            
            sanitized = sanitize_flow_data(raw)
            
            if not sanitized:
                print("[ERROR] Failed to sanitize flow data", flush=True)
                time.sleep(5)
                continue
            
            success = retry_push(push_url, token, sanitized)
            
            if not success:
                print(f"[ERROR] Failed to push after retries at {sanitized['ts']}", flush=True)
            
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON in {flow_path}: {e}", flush=True)
        except Exception as e:
            print(f"[ERROR] Unexpected error in main loop: {e}", flush=True)
        
        time.sleep(5)


if __name__ == "__main__":
    main()
