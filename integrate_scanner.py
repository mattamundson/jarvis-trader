#!/usr/bin/env python3
"""Integrate publish_event into scanner_router.py"""

import re

# Read scanner_router.py
with open('engine/routers/scanner_router.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Check if publish_event is already integrated
if 'publish_event' in content and 'from events.bus import publish' in content:
    print("publish_event already integrated into scanner_router.py")
    exit(0)

# Find the record_signal function
if 'def record_signal(' in content:
    # Add publish calls for non-HOLD signals
    # Find the end of the function
    record_signal_start = content.find('def record_signal(')
    next_def = content.find('\ndef ', record_signal_start + 10)
    next_at = content.find('\n@router', record_signal_start + 10)
    
    end_pos = min(p for p in [next_def, next_at, len(content)] if p > 0)
    
    record_signal_section = content[record_signal_start:end_pos]
    
    # Add publish logic before the logger.debug call
    new_record_signal = record_signal_section.replace(
        '    logger.debug(f"[Scanner] Recorded {symbol} {timeframe} signal: {entry_signal}")',
        '''    # Publish signal event if not HOLD
    try:
        from events.bus import publish as publish_event, detect_regime_change
        if entry_signal != "HOLD":
            publish_event(
                'signal_fired',
                f'{symbol} {timeframe} {entry_signal}',
                symbol=symbol,
                severity='info'
            )
        
        # Check for regime change
        if regime:
            old_regime = detect_regime_change(symbol, regime)
            if old_regime and old_regime != regime:
                publish_event(
                    'regime_change',
                    f'{symbol}: {old_regime} → {regime}',
                    symbol=symbol,
                    severity='warn'
                )
                # Notify regime change (asyncio task)
                import asyncio
                try:
                    from notifications.openclaw_notifier import notify_regime_change
                    asyncio.create_task(notify_regime_change(symbol, old_regime, regime))
                except Exception:
                    pass
    except Exception:
        pass
    
    logger.debug(f"[Scanner] Recorded {symbol} {timeframe} signal: {entry_signal}")'''
    )
    
    content = content[:record_signal_start] + new_record_signal + content[end_pos:]
    print("Added publish_event calls to record_signal")

# Write back to scanner_router.py
with open('engine/routers/scanner_router.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Integration complete")
