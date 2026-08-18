"""Screen → certify pipeline core (S4A).

Shared, testable logic behind ``scripts/screen_and_certify.sh``:

* ``validate_symbol`` — hard-block DO_NOT_TRADE symbols; allowlist symbols the
  iterate.py sweep has a deep cache for.
* ``select_candidates`` — filter iterate.py sweep JSON rows to screen survivors
  (>= min trades, MC p_positive_edge >= min) and return the top-N by edge.
* ``cert_env`` — build the environment for the env-parameterized gate-v2 cert
  runner (``run_equity_sma_cert.py``): candidate params plus symbol-class
  costs (futures get contract multiplier/commission/slippage).
* ``append_journal`` — append a verdict row to ``engine/data/gate_v2_verdicts/
  _journal.csv`` (the tracked verdict journal).

Pure functions where possible so the pipeline is unit-testable without running
backtests. The CLI subcommands ``select`` and ``cert-env`` are the shell
script's interface into this module (TSV lines / KEY=VALUE lines).
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Iterable

from backtest._gate_v2_helpers import classify_wfo_consistency
from backtest.signals import DO_NOT_TRADE_SYMBOLS

#: Symbols iterate.py can screen (its CACHE_PATTERNS keys) minus DO_NOT_TRADE.
#: MGC is excluded via DO_NOT_TRADE_SYMBOLS even though a cache exists.
SCREENABLE_SYMBOLS = frozenset({"MES", "SPY", "QQQ", "AAPL", "TSLA"})

#: Contract-aware costs for futures classes in the cert runner. Equities use
#: the runner defaults (multiplier 1.0, $0 commission, no slippage).
FUTURES_CERT_ENV = {
    "MES": {
        "CERT_MULT": "5.0",
        "CERT_COMMISSION": "0.62",
        "CERT_SLIPPAGE_TICKS": "2.0",
    },
}

#: Default screen filters (mirror iterate.py's shortlist print).
DEFAULT_MIN_TRADES = 10
DEFAULT_MIN_P_EDGE = 0.6

#: _journal.csv schema (tracked file, historical rows since 2026-04).
JOURNAL_COLUMNS = [
    "date",
    "symbol",
    "family",
    "rank",
    "verdict",
    "passed_via",
    "pf_ci_lower",
    "p_edge",
    "mc_dd_pct",
    "dsr",
    "wfo",
    "fixed_min_pf",
    "source_file",
]


def validate_symbol(symbol: str) -> str:
    """Uppercase and validate a symbol for the pipeline.

    Raises ValueError for DO_NOT_TRADE symbols (defense in depth — the shell
    script also guards) and for symbols with no deep cache / grid in the
    harness.
    """
    sym = symbol.upper()
    if sym in DO_NOT_TRADE_SYMBOLS:
        raise ValueError(
            f"{sym} is DO_NOT_TRADE_SYMBOLS — screening/certifying it is forbidden."
        )
    if sym not in SCREENABLE_SYMBOLS:
        raise ValueError(
            f"{sym} is not screenable: no deep cache/grid in iterate.py "
            f"(screenable: {sorted(SCREENABLE_SYMBOLS)})"
        )
    return sym


def select_candidates(
    doc: dict,
    top_n: int = 3,
    min_trades: int = DEFAULT_MIN_TRADES,
    min_p_edge: float = DEFAULT_MIN_P_EDGE,
) -> list[dict]:
    """Return the top-N screen survivors from an iterate.py sweep JSON doc.

    Survivors: rows with an MC p_positive_edge (>= min_p_edge) and enough
    trades (>= min_trades). Sorted by p_positive_edge desc, then profit_factor
    desc. WFO certification is the referee — screening alone never adopts.
    """
    rows: list[dict] = []
    for r in doc.get("rows", []):
        p_edge = r.get("mc_p_positive_edge")
        if p_edge is None or r.get("total_trades", 0) < min_trades:
            continue
        if p_edge < min_p_edge:
            continue
        rows.append(r)
    rows.sort(
        key=lambda r: (
            -(r.get("mc_p_positive_edge") or 0.0),
            -(r.get("profit_factor") or 0.0),
        )
    )
    return rows[: max(0, top_n)]


def cert_env(
    symbol: str,
    fast: int,
    slow: int,
    atr_trail_mult: float,
    *,
    smoke: bool = False,
    cache_override: str | None = None,
    strategy: str = "trend",
) -> dict[str, str]:
    """Build the env for run_equity_sma_cert.py for one candidate.

    strategy='trend' is the only strategy with a cert runner today; anything
    else raises so the pipeline fails loudly instead of silently skipping.
    """
    sym = validate_symbol(symbol)
    if strategy != "trend":
        raise ValueError(
            f"strategy={strategy!r} has no env-parameterized cert runner yet; "
            "only 'trend' (SMA) candidates can be certified by this pipeline."
        )
    env = {
        "CERT_SYMBOL": sym,
        "CERT_FAST": str(int(fast)),
        "CERT_SLOW": str(int(slow)),
        "CERT_ATR": str(float(atr_trail_mult)),
        "CERT_STRATEGY": strategy,
    }
    env.update(FUTURES_CERT_ENV.get(sym, {}))
    if smoke:
        env["CERT_SMOKE"] = "1"
    if cache_override:
        env["CERT_CACHE"] = str(cache_override)
    return env


def _fmt(value: Any) -> str:
    """Journal cell formatting: empty string for None, else str()."""
    return "" if value is None else str(value)


def verdict_journal_row(verdict: dict, source_file: str) -> dict[str, str]:
    """Map a cert verdict dict to one _journal.csv row (all cells strings)."""
    g = verdict.get("gate_v2_metrics") or {}
    win_rate = g.get("win_rate")
    oos_pfs = g.get("oos_pfs")
    if isinstance(oos_pfs, list) and oos_pfs:
        # Real per-window OOS PFs from the cert runner — exact classifier parity.
        wfo = classify_wfo_consistency([float(p) for p in oos_pfs])
    elif win_rate is None:
        wfo = classify_wfo_consistency([])
    else:
        # Fallback for hand-built verdicts: rebuild a synthetic window-PF list
        # whose profitable fraction equals win_rate. Use 1.01 (> 1.0) so the
        # classifier's strict `pf > 1.0` check counts profitable windows.
        n_ok = int(round(float(win_rate) * 10_000))
        wfo = classify_wfo_consistency([1.01] * n_ok + [0.0] * (10_000 - n_ok))
    return {
        "date": _fmt(verdict.get("created_at", ""))[:10],
        "symbol": _fmt(verdict.get("symbol", "")),
        "family": _fmt(verdict.get("family", "sma_cert")),
        "rank": _fmt(verdict.get("rank", "")),
        "verdict": _fmt(verdict.get("verdict", "")),
        "passed_via": _fmt(verdict.get("passed_via")),
        "pf_ci_lower": _fmt(g.get("pf_ci_lower")),
        "p_edge": _fmt(g.get("p_edge")),
        "mc_dd_pct": _fmt(g.get("mc_95th_dd_pct")),
        "dsr": _fmt(g.get("dsr")),
        "wfo": wfo,
        "fixed_min_pf": _fmt(g.get("fixed_min_pf")),
        "source_file": source_file,
    }


def append_journal(verdicts_dir: Path | str, verdict: dict, source_file: str) -> Path:
    """Append one verdict row to ``_journal.csv`` under verdicts_dir.

    Creates the file with a header row on first write. Returns the journal
    path. Idempotent per call — each certification appends exactly one row.
    """
    journal = Path(verdicts_dir) / "_journal.csv"
    row = verdict_journal_row(verdict, source_file)
    write_header = not journal.exists()
    with journal.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=JOURNAL_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)
    return journal


# ---------------------------------------------------------------------------
# CLI (interface for scripts/screen_and_certify.sh)
# ---------------------------------------------------------------------------


def _cmd_select(args: argparse.Namespace) -> int:
    doc = json.loads(Path(args.doc).read_text())
    for r in select_candidates(
        doc, top_n=args.top, min_trades=args.min_trades, min_p_edge=args.min_p_edge
    ):
        vix = ",".join(r["vix_regime_block"]) if r.get("vix_regime_block") else ""
        print(
            "\t".join(
                [
                    str(r["fast"]),
                    str(r["slow"]),
                    str(r["atr_trail_mult"]),
                    f"{r.get('mc_p_positive_edge') or 0:.4f}",
                    f"{r.get('profit_factor') or 0:.4f}",
                    str(r.get("total_trades", 0)),
                    vix,  # last: trailing empty field survives bash `read`
                ]
            )
        )
    return 0


def _cmd_cert_env(args: argparse.Namespace) -> int:
    env = cert_env(
        args.symbol,
        args.fast,
        args.slow,
        args.atr,
        smoke=args.smoke,
        cache_override=args.cache,
        strategy=args.strategy,
    )
    for key, value in env.items():
        print(f"{key}={value}")
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="screen→certify pipeline helpers")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_select = sub.add_parser("select", help="filter sweep JSON -> top-N TSV")
    p_select.add_argument("--doc", required=True, help="iterate.py sweep JSON path")
    p_select.add_argument("--top", type=int, default=3)
    p_select.add_argument("--min-trades", type=int, default=DEFAULT_MIN_TRADES)
    p_select.add_argument("--min-p-edge", type=float, default=DEFAULT_MIN_P_EDGE)
    p_select.set_defaults(func=_cmd_select)

    p_env = sub.add_parser("cert-env", help="print cert runner env as KEY=VALUE")
    p_env.add_argument("--symbol", required=True)
    p_env.add_argument("--fast", type=int, required=True)
    p_env.add_argument("--slow", type=int, required=True)
    p_env.add_argument("--atr", type=float, required=True)
    p_env.add_argument("--strategy", default="trend")
    p_env.add_argument("--smoke", action="store_true")
    p_env.add_argument("--cache", default=None)
    p_env.set_defaults(func=_cmd_cert_env)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
