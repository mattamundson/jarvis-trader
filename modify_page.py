#!/usr/bin/env python3
"""Modify dashboard page.tsx to add EventsFeedWidget"""

import re

# Read page.tsx
with open('dashboard/app/page.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# Check if EventsFeedWidget is already imported
if 'EventsFeedWidget' in content:
    print("EventsFeedWidget already imported")
    exit(0)

# Find the import section at the top
# Look for the last import statement
imports_match = re.search(r'(import.*?from [\'"].*?[\'"];)\n(?!import)', content, re.MULTILINE)
if imports_match:
    last_import = imports_match.group(1)
    new_import = f"import {{ EventsFeedWidget }} from '@/components/EventsFeedWidget';\n{last_import}"
    content = content.replace(last_import, new_import)
    print("Added EventsFeedWidget import")
else:
    print("Could not find import section to add EventsFeedWidget")
    exit(1)

# Now find a good place to add the widget in the JSX
# Look for the return statement and grid
# We want to add it in the lower section

# Find the grid container (look for className with "grid")
# Add it after other widgets
# Look for a pattern like "className="grid" and find a closing element to add after

# Simple approach: find the last <div className containing "grid" and add before the closing
if '<div className="grid gap-6 md:gap-8 lg:grid-cols-2">' in content:
    # This is likely the main grid, add EventsFeedWidget at the end
    # Find the closing </div> of this grid
    grid_start = content.rfind('<div className="grid gap-6 md:gap-8 lg:grid-cols-2">')
    # Find the closing div that matches this opening
    remaining = content[grid_start:]
    # Count divs to find the matching close
    # Simpler: just add EventsFeedWidget as a new div before the last </div>
    
    # Look for patterns and add the widget
    # Add it before the final closing divs
    pattern = r'(<div className="[^"]*grid[^"]*">.*?)<\/div>\s*<\/main>'
    
    def add_widget(match):
        grid_content = match.group(1)
        return f"{grid_content}\n      <EventsFeedWidget />\n    </div>\n  </main>"
    
    content = re.sub(pattern, add_widget, content, flags=re.DOTALL)
    print("Added EventsFeedWidget to page")
else:
    print("Could not find grid pattern to add widget")
    # Try alternative approach
    if '</main>' in content:
        # Add before the closing main tag
        content = content.replace(
            '</main>',
            '      <EventsFeedWidget />\n    </main>'
        )
        print("Added EventsFeedWidget before closing main tag")

# Write back to page.tsx
with open('dashboard/app/page.tsx', 'w', encoding='utf-8') as f:
    f.write(content)

print("Modification complete")
