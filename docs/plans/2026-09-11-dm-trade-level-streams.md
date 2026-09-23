# DM Trade-Level Streams Implementation Plan

> **For Hermes:** Continue implementation directly in the clean scratch branch `feat/dm-trade-level-streams` using strict TDD. Do not touch live engine/risk/kill-switch config.

**Goal:** Add a research-only trade-level Diebold-Mariano mode that compares two `iterate.py --trades-out` sidecar files by aligned realized trade PnL streams, producing the same DM/HLN statistics as verdict-window mode plus explicit alignment metadata.

**Architecture:** Extend `engine/backtest/dm_edge_screen.py` with a second input mode (`--input-mode trades`) that loads trade-sidecar JSON, extracts finite `pnl` values, aligns streams by deterministic row ordinal, and runs the existing `dm_test()` implementation. Preserve current verdict-window behavior as the default. Add golden-vector tests to `engine/backtest/tests_dm_edge_screen.py` so the new loader, alignment, and CLI behavior are independently verifiable and cannot silently bias results.

**Tech Stack:** Python stdlib only (`argparse`, `json`, `math`, `pathlib`, `tempfile`, `subprocess` for tests if needed), existing JARVIS engine venv at `C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/.venv/Scripts/python.exe`, `ruff` CLI for lint.

---

## Why we are accomplishing this

The merged PR #805 added two critical research primitives:

1. A window-level Diebold-Mariano edge screen for comparing gate-v2 verdict windows.
2. An opt-in `iterate.py --trades-out` sidecar export that can preserve per-trade realized PnL.

The next ROI step is to connect those primitives. Window-level PF/Sharpe comparisons are useful but coarse: they compress each OOS window into one value and can hide whether the edge is broad-based or driven by a few windows. Trade-level DM lets us compare realized PnL streams directly, which improves research integrity before any strategy promotion discussion.

This does **not** certify an edge by itself. It adds a research instrument that can later answer: “Does candidate B outperform champion A at the actual trade distribution level, not just at aggregated window metrics?”

## What this will accomplish

When complete, an operator can run:

```bash
python engine/backtest/dm_edge_screen.py candidate_a_trades.json candidate_b_trades.json --input-mode trades --power 1
```

and receive JSON like:

```json
{
  "input_mode": "trades",
  "metric": "trade_pnl",
  "n_a": 20,
  "n_b": 18,
  "aligned_n": 18,
  "dropped_a_tail": 2,
  "dropped_b_tail": 0,
  "alignment": "ordinal_prefix_min_length",
  "n": 18,
  "dm_hln": 2.1,
  "p_two_sided": 0.05
}
```

This makes alignment loss explicit instead of silently truncating streams.

## Non-negotiable constraints

- Research/backtest only.
- No live engine behavior changes.
- No risk config changes.
- No kill-switch changes.
- No broker or paper order path changes.
- No symbol authorization/gate changes.
- MCL and MNQ remain DO_NOT_TRADE_SYMBOLS; do not run operational commands involving them.
- `master` remains PR-only.
- Verify before claiming success.

---

## Task 0: Reset partial production patch and confirm clean TDD baseline

**Objective:** Remove the previously-started implementation patch so the new feature can be developed test-first.

**Files:**
- Modify/reset: `engine/backtest/dm_edge_screen.py`
- Keep: `docs/plans/2026-09-11-dm-trade-level-streams.md`

**Step 1: Revert only the production file**

Run:

```bash
git checkout -- engine/backtest/dm_edge_screen.py
```

**Step 2: Confirm status**

Run:

```bash
git status --short
```

Expected: only the plan file is untracked/modified before tests are added.

---

## Task 1: Add failing tests for trade sidecar loader

**Objective:** Define loader behavior before implementation.

**Files:**
- Modify: `engine/backtest/tests_dm_edge_screen.py`

**Step 1: Add tests**

Add imports:

```python
import json
import tempfile
```

Add helper:

```python
def write_json(payload) -> str:
    fh = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, fh)
    fh.close()
    return fh.name
```

Add tests:

