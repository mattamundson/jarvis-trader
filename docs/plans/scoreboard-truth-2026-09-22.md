# Plan — Scoreboard Truth PR — 2026-09-22

Finish line: focused PR that makes `engine/backtest/gen_scoreboard.py` generate canonical `engine/data/SCOREBOARD.md`, include both modern `gate_v2_metrics` verdicts and legacy `gate_v2.reasons` verdicts, exclude sidecar/non-verdict JSON, and prove current store truth is 6 real verdicts = 1 PASS / 5 FAIL.

Protected-plan note: `.hermes/plan.md` write was blocked by approval timeout; per autonomous-loop artifact discipline, this normal artifact is the active plan and `.hermes/plan.md` will not be retried in this run.

Steps:
1. Add focused tests first for canonical output path, legacy verdict parsing, and sidecar exclusion.
2. Run tests to observe RED.
3. Patch `gen_scoreboard.py` minimally.
4. Run focused tests and compile.
5. Run generator against the isolated worktree verdict store and verify `SCOREBOARD.md` counts/content.
6. Inspect diff scope, commit, push, and open PR.

Safety boundaries: no live trading, risk config, kill switch, broker, `.env`, credential, or symbol-gate changes.
