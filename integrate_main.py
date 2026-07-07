#!/usr/bin/env python3
"""Integrate events_router into main.py"""

import re

# Read main.py
with open('engine/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Check if events_router is already integrated
if 'events_router' in content or 'from routers.events_router' in content:
    print("events_router already integrated")
    exit(0)

# Find where other routers are imported
# Look for "from routers." pattern
router_imports = list(re.finditer(r'from routers\.\w+ import router as \w+', content))
if not router_imports:
    print("Could not find any router imports")
    exit(1)

# Get the last router import
last_import = router_imports[-1]
last_import_text = last_import.group(0)
last_import_pos = last_import.end()

# Add events_router import after the last router import
import_line = f'\nfrom routers.events_router import router as events_router'
content = content[:last_import_pos] + import_line + content[last_import_pos:]
print("Added events_router import")

# Now find where routers are included (app.include_router)
# Find all app.include_router calls
include_calls = list(re.finditer(r'app\.include_router\(\w+\)', content))
if not include_calls:
    print("Could not find any include_router calls")
    exit(1)

# Get the last include_router call
last_include = include_calls[-1]
last_include_text = last_include.group(0)
last_include_pos = last_include.end()

# Add events_router include after the last one
include_line = f'\napp.include_router(events_router)'
content = content[:last_include_pos] + include_line + content[last_include_pos:]
print("Added events_router include_router call")

# Now add the startup event publish
# Look for the lifespan startup or @app.on_event("startup")
# Find a good place to add publish_event call
if 'async def lifespan(app: FastAPI):' in content:
    # Find the startup section
    lifespan_start = content.find('async def lifespan(app: FastAPI):')
    # Find the first yield or code after the docstring
    lifespan_section = content[lifespan_start:lifespan_start+2000]
    
    # Find where to add the publish call - after any setup code, before yield
    if 'yield' in lifespan_section:
        yield_pos = lifespan_section.find('yield')
        actual_yield_pos = lifespan_start + yield_pos
        
        # Add before yield
        publish_call = '''# Publish startup event
    try:
        from events.bus import publish as publish_event
        publish_event('system', 'JARVIS engine started', severity='info')
    except Exception:
        pass
    
    '''
        content = content[:actual_yield_pos] + publish_call + content[actual_yield_pos:]
        print("Added publish_event call to lifespan startup")

# Write back to main.py
with open('engine/main.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Integration complete")
