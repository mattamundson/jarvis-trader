#!/usr/bin/env python3
"""Add EventsFeedWidget JSX to page.tsx"""

with open('dashboard/app/page.tsx', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Check if already added
content = ''.join(lines)
if '<EventsFeedWidget' in content:
    print("EventsFeedWidget already added to JSX")
    exit(0)

# Find the grid closing tag and add before it
# Look for the pattern: <div className="grid gap-6 md:gap-8 lg:grid-cols-2">
# Then find the matching closing </div>

grid_start_line = -1
for i, line in enumerate(lines):
    if '<div className="grid gap-6 md:gap-8 lg:grid-cols-2">' in line:
        grid_start_line = i
        break

if grid_start_line > 0:
    # Now find the closing </div> for this grid
    # Count div nesting
    nesting = 0
    for i in range(grid_start_line, len(lines)):
        line = lines[i]
        # Count opening and closing divs in this line
        open_divs = line.count('<div')
        close_divs = line.count('</div>')
        
        nesting += open_divs - close_divs
        
        # When nesting becomes 0 again, we've found the matching close
        if nesting == 0 and i > grid_start_line:
            # This line has the closing </div>
            # Insert EventsFeedWidget before this line
            insert_line = '      <EventsFeedWidget />\n'
            lines.insert(i, insert_line)
            print(f"Added EventsFeedWidget at line {i+1}")
            break

# Write back
with open('dashboard/app/page.tsx', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Done")
