#!/usr/bin/env python3
"""Test if main.py can be imported"""

import sys
sys.path.insert(0, 'engine')

try:
    import main
    print("SUCCESS: main.py imported successfully")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
