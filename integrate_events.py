#!/usr/bin/env python3
"""Script to integrate events router into main.py"""

import re

# Read main.py
with open('engine/main.py', 'r') as f:
    content = f.read()

# Check if events_router is already integrated
if 'from routers.events_router import router as events_router' in content:
    print("Events router already integrated")
    exit(0)

# Find where other routers are imported (look for the pattern)
# We'll add it after the imports section

# Find the last router import line
router_imports = re.findall(r'from routers\.\w+ import router as \w+', content)
if router_imports:
    last_import = router_imports[-1]
    print(f"Found last router import: {last_import}")
    
    # Add events_router import after the last router import
    new_import = f"{last_import}\nfrom routers.events_router import router as events_router"
    content = content.replace(last_import, new_import)
    print("Added events_router import")

# Now find where app.include_router is called and add events_router
# Look for the pattern app.include_router
include_patterns = re.findall(r'app\.include_router\(\w+\)', content)
if include_patterns:
    last_include = include_patterns[-1]
    print(f"Found last include_router: {last_include}")
    
    # Add events router include
    new_include = f"{last_include}\napp.include_router(events_router)"
    content = content.replace(last_include, new_include)
    print("Added events_router include_router call")

# Now add the publish_event call in the lifespan startup
# Look for the startup code
if '@app.on_event("startup")' in content or 'async def lifespan' in content:
    # Find a good place to add the publish call
    # Look for the startup function
    startup_match = re.search(r'(async def startup\(\):.*?)(?=\nasync def|$)', content, re.DOTALL)
    if startup_match:
        startup_func = startup_match.group(1)
        if 'publish_event' not in startup_func:
            # Add the import and call
            content = content.replace(
                startup_func,
                startup_func + "\n    from events.bus import publish as publish_event\n    publish_event('system', 'JARVIS engine started', severity='info')"
            )
            print("Added publish_event call to startup")

# Write back to main.py
with open('engine/main.py', 'w') as f:
    f.write(content)

print("Integration complete")
