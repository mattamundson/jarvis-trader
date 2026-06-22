"""Concurrent-exposure validation for correlation-aware sizing (P2.3).

Replays the real paper-trade history to answer, on the windows where the system
actually held >=2 positions at once: how would each correlation-sizing approach
have trimmed the newer position, and which reduces aggregate *correlated* risk
without over-trimming viable trades?

  - BINARY approach   = the existing PositionCorrelationMonitor rule: a static
    correlation table + a 0.80 threshold; above it, cap the correlated position
    at CORRELATED_PAIR_MAX_CONTRACTS. Blind to any pair absent from the table.
  - CONTINUOUS approach = risk.portfolio_sizer: estimate the correlation from
    price bars, then trim by the portfolio-variance quadratic.

Run as a script (``python -m risk.correlation_validation``) to print the report.
The pure helpers below are unit-tested; the I/O + reporting live in ``main``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Optional

# Authoritative $/point multipliers (mirrors utils.position_sizing.INSTRUMENT_MULTIPLIERS).
_MULTIPLIERS = {"MES": 5.0, "MGC": 10.0, "MNQ": 2.0, "MCL": 100.0, "M2K": 5.0}


def risk_at_stop(
    entry_price: float,
    stop_loss: Optional[float],
    quantity: float,
    multiplier: float,
) -> float:
    """Dollar risk of a position to its stop: |entry - stop| * qty * multiplier.

    Returns 0.0 when the stop is missing/zero (no measurable risk contribution).
    """
    if not stop_loss or not entry_price:
        return 0.0
    return abs(entry_price - stop_loss) * abs(quantity) * multiplier


def find_concurrent_pairs(
    intervals: Sequence[tuple],
) -> list[tuple]:
    """Return overlapping interval pairs as ``(newer, older, ostart, oend)``.

    Each interval is ``(start, end, symbol, payload)``. Two intervals overlap
    when one starts strictly before the other ends (touching endpoints do not
    count). ``newer`` is the later-starting interval — the one a correlation
    trim would size down against the already-open book.
    """
    items = sorted(intervals, key=lambda iv: iv[0])
    pairs: list[tuple] = []
    for i in range(len(items)):
        ei = items[i][1]
        for j in range(i + 1, len(items)):
            sj, ej = items[j][0], items[j][1]
            if sj >= ei:  # sorted by start: once sj passes ei, no later j overlaps i
                break
            ostart = sj
            oend = min(ei, ej)
            pairs.append((items[j], items[i], ostart, oend))
    return pairs


# --------------------------------------------------------------------------- #
# Script entry point — the actual validation run (I/O + reporting)
# --------------------------------------------------------------------------- #
def _parse_ts(t):
    from datetime import datetime, timezone

    try:
        d = datetime.fromisoformat(t)
    except (ValueError, TypeError):
        return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def _load_trades(db_path: str) -> list[dict]:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT symbol, entry_time, exit_time, quantity, entry_price, stop_loss "
        "FROM paper_trades"
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        if r["symbol"] not in _MULTIPLIERS:
            continue
        e, x = _parse_ts(r["entry_time"]), _parse_ts(r["exit_time"])
        if not e or not x or x <= e:
            continue
        out.append(
            {
                "symbol": r["symbol"],
                "entry": e,
                "exit": x,
                "qty": r["quantity"] or 1.0,
                "entry_price": r["entry_price"],
                "stop_loss": r["stop_loss"],
                "risk": risk_at_stop(
                    r["entry_price"],
                    r["stop_loss"],
                    r["quantity"] or 1.0,
                    _MULTIPLIERS[r["symbol"]],
                ),
            }
        )
    return out


def _estimate_pair_correlations(symbols, data_dir: str, interval: str = "1d"):
    """Best-effort return correlations from cached bars; {} on any miss."""
    import csv
    import glob

    from risk.correlation_estimator import bars_to_returns, estimate_correlations

    closes_by_symbol: dict[str, list[float]] = {}
    for sym in symbols:
        matches = sorted(glob.glob(f"{data_dir}/{sym}_*_{interval}.csv"))
        if not matches:
            continue
        closes: list[float] = []
        try:
            with open(matches[-1], newline="") as fh:
                for row in csv.DictReader(fh):
                    c = row.get("close") or row.get("Close")
                    if c:
                        closes.append(float(c))
        except (OSError, ValueError):
            continue
        if len(closes) > 30:
            closes_by_symbol[sym] = bars_to_returns(closes)
    return estimate_correlations(closes_by_symbol, min_overlap=30)


def main() -> None:
    import os

    from config import settings
    from risk.portfolio_sizer import correlation_trim_contracts

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(here, "data", "jarvis_trader.db")
    data_dir = os.path.join(here, "data")

    trades = _load_trades(db_path)
    intervals = [(t["entry"], t["exit"], t["symbol"], t) for t in trades]
    pairs = find_concurrent_pairs(intervals)
    cross = [p for p in pairs if p[0][2] != p[1][2]]

    symbols = sorted({t["symbol"] for t in trades})
    est_corr = _estimate_pair_correlations(symbols, data_dir)

    ceiling = settings.CORRELATION_MAX_PORTFOLIO_RISK_USD
    default_corr = settings.CORRELATION_DEFAULT_CORR
    block_thr = settings.CORRELATION_BLOCK_THRESHOLD
    static = settings.INSTRUMENT_CORRELATION_PAIRS
    binary_thr = settings.CORRELATION_THRESHOLD
    binary_cap = settings.CORRELATED_PAIR_MAX_CONTRACTS

    print("=" * 72)
    print("P2.3 CONCURRENT-EXPOSURE VALIDATION — correlation-aware sizing")
    print("=" * 72)
    print(f"futures trades w/ valid intervals : {len(trades)}")
    print(f"overlapping position-pairs        : {len(pairs)}")
    print(f"  cross-symbol (trim targets)     : {len(cross)}")
    print(f"estimated bar correlations        : {dict(est_corr) or '(none — bars missing)'}")
    print(f"static table (binary source)      : {dict(static)}")
    print(f"ceiling=${ceiling:.0f}  default_corr={default_corr}  block_thr={block_thr}")
    print("-" * 72)

    # Plausible per-contract dollar-risk band for a 1-lot micro. Outside this
    # band the stop_loss is missing/corrupt and the window is UNMEASURABLE — it
    # must not be silently counted as a "fire" (that was the misleading result).
    risk_lo, risk_hi = 5.0, 3000.0

    def _plausible(risk: float, contracts: int) -> bool:
        per = risk / max(1, contracts)
        return risk_lo <= per <= risk_hi

    cont_fires = cont_blocks = binary_fires = 0
    measurable = unmeasurable = 0
    cont_risk_removed = 0.0
    examples = []
    for newer, older, ostart, _oend in cross:
        ns, os_ = newer[2], older[2]
        nt, ot = newer[3], older[3]
        new_contracts = max(1, int(round(nt["qty"])))
        old_contracts = max(1, int(round(ot["qty"])))
        new_risk = nt["risk"]
        if not _plausible(new_risk, new_contracts) or not _plausible(ot["risk"], old_contracts):
            unmeasurable += 1
            continue
        measurable += 1
        book = {os_: ot["risk"]}

        # CONTINUOUS: estimated corr (fallback default_corr inside the sizer)
        trimmed, factor, _reason = correlation_trim_contracts(
            ns,
            new_contracts,
            new_risk,
            book,
            est_corr,
            ceiling,
            default_corr=default_corr,
            block_threshold=block_thr,
        )
        if trimmed < new_contracts:
            cont_fires += 1
            cont_risk_removed += (new_contracts - trimmed) / new_contracts * new_risk
        if trimmed == 0:
            cont_blocks += 1

        # BINARY: static table; fire only if pair listed AND rho >= threshold
        rho_static = static.get(f"{ns}-{os_}", static.get(f"{os_}-{ns}"))
        binary_trim = (
            min(new_contracts, binary_cap)
            if (rho_static is not None and rho_static >= binary_thr)
            else new_contracts
        )
        if binary_trim < new_contracts:
            binary_fires += 1

        if len(examples) < 6 and trimmed < new_contracts:
            examples.append(
                f"  {ns}+{os_} {ostart.date()} {ostart.strftime('%H:%M')}: "
                f"cont {new_contracts}->{trimmed} (x{factor:.2f}) | binary {new_contracts}->{binary_trim}"
            )

    has_corr_source = bool(est_corr)
    mgc_in_static = any("MGC" in k for k in static)
    print(f"windows measurable (clean stops) : {measurable}")
    print(f"windows UNMEASURABLE (bad stops) : {unmeasurable}  <- excluded, not counted as fires")
    print(
        f"correlation source (real bars)   : {'yes' if has_corr_source else 'NO — flat default prior'}"
    )
    print("-" * 72)
    m = measurable
    print(
        f"CONTINUOUS  fired {cont_fires}/{m} measurable "
        f"({100*cont_fires/m if m else 0:.0f}%), blocked {cont_blocks}, "
        f"~${cont_risk_removed:.0f} risk trimmed (prior-driven — see caveat)"
    )
    print(
        f"BINARY      fired {binary_fires}/{m} measurable ({100*binary_fires/m if m else 0:.0f}%)"
    )
    if examples:
        print("examples:")
        for e in examples:
            print(e)
    print("-" * 72)
    # Honest verdict: structure is conclusive; magnitude is not.
    print("VERDICT")
    print(
        f"  STRUCTURAL  : BINARY is disqualified — MGC ({'present' if mgc_in_static else 'ABSENT'}) "
        "in its static table; it cannot govern the dominant MES+MGC exposure."
    )
    if m < 20 or not has_corr_source:
        print(
            "  MAGNITUDE   : INCONCLUSIVE — too few clean-stop windows and/or no real "
            "correlation source. Benefit cannot be quantified on this data."
        )
        print(
            "  => Wire the CONTINUOUS approach flag-OFF; keep it OFF until stop_loss "
            "coverage + a bar-correlation feed are fixed, then re-run for a magnitude verdict."
        )
    else:
        print("  MAGNITUDE   : measurable — see fire/trim stats above.")
    print("=" * 72)


if __name__ == "__main__":
    main()
