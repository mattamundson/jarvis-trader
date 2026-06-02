#!/usr/bin/env python3
"""check_gate_v2_integrity.py -- Gate-v2 metric-integrity guard (Initiative 2A).

Read-only STATIC check. No engine import, no numpy -- pure stdlib so it runs
in milliseconds as a pre-commit hook.

WHY THIS EXISTS
---------------
The gate-v2 DSR/Monte-Carlo-DD computation is forked across ~41 strategy
runners. Two distinct code paths exist:

  * TRADE-LEVEL (correct): computes DSR + 95th-percentile drawdown from the
    concatenated per-trade pnl series via ``_gate_v2_trade_metrics``
    (``trade_level_dsr`` + ``trade_level_mc_95th_dd``). Statistically sound.

  * WINDOW-LEVEL (buggy): feeds the *mean of per-window Sharpes* into
    ``deflated_sharpe_ratio(sharpe=...)`` and takes ``np.percentile(oos_dds,
    95)`` over window-level drawdowns. The window-level DSR silently
    auto-PASSES through the infinite-sigma fallback in
    ``deflated_sharpe.py`` when the window-Sharpe series is short/degenerate.

Only the two ENABLED strategies (paper_config: MES, MGC) were migrated to the
trade-level path. The other ~39 runners are dead experiments left on the
window-level path. The hazard: ``gate_v2_policy.is_ungate_eligible`` authorizes
a symbol on *any* non-stale PASS verdict across *all* its rank files -- so a
stray window-level PASS written for an enabled symbol would authorize trading
on the unsound metric.

INVARIANTS
----------
  T1 (FATAL): every paper_config ``enabled=True`` strategy's CANONICAL runner
      uses the trade-level path and contains NO window-level gate pattern.
      Canonical runner is resolved with zero hardcoding:
          enabled symbol
            -> the "Verdict file: .../<BASENAME>.json" comment in its
               paper_config block
            -> the run_*.py whose docstring "Writes: .../<BASENAME>.json"
      A missing comment / no producing runner / ambiguous producer is itself
      a FATAL (the canonical mapping must be explicit and unique).

  T2 (FATAL, pre-commit mode only): any NEWLY-ADDED run_*.py (not present in
      git HEAD) that defines ``_compute_gate_v2`` must use the trade-level
      path. Freezes the bug class for new strategies WITHOUT forcing a rewrite
      of the existing dead-experiment runners (those are not "new").

  WARN (advisory, never fails): window-level runners that write a verdict for
      an ENABLED symbol -- the latent by-symbol authorization risk above.
      Surfaced for a separate archive/remediation decision.

USAGE
-----
    python check_gate_v2_integrity.py            # full audit (T1 + WARN)
    python check_gate_v2_integrity.py FILES...   # pre-commit: also runs T2

Exit 0 = clean, 1 = an invariant was violated.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# --- detection patterns -------------------------------------------------------
# Trade-level path is identified by the actual gate CALLS (importing alone is
# not proof the decision uses them).
_RE_TRADE_DSR = re.compile(r"\btrade_level_dsr\s*\(")
_RE_TRADE_MCDD = re.compile(r"\btrade_level_mc_95th_dd\s*\(")
# Window-level (buggy) signatures, either is sufficient.
_RE_WINDOW_PCTL = re.compile(r"np\.percentile\(\s*oos_dds")
_RE_WINDOW_DSR = re.compile(r"deflated_sharpe_ratio\s*\(\s*sharpe\s*=")
_RE_COMPUTE_GATE = re.compile(r"^\s*def\s+_compute_gate_v2\b", re.MULTILINE)
# Runner docstring declaring its verdict output file.
_RE_WRITES = re.compile(r"Writes:\s*\S*gate_v2_verdicts/([A-Za-z0-9_]+)\.json")
# paper_config block scanning.
_RE_BLOCK_START = re.compile(r"^[A-Z][A-Z0-9_]*\s*=\s*\{\s*$")
_RE_BLOCK_END = re.compile(r"^\}\s*$")
_RE_SYMBOL = re.compile(r'"symbol"\s*:\s*"([A-Za-z0-9]+)"')
_RE_ENABLED_TRUE = re.compile(r'^\s*"enabled"\s*:\s*True\b')
_RE_VERDICT_COMMENT = re.compile(
    r"Verdict file:\s*\S*gate_v2_verdicts/([A-Za-z0-9_]+)\.json"
)


class RunnerInfo:
    """Static classification of a single strategy-runner source file."""

    __slots__ = ("path", "has_compute_gate", "has_trade_calls", "has_window_pattern", "writes")

    def __init__(self, path: Path, text: str) -> None:
        self.path = path
        self.has_compute_gate = bool(_RE_COMPUTE_GATE.search(text))
        self.has_trade_calls = bool(_RE_TRADE_DSR.search(text)) and bool(
            _RE_TRADE_MCDD.search(text)
        )
        self.has_window_pattern = bool(_RE_WINDOW_PCTL.search(text)) or bool(
            _RE_WINDOW_DSR.search(text)
        )
        self.writes = set(_RE_WRITES.findall(text))

    @property
    def is_trade_level(self) -> bool:
        """Trade-level iff it CALLS both ``trade_level_dsr`` and
        ``trade_level_mc_95th_dd``.

        The canonical runners legitimately ALSO compute a window-level
        drawdown for display, kept under a segregated ``*_window_legacy`` name
        and NOT fed to the gate (see run_mes_trend_rank11.py:399). So the
        window pattern may co-exist; presence of the trade-level CALLS is the
        positive signal that the gate decision is trade-level.

        Known limitation: this confirms the trade-level helpers are CALLED,
        not (via dataflow) that their results -- rather than a stray window
        value -- are the ones compared to the thresholds. The codebase
        convention (gate vars ``dsr`` / ``mc_95th_dd`` <- ``trade_level_*``)
        makes call-presence a reliable proxy; a deliberate copy-paste of the
        window value into the gate var is out of scope for a static guard.
        """
        return self.has_trade_calls


def parse_paper_config(text: str) -> dict[str, str | None]:
    """Map each ``enabled=True`` symbol to its canonical verdict basename.

    Returns ``{symbol: basename_or_None}``. ``None`` means the enabled block
    had no parseable ``Verdict file:`` comment (caller treats as FATAL).
    """
    enabled: dict[str, str | None] = {}
    in_block = False
    block: list[str] = []
    for line in text.splitlines():
        if not in_block:
            if _RE_BLOCK_START.match(line):
                in_block, block = True, []
            continue
        if _RE_BLOCK_END.match(line):
            in_block = False
            body = "\n".join(block)
            sym_m = _RE_SYMBOL.search(body)
            is_enabled = any(_RE_ENABLED_TRUE.match(ln) for ln in block)
            if sym_m and is_enabled:
                v_m = _RE_VERDICT_COMMENT.search(body)
                enabled[sym_m.group(1).upper()] = v_m.group(1) if v_m else None
            block = []
            continue
        block.append(line)
    return enabled


def _is_new_file(path: Path, repo_root: Path) -> bool | None:
    """True if ``path`` is absent from git HEAD (newly added), False if present,
    None if newness cannot be determined (no git / error)."""
    try:
        rel = path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return None
    try:
        r = subprocess.run(
            ["git", "-C", str(repo_root), "cat-file", "-e", f"HEAD:{rel}"],
            capture_output=True,
            timeout=10,
        )
        return r.returncode != 0
    except Exception:  # noqa: BLE001 -- git unavailable -> unknown, don't block
        return None


def _repo_root(start: Path) -> Path | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0:
            return Path(r.stdout.strip())
    except Exception:  # noqa: BLE001
        pass
    return None


def audit(backtest_dir: Path) -> tuple[list[str], list[str]]:
    """T1 + WARN over the whole backtest dir. Returns (failures, warnings).

    Pure / git-free so it is deterministically unit-testable.
    """
    failures: list[str] = []
    warnings: list[str] = []

    paper_config = backtest_dir / "paper_config.py"
    if not paper_config.exists():
        return ([f"paper_config.py not found at {paper_config}"], [])
    enabled = parse_paper_config(paper_config.read_text(encoding="utf-8"))
    if not enabled:
        warnings.append("no enabled=True strategies found in paper_config.py")

    # Index every runner: basename -> [RunnerInfo], plus a flat list.
    runners = [
        RunnerInfo(p, p.read_text(encoding="utf-8"))
        for p in sorted(backtest_dir.glob("run_*.py"))
    ]
    by_basename: dict[str, list[RunnerInfo]] = {}
    for r in runners:
        for bn in r.writes:
            by_basename.setdefault(bn, []).append(r)

    canonical_paths: set[Path] = set()

    # T1: each enabled symbol's canonical runner must be trade-level.
    for sym, basename in sorted(enabled.items()):
        if basename is None:
            failures.append(
                f"T1 {sym}: enabled in paper_config but has no 'Verdict file: "
                f".../<name>.json' comment -- canonical runner is undocumented"
            )
            continue
        producers = by_basename.get(basename, [])
        if not producers:
            failures.append(
                f"T1 {sym}: canonical verdict '{basename}.json' is not produced "
                f"by any run_*.py (no matching 'Writes:' docstring)"
            )
            continue
        if len(producers) > 1:
            names = ", ".join(p.path.name for p in producers)
            failures.append(
                f"T1 {sym}: canonical verdict '{basename}.json' is written by "
                f"multiple runners ({names}) -- ambiguous canonical mapping"
            )
            continue
        runner = producers[0]
        canonical_paths.add(runner.path)
        if not runner.is_trade_level:
            failures.append(
                f"T1 {sym}: canonical runner {runner.path.name} does not call "
                f"trade_level_dsr + trade_level_mc_95th_dd -- the enabled strategy "
                f"would be authorized on the unsound window-level metric."
            )

    # WARN: window-level runners that write a verdict for an enabled symbol
    # (and are not the canonical) -- latent by-symbol authorization risk.
    enabled_syms = set(enabled)
    for r in runners:
        if r.path in canonical_paths or not r.has_compute_gate:
            continue
        if r.has_trade_calls or not r.has_window_pattern:
            continue
        hit = sorted(bn for bn in r.writes if bn.split("_", 1)[0].upper() in enabled_syms)
        if hit:
            warnings.append(
                f"{r.path.name}: window-level dead runner writes enabled-symbol "
                f"verdict(s) {hit} -- a stray fresh PASS here would authorize "
                f"trading on the unsound metric (archive or prune verdicts)"
            )

    return failures, warnings


def check_new_files(paths: list[Path], repo_root: Path | None) -> list[str]:
    """T2: newly-added runners that define _compute_gate_v2 must be trade-level."""
    failures: list[str] = []
    for p in paths:
        if not p.name.startswith("run_") or p.suffix != ".py" or not p.exists():
            continue
        info = RunnerInfo(p, p.read_text(encoding="utf-8"))
        if not info.has_compute_gate:
            continue
        new = _is_new_file(p, repo_root) if repo_root else None
        if new and not info.is_trade_level:
            failures.append(
                f"T2 {p.name}: new runner defines _compute_gate_v2 on the "
                f"window-level gate path. New gate computations must use "
                f"trade_level_dsr + trade_level_mc_95th_dd."
            )
    return failures


def main(argv: list[str]) -> int:
    here = Path(__file__).resolve()
    backtest_dir = here.parent.parent / "backtest"  # engine/scripts/.. /backtest
    if not backtest_dir.exists():
        print(f"FAIL: backtest dir not found at {backtest_dir}", file=sys.stderr)
        return 1

    enabled = parse_paper_config((backtest_dir / "paper_config.py").read_text(encoding="utf-8"))
    failures, warnings = audit(backtest_dir)

    # T2 only for explicitly-passed runner files (pre-commit mode).
    file_args = [Path(a) for a in argv if a.endswith(".py")]
    runner_args = [p for p in file_args if p.name.startswith("run_")]
    if runner_args:
        repo_root = _repo_root(backtest_dir)
        failures += check_new_files(runner_args, repo_root)

    for w in warnings:
        print(f"  WARN  {w}")
    if failures:
        print()
        for f in failures:
            print(f"  FAIL  {f}", file=sys.stderr)
        print(
            f"\ngate-v2 integrity check FAILED ({len(failures)} violation(s)).",
            file=sys.stderr,
        )
        return 1
    syms = ", ".join(sorted(enabled)) or "none"
    print(
        f"gate-v2 integrity OK: canonical runner(s) for enabled strateg(ies) "
        f"[{syms}] are on the trade-level path; {len(warnings)} advisory warning(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
