#!/usr/bin/env python3
"""Find method definitions in pipeline.py"""

with open('engine/agents/pipeline.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines[:300], 1):
    if ('def ' in line or 'async def' in line) and not line.strip().startswith('#'):
        print(f"{i}: {line.rstrip()}")
