#!/usr/bin/env python3
"""Check page.tsx for issues"""

with open('dashboard/app/page.tsx', 'r', encoding='utf-8', errors='replace') as f:
    lines = f.readlines()

# Print around line 633
for i in range(max(0, 625), min(len(lines), 633)):
    print(f"{i+1}: {lines[i].rstrip()}")

print(f"\nTotal lines: {len(lines)}")
