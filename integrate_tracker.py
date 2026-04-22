#!/usr/bin/env python3
"""Integrate publish_event into tracker.py open_trade and close_trade methods"""

import re

# Read tracker.py
with open('engine/portfolio/tracker.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Check if publish_event is already integrated
if 'publish_event' in content and 'from events.bus import publish' in content:
    print("publish_event already integrated into tracker.py")
    exit(0)

# Find open_trade method
# Look for "def open_trade(self"
open_trade_match = re.search(
    r'(def open_trade\(self[^:]*:.*?)(?=\n    def |\Z)',
    content,
    re.DOTALL
)

if not open_trade_match:
    print("Could not find open_trade method")
    exit(1)

open_trade_method = open_trade_match.group(1)
print("Found open_trade method")

# Add publish call at the end, before the return
if 'return trade' in open_trade_method:
    new_open_trade = open_trade_method.replace(
        'return trade',
        '''# Publish trade opened event
        try:
            from events.bus import publish as publish_event
            publish_event(
                'trade_opened',
                f'{trade.symbol} {trade.side} {trade.quantity} @ {trade.entry_price}',
                symbol=trade.symbol,
                severity='info'
            )
        except Exception:
            pass
        
        return trade''',
        1
    )
    content = content.replace(open_trade_method, new_open_trade)
    print("Added publish_event call to open_trade")

# Find close_trade method
close_trade_match = re.search(
    r'(def close_trade\(self[^:]*:.*?)(?=\n    def |\Z)',
    content,
    re.DOTALL
)

if not close_trade_match:
    print("Could not find close_trade method")
    exit(1)

close_trade_method = close_trade_match.group(1)
print("Found close_trade method")

# Add publish call at the end, before the return
if 'return trade' in close_trade_method:
    new_close_trade = close_trade_method.replace(
        'return trade',
        '''# Publish trade closed event
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
        
        return trade''',
        1
    )
    content = content.replace(close_trade_method, new_close_trade)
    print("Added publish_event call to close_trade")

# Write back to tracker.py
with open('engine/portfolio/tracker.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Integration complete")