```python
def test_load_trade_pnl_series_wrapped_schema() -> None:
    path = write_json({"trades": [{"pnl": 10.5}, {"pnl": -2.0}, {"pnl": 0}]})
    vals = load_trade_pnl_series(path)
    assert vals == [10.5, -2.0, 0.0]
    print("PASS wrapped trade sidecar pnl extraction")


def test_load_trade_pnl_series_raw_list_schema() -> None:
    path = write_json([{"pnl": 1}, {"pnl": 2.25}])
    vals = load_trade_pnl_series(path)
    assert vals == [1.0, 2.25]
    print("PASS raw-list trade sidecar pnl extraction")


def test_load_trade_pnl_series_rejects_missing_pnl() -> None:
    path = write_json({"trades": [{"pnl": 1}, {"not_pnl": 2}]})
    try:
        load_trade_pnl_series(path)
    except ValueError as e:
        assert "missing pnl" in str(e)
    else:
        raise AssertionError("expected missing pnl ValueError")
    print("PASS missing pnl rejected")
```

Update import line:

```python
from dm_edge_screen import _t_sf_two_sided, dm_test, load_trade_pnl_series
```

**Step 2: Run test and verify RED**

Run:

```bash
C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/.venv/Scripts/python.exe engine/backtest/tests_dm_edge_screen.py
```

Expected: FAIL with `ImportError` or `NameError` for `load_trade_pnl_series`.

---

## Task 2: Implement minimal trade sidecar loader

**Objective:** Make Task 1 tests pass with the smallest robust implementation.

**Files:**
- Modify: `engine/backtest/dm_edge_screen.py`

**Implementation:**

Add after `align()`:

```python
def load_trade_pnl_series(path: str) -> list[float]:
    """Extract realized trade PnL from an iterate.py --trades-out sidecar."""
    d = json.loads(Path(path).read_text())
    rows = d.get("trades") if isinstance(d, dict) else d
    if not isinstance(rows, list):
        raise ValueError(f"{path}: expected a trades list or object with trades[]")
    values: list[float] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or "pnl" not in row:
            raise ValueError(f"{path}: trade row {i} missing pnl")
        value = float(row["pnl"])
        if not math.isfinite(value):
            raise ValueError(f"{path}: trade row {i} has non-finite pnl")
        values.append(value)
    return values
```

**Verification:**

Run same test file. Expected: existing golden tests + 3 new tests pass.

---

## Task 3: Add failing tests for ordinal alignment metadata

**Objective:** Make alignment truncation explicit and tested.

**Files:**
- Modify: `engine/backtest/tests_dm_edge_screen.py`

**Tests:**

Import `align_by_ordinal`.

```python
def test_align_by_ordinal_reports_dropped_tails() -> None:
    a, b, meta = align_by_ordinal([10, 20, 30], [1, 2])
    assert a == [10, 20]
    assert b == [1, 2]
    assert meta == {
        "n_a": 3,
        "n_b": 2,
        "aligned_n": 2,
        "dropped_a_tail": 1,
        "dropped_b_tail": 0,
        "alignment": "ordinal_prefix_min_length",
    }
    print("PASS ordinal alignment reports dropped tails")
```

**RED command:** same test file. Expected: `ImportError` / `NameError` for `align_by_ordinal`.

---

## Task 4: Implement ordinal alignment helper

**Objective:** Make Task 3 pass.

**Files:**
- Modify: `engine/backtest/dm_edge_screen.py`

**Implementation:**

```python
def align_by_ordinal(a_vals: list[float], b_vals: list[float]) -> tuple[list[float], list[float], dict]:
    """Align trade-level streams by deterministic row ordinal."""
    n = min(len(a_vals), len(b_vals))
    return a_vals[:n], b_vals[:n], {
        "n_a": len(a_vals),
        "n_b": len(b_vals),
        "aligned_n": n,
        "dropped_a_tail": max(0, len(a_vals) - n),
        "dropped_b_tail": max(0, len(b_vals) - n),
        "alignment": "ordinal_prefix_min_length",
    }
```

**Verification:** same test file. Expected: all tests pass.

---

## Task 5: Add failing CLI trade-mode test

**Objective:** Prove the command-line path emits correct trade-mode metadata and DM result shape.

**Files:**
- Modify: `engine/backtest/tests_dm_edge_screen.py`

**Implementation idea:** Prefer direct function-level test if keeping script simple; otherwise use `subprocess` with `sys.executable`.

Add import:

```python
import subprocess
```

Test:

