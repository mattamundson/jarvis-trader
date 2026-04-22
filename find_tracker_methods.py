#!/usr/bin/env python3
"""Find method definitions in tracker.py"""

with open('engine/portfolio/tracker.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines[:400], 1):
    if ('def ' in line or 'async def' in line) and not line.strip().startswith('#'):
        print(f"{i}: {line.rstrip()}")
