#!/usr/bin/env python3
"""
Fix OpenClaw LLM provider lockout — run via WSL after topping up API credits.

Usage (from Windows):
    wsl -d Ubuntu -e python3 /mnt/c/Users/mattm/ThinkorSwim/jarvis-trader/scripts/fix-openclaw-lockout.py

Usage (from WSL):
    python3 /mnt/c/Users/mattm/ThinkorSwim/jarvis-trader/scripts/fix-openclaw-lockout.py
"""
import json
import subprocess
from datetime import datetime

PATH = "/root/.openclaw/agents/main/agent/auth-profiles.json"

# Read via WSL if running on Windows
import os, sys

def run():
    with open(PATH) as f:
        d = json.load(f)

    stats = d.get("usageStats", {})
    cleared = []

    for profile_id, profile in stats.items():
        changes = {}

        # Clear Anthropic billing disable
        if profile.get("disabledReason") == "billing" or "disabledUntil" in profile:
            profile.pop("disabledUntil", None)
            profile.pop("disabledReason", None)
            profile["errorCount"] = 0
            profile.pop("lastFailureAt", None)
            profile["failureCounts"] = {}
            changes["billing_lockout"] = "cleared"

        # Clear rate-limit cooldown
        if "cooldownUntil" in profile:
            profile.pop("cooldownUntil", None)
            profile.pop("cooldownReason", None)
            profile.pop("cooldownModel", None)
            profile["errorCount"] = 0
            profile.pop("lastFailureAt", None)
            profile["failureCounts"] = {}
            changes["cooldown"] = "cleared"

        if changes:
            cleared.append((profile_id, changes))

    with open(PATH, "w") as f:
        json.dump(d, f, indent=2)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Cleared {len(cleared)} profile(s):")
    for pid, changes in cleared:
        print(f"  {pid}: {changes}")

    if not cleared:
        print("  Nothing to clear — no active lockouts found.")

    print("\nRestart OpenClaw gateway:")
    print("  wsl -d Ubuntu -e systemctl --user restart openclaw-gateway.service")

if __name__ == "__main__":
    run()
