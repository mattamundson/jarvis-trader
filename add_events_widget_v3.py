#!/usr/bin/env python3
"""Add EventsFeedWidget to page.tsx - simpler approach"""

with open('dashboard/app/page.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# Check if already added
if '<EventsFeedWidget' in content:
    print("EventsFeedWidget already added to JSX")
    exit(0)

# Simple: find </main> and add the widget before it
if '</main>' in content:
    # Add a new section for the widget
    widget_section = '''
      <div className="mt-8">
        <EventsFeedWidget />
      </div>
    '''
    
    content = content.replace('</main>', widget_section + '\n</main>')
    print("Added EventsFeedWidget before closing main tag")
else:
    print("Could not find </main> tag")
    exit(1)

# Write back
with open('dashboard/app/page.tsx', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done")
