#!/usr/bin/env python3
"""Add EventsFeedWidget to page.tsx"""

with open('dashboard/app/page.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# Check if already added
if 'EventsFeedWidget' in content:
    print("EventsFeedWidget already in page.tsx")
    exit(0)

# Add import at the top after the other imports
# Find the last import line
import_lines = []
lines = content.split('\n')
last_import_idx = 0

for i, line in enumerate(lines):
    if line.startswith('import ') or line.startswith('from '):
        last_import_idx = i

# Add the new import after the last import
if last_import_idx > 0:
    lines.insert(last_import_idx + 1, "import { EventsFeedWidget } from '@/components/EventsFeedWidget';")
    content = '\n'.join(lines)
    print("Added EventsFeedWidget import")

# Now add the widget to the JSX
# Find a good place in the dashboard grid - add as a new grid item
# Look for the grid container and add the widget

# Find the main grid that contains other widgets
# Usually it's near the end, look for className="grid gap-6"
# We'll add it before the closing grid div

if '<div className="grid gap-6 md:gap-8 lg:grid-cols-2">' in content:
    # Add the widget as a new grid item at the end, before closing div
    # Find the last closing </div> before </main>
    
    # More surgical approach: find a place to add it
    # Look for PortfolioMetrics or similar widget and add after
    
    # Simple approach: add before the last </div> that closes the grid
    lines = content.split('\n')
    
    # Find the line with the grid and then find its closing div
    grid_start = -1
    for i, line in enumerate(lines):
        if '<div className="grid gap-6 md:gap-8 lg:grid-cols-2">' in line:
            grid_start = i
            break
    
    if grid_start > 0:
        # Count nested divs to find the matching closing div
        div_count = 0
        for i in range(grid_start, len(lines)):
            line = lines[i]
            # Count opening divs
            div_count += line.count('<div')
            # Count closing divs
            div_count -= line.count('</div>')
            
            # When we get back to 0, we've found the matching close
            if div_count == 0 and i > grid_start:
                # Insert EventsFeedWidget before this closing div
                indent = '      '
                lines.insert(i, f'{indent}<EventsFeedWidget />')
                print("Added EventsFeedWidget to grid")
                break
    
    content = '\n'.join(lines)

# Write back
with open('dashboard/app/page.tsx', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done")
