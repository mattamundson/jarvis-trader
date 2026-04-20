"""Forward-recording experiments that accumulate signal+outcome data over time.

These modules are *observational*, not executional — they never place orders,
never modify live-trading state, and never block on external services. They
write daily rows to dedicated experiment tables so that future backtests can
replay signals that have no historical archive (e.g. TradingView gamma levels).
"""
