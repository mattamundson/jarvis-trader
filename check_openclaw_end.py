#!/usr/bin/env python3
"""Check end of openclaw_notifier.py"""

with open('engine/notifications/openclaw_notifier.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Print last 50 lines
for i in range(max(0, len(lines)-50), len(lines)):
    print(f"{i+1}: {lines[i].rstrip()}")