```python
def test_cli_trade_mode_outputs_alignment_metadata() -> None:
    a_path = write_json({"trades": [{"pnl": 10}, {"pnl": -5}, {"pnl": 7}, {"pnl": 4}]})
    b_path = write_json({"trades": [{"pnl": 1}, {"pnl": -1}, {"pnl": 2}]})
    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("dm_edge_screen.py")),
            a_path,
            b_path,
            "--input-mode",
            "trades",
            "--power",
            "1",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    out = json.loads(proc.stdout)
    assert out["input_mode"] == "trades"
    assert out["metric"] == "trade_pnl"
    assert out["n_a"] == 4
    assert out["n_b"] == 3
    assert out["aligned_n"] == 3
    assert out["dropped_a_tail"] == 1
    assert out["dropped_b_tail"] == 0
    assert out["n"] == 3
    print("PASS trade-mode CLI emits alignment metadata")
```

**RED command:** same test file. Expected: CLI rejects `--input-mode` before implementation.

---

## Task 6: Implement CLI trade mode without changing verdict mode

**Objective:** Add `--input-mode trades` and preserve current default behavior.

**Files:**
- Modify: `engine/backtest/dm_edge_screen.py`

**Implementation:**

Change positional args to neutral names:

```python
ap.add_argument("input_a")
ap.add_argument("input_b")
ap.add_argument("--input-mode", choices=["verdict", "trades"], default="verdict")
```

Branch after args parse:

```python
if args.input_mode == "trades":
    a_vals = load_trade_pnl_series(args.input_a)
    b_vals = load_trade_pnl_series(args.input_b)
    a, b, alignment = align_by_ordinal(a_vals, b_vals)
    res = dm_test(a, b, power=args.power)
    out = {
        "a": Path(args.input_a).name,
        "b": Path(args.input_b).name,
        "input_mode": "trades",
        "metric": "trade_pnl",
        **alignment,
        **res,
    }
else:
    ap_periods, ap_vals = load_oos_series(args.input_a, args.metric)
    bp_periods, bp_vals = load_oos_series(args.input_b, args.metric)
    a, b = align(ap_periods, ap_vals, bp_periods, bp_vals)
    res = dm_test(a, b, power=args.power)
    out = {
        "a": Path(args.input_a).name,
        "b": Path(args.input_b).name,
        "input_mode": "verdict",
        "metric": f"oos_{args.metric}",
        **res,
    }
```

Keep one-sided logic unchanged after `out` is constructed.

**Verification:** same test file. Expected: all tests pass.

---

## Task 7: Full verification battery

**Objective:** Prove code, tests, and lint are clean.

Commands:

```bash
C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/.venv/Scripts/python.exe -m py_compile engine/backtest/dm_edge_screen.py engine/backtest/tests_dm_edge_screen.py
C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/.venv/Scripts/python.exe engine/backtest/tests_dm_edge_screen.py
ruff check engine/backtest/dm_edge_screen.py engine/backtest/tests_dm_edge_screen.py
```

Expected:

- compile: exit 0
- tests: all golden + loader/alignment/CLI tests pass
- ruff: `All checks passed!`

---

## Task 8: Real sidecar smoke

**Objective:** Prove trade-mode works on generated iterate sidecars.

Generate two smoke sidecars with different params if practical, then run:

```bash
python engine/backtest/dm_edge_screen.py <sidecar_a.json> <sidecar_b.json> --input-mode trades --power 1
```

Acceptance:

- JSON output has `input_mode=trades`.
- `metric=trade_pnl`.
- `aligned_n >= 3` for a statistically meaningful smoke; if less than 3, output must explicitly report insufficient aligned trades.
- Dropped-tail metadata is present.

---

## Task 9: Commit and PR

**Objective:** Ship as a small research-only PR.

Commands:

```bash
git status --short
git add docs/plans/2026-09-11-dm-trade-level-streams.md engine/backtest/dm_edge_screen.py engine/backtest/tests_dm_edge_screen.py
git commit -m "research: add trade-level DM stream mode"
git push -u github feat/dm-trade-level-streams
gh pr create --repo mattamundson/jarvis-trader --base master --head feat/dm-trade-level-streams --title "Research: add trade-level DM stream mode" --body-file <body-file>
```

PR body must include:

- Research-only safety statement.
- No live engine/risk/kill-switch/broker/symbol changes.
- Verification commands and exact outputs.
- Limitations: ordinal alignment is a research approximation, not execution-level trade matching.

---

## Final acceptance criteria

- Plan saved.
- Tests were written and observed failing before production implementation.
- `dm_edge_screen.py` supports verdict mode and trade mode.
- Trade mode handles wrapped sidecar schema and raw list fixture schema.
- Missing/non-finite PnL fails loudly.
- Alignment metadata is explicit.
- Full verification battery passes.
- PR opened or, if blocked, branch/commit state documented in handoff.
