#!/usr/bin/env python3
"""Integrate publish_event into pipeline.py"""

import re

# Read pipeline.py
with open('engine/agents/pipeline.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Check if publish_event is already integrated
if 'publish_event' in content and 'from events.bus import publish' in content:
    print("publish_event already integrated into pipeline.py")
    exit(0)

# Find the run() method
# Look for "async def run(" or similar
run_method_match = re.search(r'(async def run\([^)]*\)[^:]*:.*?)(?=\n    async def |\n    def |\Z)', content, re.DOTALL)
if not run_method_match:
    print("Could not find run() method in pipeline.py")
    exit(1)

run_method = run_method_match.group(1)
print(f"Found run() method, length: {len(run_method)}")

# Find the end of the method where pipeline_result is created
# Look for the pattern where result is returned
# We want to add the publish call before the return

# Look for "return pipeline_result" or similar
if 'return pipeline_result' in run_method:
    # Add the publish call before the return
    new_run_method = run_method.replace(
        'return pipeline_result',
        '''# Publish pipeline result event
        try:
            from events.bus import publish as publish_event
            symbol_val = kwargs.get('symbol')
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
        
        return pipeline_result'''
    )
    content = content.replace(run_method, new_run_method)
    print("Added publish_event call to run() method")
else:
    print("Could not find return statement in run() method")
    exit(1)

# Write back to pipeline.py
with open('engine/agents/pipeline.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Integration complete")
