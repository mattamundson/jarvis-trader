#!/usr/bin/env python3
"""Integrate publish_event into pipeline.py analyze_and_decide method"""

import re

# Read pipeline.py
with open('engine/agents/pipeline.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Check if publish_event is already integrated
if 'publish_event' in content and 'from events.bus import publish' in content:
    print("publish_event already integrated into pipeline.py")
    exit(0)

# Find the analyze_and_decide method
# Look for "async def analyze_and_decide("
analyze_method_match = re.search(
    r'(async def analyze_and_decide\(.*?\n(?:.*?\n)*?.*?return pipeline_result)',
    content,
    re.DOTALL
)

if not analyze_method_match:
    print("Could not find analyze_and_decide method or return statement")
    # Try a different pattern
    print("Looking for the method...")
    if 'async def analyze_and_decide' in content:
        print("Found analyze_and_decide method")
        # Find the next return statement after the method
        method_start = content.find('async def analyze_and_decide')
        # Find "return pipeline_result" after this
        return_pos = content.find('return pipeline_result', method_start)
        if return_pos > 0:
            print(f"Found return at position {return_pos}")
            # Get the context
            context_start = max(0, return_pos - 200)
            print(f"Context: ...{content[context_start:return_pos+50]}...")
    exit(1)

# Add the publish call before the return
new_content = content.replace(
    'return pipeline_result',
    '''# Publish pipeline result event
        try:
            from events.bus import publish as publish_event
            symbol_val = kwargs.get('symbol', 'UNKNOWN')
            action = pipeline_result.get('action', 'HOLD').upper() if pipeline_result else 'HOLD'
            conviction = pipeline_result.get('conviction', 0) if pipeline_result else 0
            publish_event(
                'pipeline_run',
                f'{symbol_val} → {action} conviction={conviction:.0%}',
                symbol=symbol_val,
                severity='info'
            )
        except Exception as e:
            logger.warning(f"Failed to publish pipeline event: {e}")
        
        return pipeline_result''',
    1  # Replace only the first occurrence
)

if new_content == content:
    print("Failed to integrate - no changes made")
    exit(1)

# Write back to pipeline.py
with open('engine/agents/pipeline.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Integration complete - publish_event added to pipeline.py")
