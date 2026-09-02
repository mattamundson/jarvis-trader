#!/usr/bin/env python3
"""Check tracker.py open_trade method format"""

with open('engine/portfolio/tracker.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Line 140 should be open_trade
for i in range(139, 220):
    print(f"{i+1}: {lines[i].rstrip()}")
