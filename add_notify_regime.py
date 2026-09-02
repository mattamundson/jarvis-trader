#!/usr/bin/env python3
"""Add notify_regime_change function to openclaw_notifier.py"""

# Read the file
with open('engine/notifications/openclaw_notifier.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Check if already added
if 'async def notify_regime_change' in content:
    print("notify_regime_change already exists")
    exit(0)

# Add the new function at the end
new_function = '''

async def notify_regime_change(symbol: str, old_regime: str, new_regime: str) -> bool:
    """Send WhatsApp alert when regime changes. No cooldown (regimes change rarely)."""
    if os.getenv("TESTING"):
        logger.debug("OpenClaw regime change notify suppressed in TESTING mode")
        return False
    ts = _ct_time()
    msg = (
        f"JARVIS Regime Alert\n"
        f"{symbol}: {old_regime} → {new_regime}\n"
        f"Time: {ts} CT"
    )
    return await _send(msg)
'''

content += new_function

# Write back
with open('engine/notifications/openclaw_notifier.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Added notify_regime_change function")
