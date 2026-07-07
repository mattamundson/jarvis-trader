#!/usr/bin/env python3
"""Fix the imports in page.tsx"""

with open('dashboard/app/page.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove the bad import we added
bad_import = "import { EventsFeedWidget } from '@/components/EventsFeedWidget';\n"
content = content.replace(bad_import, '')

# Find the proper place to add it - after all the imports
# Look for the pattern after all import statements

# Find the last import line (usually "import type {" or similar that spans multiple lines)
# Better approach: find the closing import statement

import_pattern = "import type {"
if import_pattern in content:
    # Find where this multiline import ends
    start = content.find(import_pattern)
    # Find the closing semicolon
    end = content.find("};", start)
    if end > 0:
        # Insert after this import
        insert_pos = end + 2  # After the };
        
        new_import = "\nimport { EventsFeedWidget } from '@/components/EventsFeedWidget';"
        
        # Find the next newline after the import ends
        next_newline = content.find('\n', insert_pos)
        if next_newline > 0:
            content = content[:next_newline+1] + new_import + content[next_newline+1:]
            print("Fixed import placement")

# Write back
with open('dashboard/app/page.tsx', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done")
