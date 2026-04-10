#!/usr/bin/env python3
"""Integrate publish_event into tracker.py"""

import re

# Read tracker.py
with open('engine/portfolio/tracker.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Check if publish_event is already integrated
if 'publish_event' in content and 'from events.bus import publish' in content:
    print("publish_event already integrated into tracker.py")
    exit(0)

# Find open_trade method - returns trade_id (string)
# Look for "return trade_id"
if 'return trade_id' in content:
    # Add publish call just before the return
    new_content = content.replace(
        '        return trade_id',
        '''        # Publish trade opened event
        try:
            from events.bus import publish as publish_event
            publish_event(
                'trade_opened',
                f'{symbol.upper()} {action.upper()} {quantity} @ {price}',
                symbol=symbol.upper(),
                severity='info'
            )
        except Exception:
            pass
        
        return trade_id''',
        1  # Replace first occurrence (in open_trade)
    )
    if new_content != content:
        content = new_content
        print("Added publish_event call to open_trade")
    else:
        print("Failed to add to open_trade")

# Find close_trade method - returns PaperTrade object
# Look for "return trade" in close_trade context
# We need to find the close_trade method first

# Find the section after "def close_trade" and add before the return at the end
close_trade_start = content.find('def close_trade(self, trade_id: str, exit_price: float) -> PaperTrade:')
if close_trade_start > 0:
    # Find the next "def " after close_trade to know where the method ends
    next_def = content.find('\n    def ', close_trade_start + 10)
    if next_def > 0:
        close_trade_section = content[close_trade_start:next_def]
        
        # Find the last "return trade" in this section
        last_return_pos = close_trade_section.rfind('return trade')
        if last_return_pos > 0:
            # This is in the close_trade method
            # We need to add the publish call before this return
            actual_pos = close_trade_start + last_return_pos
            
            publish_code = '''# Publish trade closed event
        try:
            from events.bus import publish as publish_event
            severity = 'warn' if trade.pnl and trade.pnl < 0 else 'info'
            publish_event(
                'trade_closed',
                f'{trade.symbol} closed pnl={trade.pnl}',
                symbol=trade.symbol,
                severity=severity
            )
        except Exception:
            pass
        
        '''
            
            content = content[:actual_pos] + publish_code + content[actual_pos:]
            print("Added publish_event call to close_trade")

# Write back to tracker.py
with open('engine/portfolio/tracker.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Integration complete")
