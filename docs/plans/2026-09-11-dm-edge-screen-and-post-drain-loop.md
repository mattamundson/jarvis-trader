# Plan — DM edge screen + post-drain recommendation loop

Finish line: land a verified research-only Diebold-Mariano edge screen, document first-run findings, verify the MES value-area data prerequisite, audit watchdog state, archive stale top-10 artifacts, and refresh the next ROI queue. No live trading, risk, kill-switch, broker, or `paper_config.py` changes are authorized; any such change requires a `[safety-review]` PR.

## Steps
1. Validate `dm_edge_screen.py` with golden-vector tests.
2. Run the screen against existing gate-v2 verdicts and document statistical conclusions.
3. Find and inspect MES 1h cache availability; verify whether RTH/session tagging can be reconstructed.
4. Confirm control-plane watchdogs are green or write a blocker note.
5. Archive stale stamped top-10 files while preserving recoverable history.
6. Commit scoped research artifacts on the isolated branch and refresh queue/handoff artifacts.
