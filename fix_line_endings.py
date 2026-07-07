#!/usr/bin/env python3
"""Fix line ending issues in modified files"""

import os

files_to_check = [
    'engine/events/bus.py',
    'engine/routers/events_router.py',
    'engine/agents/pipeline.py',
    'engine/portfolio/tracker.py',
    'engine/routers/scanner_router.py',
    'engine/notifications/openclaw_notifier.py',
    'engine/main.py',
]

for filepath in files_to_check:
    if not os.path.exists(filepath):
        print(f"Skipped {filepath} (not found)")
        continue
    
    try:
        with open(filepath, 'rb') as f:
            content = f.read()
        
        # Replace CRLF with LF and remove null bytes
        content = content.replace(b'\r\n', b'\n')
        content = content.replace(b'\r', b'\n')
        content = content.replace(b'\x00', b'')
        
        with open(filepath, 'wb') as f:
            f.write(content)
        
        print(f"Fixed {filepath}")
    except Exception as e:
        print(f"Error fixing {filepath}: {e}")

print("Done")
