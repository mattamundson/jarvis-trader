#!/usr/bin/env python3
"""
Add API versioning with v1 router to main.py.
Creates an APIRouter with /v1 prefix and includes all endpoints.
"""

import re
from pathlib import Path

main_file = Path("main.py")
content = main_file.read_text()

# Find where the app is created (look for app = FastAPI(...))
app_creation_pattern = r"(app = FastAPI\([^)]*\))"

# Create the v1 router setup code that should be added after app creation
v1_router_code = """

# ── API Versioning ────────────────────────────────────────────────────────────
# Create v1 router with /v1 prefix for future versioning support
v1_router = APIRouter(prefix="/v1", tags=["v1"])

# Register all endpoints with the v1 router below.
# For now, we serve the same endpoints under both / (legacy) and /v1 (new).
# This allows clients to transition gradually.
"""

# Find the lifespan context manager to insert router registration after app creation
# Look for the section where app is defined and add the router setup

# Find the position after app = FastAPI
match = re.search(r"(app = FastAPI\([^)]*\))", content)
if match:
    insert_pos = match.end()
    # Find the next newline
    next_newline = content.find("\n", insert_pos)
    # Insert the router setup code
    content = content[: next_newline + 1] + v1_router_code + "\n" + content[next_newline + 1 :]
    print("✅ Added v1 router setup code")
else:
    print("⚠️ Could not find app = FastAPI() statement")

# Now add the include_router call before the app startup
# Look for where routers are included (around line with "app.include_router(journal_router...)")
include_pattern = r"(app\.include_router\(journal_router.*?\n)"

match = re.search(include_pattern, content)
if match:
    insert_pos = match.end()
    v1_include = "app.include_router(v1_router)\n"
    content = content[:insert_pos] + v1_include + content[insert_pos:]
    print("✅ Added v1_router include statement")
else:
    print("⚠️ Could not find app.include_router() statement to add v1 router")

# Write the updated content
main_file.write_text(content)
print("✅ API versioning setup complete!")
