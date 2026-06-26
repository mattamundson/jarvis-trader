"""Strategy Factory -- hypothesis-driven combinatorial discovery funnel.

A staged funnel (cards -> smoke -> robustness -> combinations) layered on the
existing backtester + gate-v2 machinery, with multiple-testing control
(Deflated Sharpe + PBO) and leakage control (purged k-fold). Compute is pure
Python (tokenless); cognition is reserved for survivors only.

See docs: the approved plan at ~/.claude/plans/declarative-cuddling-naur.md.
"""
