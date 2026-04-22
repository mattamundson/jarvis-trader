#!/usr/bin/env python3
"""Find grid location in page.tsx"""

with open('dashboard/app/page.tsx', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'grid' in line.lower() and 'className' in line:
        print(f"{i+1}: {line.rstrip()}")
