#!/usr/bin/env python3
"""Update prd.json and progress.txt for US-2402"""

import json

# Update prd.json
try:
    with open('prd.json', 'r') as f:
        prd = json.load(f)
    
    # Find and update US-2402
    for story in prd.get('stories', []):
        if story.get('id') == 'US-2402':
            story['passes'] = True
            print(f"Updated US-2402 in prd.json: passes=true")
            break
    
    with open('prd.json', 'w') as f:
        json.dump(prd, f, indent=2)
except Exception as e:
    print(f"Error updating prd.json: {e}")

# Update progress.txt
progress_entry = """## [2026-04-04] - US-2402: Events Ring Buffer + Feed + Dashboard Widget
- Created engine/events/__init__.py (empty)
- Created engine/events/bus.py (150-event ring buffer, publish, get_recent, detect_regime_change)
- Created engine/routers/events_router.py (GET /events/recent endpoint)
- Integrated publish_event into engine/agents/pipeline.py (pipeline_run events)
- Integrated publish_event into engine/portfolio/tracker.py (trade_opened, trade_closed events)
- Integrated publish_event into engine/routers/scanner_router.py (signal_fired, regime_change events)
- Added notify_regime_change async function to engine/notifications/openclaw_notifier.py
- Created dashboard/components/EventsFeedWidget.tsx (React client component, useSWR polling)
- Added JarvisEvent and EventsResponse interfaces to dashboard/lib/api.ts
- Integrated EventsFeedWidget import and usage into dashboard/app/page.tsx
- Created engine/tests/test_events_bus.py with 7 comprehensive tests - ALL PASS
- Status: COMPLETE - All tests pass, events system fully operational
"""

with open('progress.txt', 'a') as f:
    f.write('\n' + progress_entry + '\n')

print("Updated progress.txt")
print("Done")
