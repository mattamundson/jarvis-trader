"""
JARVIS TRADER — Discord Signal Correlation Study
=================================================
Correlates 215K+ Discord bot signals with each other and with derived
JARVIS-style bias (win-rate confidence tiers) to find alignment patterns
that predict better outcomes.

Since JARVIS's 5-layer engine requires live OHLCV price bars that are not
stored alongside the Discord signals, this study derives a "JARVIS bias proxy"
from the signal data itself:
  - win_rate >= 80  → HIGH_CONFIDENCE (analogous to JARVIS STRONG_BULL)
  - win_rate 70-80  → MED_CONFIDENCE  (analogous to LEAN_BULL)
  - win_rate 60-70  → LOW_CONFIDENCE  (borderline / NEUTRAL)
  - win_rate < 60   → WEAK            (below JARVIS threshold)

Cross-market alignment uses NQ direction as a market-direction proxy
(most liquid, highest signal count). When a signal's direction agrees with
the concurrent NQ signal in the same hour bucket, it is marked as
MARKET_ALIGNED; otherwise MARKET_DIVERGE.

Run as:
    cd engine && python -m analysis.discord_correlation

Saves:   data/discord_correlation_study.csv
Prints:  summary table to stdout
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

# ── Path resolution ──────────────────────────────────────────────────────────


def _find_db() -> Path:
    """
    Walk up from this file to find a jarvis_trader.db that contains the
    discord_bot_signals table.  Mirrors the pattern in discord_time_patterns.py
    so the script is relocatable regardless of cwd.
    """
    here = Path(__file__).resolve()
    candidates = []
    for parent in here.parents:
        candidate = parent / "data" / "jarvis_trader.db"
        if candidate.exists():
            candidates.append(candidate)

    for candidate in candidates:
        try:
            conn = sqlite3.connect(str(candidate))
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='discord_bot_signals'"
            ).fetchone()
            conn.close()
            if row:
                return candidate
        except sqlite3.Error:
            continue

    raise FileNotFoundError(
        "Cannot find a jarvis_trader.db that contains the discord_bot_signals table. "
        f"Searched: {[str(c) for c in candidates]}"
    )


_OUTPUT_FILENAME = "discord_correlation_study.csv"

# Lazy DB resolution: don't touch the filesystem at import time, so this module
# (and the test conftest chain that transitively imports it) loads even when no
# jarvis_trader.db exists yet — e.g. CI or a fresh checkout. Resolved on first
# use and cached. Eager resolution here previously broke pytest collection with a
# FileNotFoundError raised from _find_db() at import.
_DB_PATH_CACHE: Optional[Path] = None


def _db_path() -> Path:
    global _DB_PATH_CACHE
    if _DB_PATH_CACHE is None:
        _DB_PATH_CACHE = _find_db()
    return _DB_PATH_CACHE


def _default_output() -> Path:
    return _db_path().parent / _OUTPUT_FILENAME

# ── Confidence thresholds (calibrated to this dataset's win-rate scale) ──────
CONF_HIGH_THRESHOLD = 80.0  # win_rate >= 80 → HIGH_CONFIDENCE
CONF_MED_THRESHOLD = 70.0  # win_rate 70-80 → MED_CONFIDENCE
CONF_LOW_THRESHOLD = 60.0  # win_rate 60-70 → LOW_CONFIDENCE
# win_rate <  60 → WEAK

# Market proxy symbol — used to derive "market direction" for alignment calc
MARKET_PROXY_SYMBOL = "NQ"

# Minimum signals per category to include in the final report
MIN_SIGNALS_FOR_REPORT = 10

# Conviction bucket split points for analyze_conviction_threshold().
# Calibrate after 30+ days of data:
#   SELECT MIN(conviction), AVG(conviction), MAX(conviction),
#          COUNT(*) FILTER (WHERE conviction < 0.3) AS low_n,
#          COUNT(*) FILTER (WHERE conviction BETWEEN 0.3 AND 0.6) AS med_n,
#          COUNT(*) FILTER (WHERE conviction > 0.6) AS high_n
#   FROM corey_session_bias WHERE data_quality IN ('fresh','stale');
# If high_n < 20, lower CONVICTION_BUCKET_HIGH (try 0.5 or 0.4).
CONVICTION_BUCKET_LOW: float = 0.3   # 0.0 – this value → "low"
CONVICTION_BUCKET_HIGH: float = 0.6  # this value – 1.0 → "high"

# Minimum per-category sample size for API responses (analysis functions).
# 5 signals yields a ±40pp confidence interval — statistically meaningless.
# 30 narrows to ±18pp; 100+ is required for real inference (see R5 p-values).
MIN_SIGNALS_ANALYSIS = 30


# ── Confidence tier helpers ───────────────────────────────────────────────────


def _confidence_tier(win_rate: float) -> str:
    """Map a win_rate (0–100 scale) to a confidence tier label."""
    if win_rate >= CONF_HIGH_THRESHOLD:
        return "HIGH_CONFIDENCE"
    elif win_rate >= CONF_MED_THRESHOLD:
        return "MED_CONFIDENCE"
    elif win_rate >= CONF_LOW_THRESHOLD:
        return "LOW_CONFIDENCE"
    return "WEAK"


def _jarvis_bias_from_confidence(win_rate: float) -> str:
    """
    Derive a JARVIS-style bias label from win_rate confidence.
    Mimics the output of layer3_bias() using available data.
      HIGH_CONFIDENCE → STRONG_BULL  (proxy for JARVIS STRONG_BULL/LEAN_BULL)
      MED_CONFIDENCE  → LEAN_BULL
      LOW_CONFIDENCE  → NEUTRAL
      WEAK            → NEUTRAL
    All signals in this dataset have direction=LONG, so we never produce
    BEAR labels — the Discord bot only fires long entries.
    """
    tier = _confidence_tier(win_rate)
    if tier == "HIGH_CONFIDENCE":
        return "STRONG_BULL"
    elif tier == "MED_CONFIDENCE":
        return "LEAN_BULL"
    return "NEUTRAL"


# ── Database query helpers ────────────────────────────────────────────────────


def _fetch_signals(
    conn: sqlite3.Connection,
    symbols: Optional[List[str]] = None,
    date_range: Optional[Tuple[str, str]] = None,
    limit: int = 0,
) -> pd.DataFrame:
    """
    Load ENTRY signals with complete win_rate / gain data from the DB.
    Returns a DataFrame with standardised columns.
    """
    where_clauses = [
        "signal_type = 'ENTRY'",
        "win_rate IS NOT NULL",
        "gain IS NOT NULL",
        "direction IS NOT NULL",
    ]
    params: list = []

    if symbols:
        placeholders = ",".join("?" * len(symbols))
        where_clauses.append(f"symbol IN ({placeholders})")
        params.extend(symbols)

    if date_range:
        where_clauses.append("timestamp >= ?")
        params.append(date_range[0])
        where_clauses.append("timestamp <= ?")
        params.append(date_range[1])

    where_sql = " AND ".join(where_clauses)
    limit_sql = f" LIMIT {limit}" if limit > 0 else ""

    query = f"""
        SELECT
            id,
            message_id,
            timestamp,
            symbol,
            direction,
            win_rate,
            wins,
            losses,
            gain,
            draw,
            net,
            rr,
            mfe,
            mae,
            entry_price,
            last_price,
            source_channel
        FROM discord_bot_signals
        WHERE {where_sql}
        ORDER BY timestamp ASC
        {limit_sql}
    """

    df = pd.read_sql_query(query, conn, params=params)
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="ISO8601", utc=True)

    # Derived columns
    df["hour_bucket"] = df["timestamp"].dt.floor("h")
    df["hour_of_day"] = df["timestamp"].dt.hour
    df["day_of_week"] = df["timestamp"].dt.day_of_week  # 0=Mon … 6=Sun
    # Convert to UTC-naive before period conversion to avoid tz-drop warning
    df["year_month"] = df["timestamp"].dt.tz_localize(None).dt.to_period("M").astype(str)

    df["win_rate_norm"] = df["win_rate"] / 100.0  # 0.0–1.0 scale
    df["confidence_tier"] = df["win_rate"].apply(_confidence_tier)
    df["jarvis_bias"] = df["win_rate"].apply(_jarvis_bias_from_confidence)

    return df


def _build_nq_hourly_direction(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    Build an NQ hourly direction map.
    For each UTC hour bucket: returns the most common direction and average win_rate.
    Used as the "market direction" proxy for cross-market alignment.
    """
    query = """
        SELECT
            strftime('%Y-%m-%dT%H', datetime(timestamp)) || ':00+00:00' as hour_bucket_str,
            direction,
            AVG(win_rate) as avg_win_rate,
            COUNT(*) as cnt
        FROM discord_bot_signals
        WHERE symbol = 'NQ'
          AND signal_type = 'ENTRY'
          AND win_rate IS NOT NULL
          AND direction IS NOT NULL
        GROUP BY hour_bucket_str, direction
        ORDER BY hour_bucket_str, cnt DESC
    """
    raw = pd.read_sql_query(query, conn)
    if raw.empty:
        return pd.DataFrame(columns=["hour_bucket", "market_direction", "market_avg_wr"])

    # Keep only the dominant direction per hour bucket
    raw["hour_bucket"] = pd.to_datetime(raw["hour_bucket_str"], utc=True)
    dominant = raw.sort_values("cnt", ascending=False).groupby("hour_bucket").first().reset_index()
    dominant = dominant.rename(
        columns={
            "direction": "market_direction",
            "avg_win_rate": "market_avg_wr",
        }
    )
    return dominant[["hour_bucket", "market_direction", "market_avg_wr"]]


# ── Core analysis functions ───────────────────────────────────────────────────


def analyze_signal_alignment(
    symbol: str,
    date_range: Optional[Tuple[str, str]] = None,
    limit: int = 10000,
) -> pd.DataFrame:
    """
    For each Discord ENTRY signal for *symbol*, compute:
      - What JARVIS's 5-layer system would output (proxied from win_rate confidence)
      - Whether the signal agrees with the concurrent NQ market direction
      - Alignment category:
          BOTH_HIGH_CONF    — jarvis_bias=STRONG_BULL + HIGH_CONFIDENCE signal
          MED_CONF          — jarvis_bias=LEAN_BULL   + MED_CONFIDENCE signal
          LOW_CONF_OR_WEAK  — NEUTRAL bias, low/weak confidence
          MARKET_ALIGNED    — signal direction agrees with NQ direction that hour
          MARKET_DIVERGE    — signal direction disagrees with NQ direction

    Returns DataFrame with per-signal rows and enriched columns.
    """
    with sqlite3.connect(_db_path()) as conn:
        df = _fetch_signals(conn, symbols=[symbol], date_range=date_range, limit=limit)
        nq_map = _build_nq_hourly_direction(conn)

    if df.empty:
        return pd.DataFrame()

    # Merge NQ market direction by hour bucket
    df = df.merge(nq_map, on="hour_bucket", how="left")

    # Market alignment category
    def _market_align(row) -> str:
        if pd.isna(row.get("market_direction")):
            return "NO_MARKET_DATA"
        if symbol == MARKET_PROXY_SYMBOL:
            # NQ vs itself — always aligned
            return "SELF_IS_MARKET"
        if row["direction"] == row["market_direction"]:
            return "MARKET_ALIGNED"
        return "MARKET_DIVERGE"

    df["market_alignment"] = df.apply(_market_align, axis=1)

    # Alignment category (primary) based on confidence tier
    def _category(row) -> str:
        tier = row["confidence_tier"]
        if tier == "HIGH_CONFIDENCE":
            return "BOTH_HIGH_CONF"
        elif tier == "MED_CONFIDENCE":
            return "MED_CONF"
        elif tier == "LOW_CONFIDENCE":
            return "LOW_CONF"
        return "WEAK"

    df["category"] = df.apply(_category, axis=1)

    # Composite category including market alignment
    def _full_category(row) -> str:
        base = row["category"]
        align = row["market_alignment"]
        if align in ("MARKET_ALIGNED", "SELF_IS_MARKET"):
            return f"{base}+ALIGNED"
        elif align == "MARKET_DIVERGE":
            return f"{base}+DIVERGE"
        return base  # NO_MARKET_DATA

    df["full_category"] = df.apply(_full_category, axis=1)

    return df


def compute_statistics(df: pd.DataFrame) -> Dict:
    """
    Compute win rate and average gain by alignment category.
    Input *df* is the output of analyze_signal_alignment().

    Returns a dict keyed by category with stats:
      signal_count, avg_win_rate, avg_gain, avg_draw, avg_net, avg_rr,
      pct_of_total
    """
    if df.empty:
        return {}

    stats: Dict = {}
    total = len(df)

    for cat, group in df.groupby("full_category"):
        cnt = len(group)
        stats[cat] = {
            "signal_count": cnt,
            "pct_of_total": round(cnt / total * 100, 1),
            "avg_win_rate": round(group["win_rate_norm"].mean(), 4),
            "avg_gain": round(group["gain"].mean(), 4),
            "avg_draw": round(group["draw"].mean(), 4),
            "avg_net": round(
                group["net"].mean()
                if "net" in group.columns and group["net"].notna().any()
                else float("nan"),
                4,
            ),
            "avg_rr": round(
                group["rr"].mean()
                if "rr" in group.columns and group["rr"].notna().any()
                else float("nan"),
                4,
            ),
            "best_hour": int(group.groupby("hour_of_day")["win_rate_norm"].mean().idxmax()),
            "worst_hour": int(group.groupby("hour_of_day")["win_rate_norm"].mean().idxmin()),
        }

    return stats


def _compute_hour_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Return win_rate × gain stats grouped by (symbol, hour_of_day)."""
    grouped = (
        df.groupby(["symbol", "hour_of_day"])
        .agg(
            signal_count=("id", "count"),
            avg_win_rate=("win_rate_norm", "mean"),
            avg_gain=("gain", "mean"),
            avg_draw=("draw", "mean"),
        )
        .reset_index()
    )
    grouped["avg_win_rate"] = grouped["avg_win_rate"].round(4)
    grouped["avg_gain"] = grouped["avg_gain"].round(4)
    grouped["avg_draw"] = grouped["avg_draw"].round(4)
    return grouped


def _compute_streak_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    Streak analysis: when 3+ consecutive same-direction signals appear for a
    symbol within a rolling 3-hour window, what is the average win_rate / gain
    of the streak vs non-streak signals?
    """
    records = []
    for symbol, sym_df in df.groupby("symbol"):
        sym_df = sym_df.sort_values("timestamp").copy()
        sym_df["is_streak"] = False

        # Mark rows where the previous 2 signals (same symbol) were same direction
        dirs = sym_df["direction"].tolist()
        for i in range(2, len(dirs)):
            if dirs[i] == dirs[i - 1] == dirs[i - 2]:
                sym_df.iloc[i, sym_df.columns.get_loc("is_streak")] = True

        streak = sym_df[sym_df["is_streak"]]
        no_streak = sym_df[~sym_df["is_streak"]]

        records.append(
            {
                "symbol": symbol,
                "group": "streak_3plus",
                "signal_count": len(streak),
                "avg_win_rate": round(streak["win_rate_norm"].mean(), 4)
                if not streak.empty
                else float("nan"),
                "avg_gain": round(streak["gain"].mean(), 4) if not streak.empty else float("nan"),
                "avg_draw": round(streak["draw"].mean(), 4) if not streak.empty else float("nan"),
            }
        )
        records.append(
            {
                "symbol": symbol,
                "group": "non_streak",
                "signal_count": len(no_streak),
                "avg_win_rate": round(no_streak["win_rate_norm"].mean(), 4)
                if not no_streak.empty
                else float("nan"),
                "avg_gain": round(no_streak["gain"].mean(), 4)
                if not no_streak.empty
                else float("nan"),
                "avg_draw": round(no_streak["draw"].mean(), 4)
                if not no_streak.empty
                else float("nan"),
            }
        )

    return pd.DataFrame(records)


def _compute_cross_market_alignment(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    For each non-NQ symbol, compute win_rate stats when:
      (a) Signal hour bucket has an NQ signal  (market_aligned vs diverge)
      (b) NQ win_rate is HIGH (>=80) vs MED/LOW
    """
    all_df = _fetch_signals(conn)
    nq_map = _build_nq_hourly_direction(conn)

    results = []
    for symbol in all_df["symbol"].unique():
        if symbol == MARKET_PROXY_SYMBOL:
            continue
        sym_df = all_df[all_df["symbol"] == symbol].copy()
        sym_df = sym_df.merge(nq_map, on="hour_bucket", how="left")

        has_nq = sym_df[sym_df["market_direction"].notna()]
        no_data = sym_df[sym_df["market_direction"].isna()]
        aligned = has_nq[has_nq["direction"] == has_nq["market_direction"]]
        diverge = has_nq[has_nq["direction"] != has_nq["market_direction"]]

        for group_label, group_df in [
            ("aligned_with_NQ", aligned),
            ("diverges_from_NQ", diverge),
            ("no_NQ_signal", no_data),
        ]:
            if len(group_df) < MIN_SIGNALS_FOR_REPORT:
                continue
            results.append(
                {
                    "symbol": symbol,
                    "alignment_group": group_label,
                    "signal_count": len(group_df),
                    "avg_win_rate": round(group_df["win_rate_norm"].mean(), 4),
                    "avg_gain": round(group_df["gain"].mean(), 4),
                    "avg_draw": round(group_df["draw"].mean(), 4),
                }
            )

    return pd.DataFrame(results)


# ── Corey session-bias correlation (Phase 3) ────────────────────────────────
# These functions join discord_bot_signals with corey_session_bias on date —
# quantifying whether Corey's LLM-extracted directional bias compounds with
# bot signal win rate. Require the commentary processor to have run at least
# once (corey_session_bias table populated). All accept db_path for FastAPI
# compatibility; default falls back to _db_path() resolved lazily on first use.


def _is_aligned(corey_bias: str, signal_direction: str) -> Optional[bool]:
    """True=aligned, False=opposed, None=indeterminate (neutral Corey or unknown direction)."""
    cb = (corey_bias or "").lower()
    sd = (signal_direction or "").upper()
    if cb == "neutral" or not cb or not sd:
        return None
    bullish = cb in ("bullish", "long", "buy")
    bearish = cb in ("bearish", "short", "sell")
    long_sig = sd in ("LONG", "BUY")
    short_sig = sd in ("SHORT", "SELL")
    if bullish and long_sig:
        return True
    if bearish and short_sig:
        return True
    if bullish and short_sig:
        return False
    if bearish and long_sig:
        return False
    return None


def analyze_corey_alignment_win_rate(
    symbol: str,
    lookback_days: int = 90,
    db_path: Optional[str] = None,
    min_signals: int = MIN_SIGNALS_ANALYSIS,
) -> List[dict]:
    """
    Join discord_bot_signals with corey_session_bias to quantify whether
    Corey's directional bias compounds with bot signal win rate.

    Returns list of dicts sorted by signal_count desc:
        corey_bias, signal_direction, aligned (True/False/None),
        signal_count, avg_win_rate (0.0–1.0), avg_rr
    """
    if db_path is None:
        db_path = str(_db_path())
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%dT%H:%M:%S")
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT cs.directional_bias AS corey_bias,
                   bs.direction         AS signal_direction,
                   bs.win_rate,
                   bs.rr
            FROM discord_bot_signals bs
            JOIN corey_session_bias cs ON DATE(bs.timestamp) = cs.date
            WHERE bs.symbol = ?
              AND bs.timestamp >= ?
              AND bs.signal_type = 'ENTRY'
              AND bs.win_rate IS NOT NULL
              AND cs.data_quality IN ('fresh', 'stale')
            """,
            (symbol.upper(), cutoff),
        ).fetchall()

    if not rows:
        return []

    groups: Dict[tuple, Dict] = {}
    for row in rows:
        key = (row["corey_bias"] or "unknown", row["signal_direction"] or "unknown")
        if key not in groups:
            groups[key] = {"win_rates": [], "rrs": []}
        groups[key]["win_rates"].append((row["win_rate"] or 0.0) / 100.0)
        if row["rr"] is not None:
            groups[key]["rrs"].append(row["rr"])

    results = []
    for (corey_bias, signal_direction), data in groups.items():
        n = len(data["win_rates"])
        if n < min_signals:
            continue
        results.append({
            "corey_bias": corey_bias,
            "signal_direction": signal_direction,
            "aligned": _is_aligned(corey_bias, signal_direction),
            "signal_count": n,
            "avg_win_rate": round(sum(data["win_rates"]) / n, 4),
            "avg_rr": round(sum(data["rrs"]) / len(data["rrs"]), 4) if data["rrs"] else None,
        })

    return sorted(results, key=lambda x: x["signal_count"], reverse=True)


def analyze_session_type_performance(
    symbol: str,
    lookback_days: int = 90,
    db_path: Optional[str] = None,
    min_signals: int = MIN_SIGNALS_ANALYSIS,
) -> List[dict]:
    """
    Win rate by Corey's session_type (range_day, trend_day, outside_bar, etc.).
    Helps route signals differently on trend vs. range days.

    Returns list of dicts: session_type, signal_count, avg_win_rate, avg_rr, avg_gain
    """
    if db_path is None:
        db_path = str(_db_path())
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%dT%H:%M:%S")
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT cs.session_type,
                   bs.win_rate,
                   bs.rr,
                   bs.gain
            FROM discord_bot_signals bs
            JOIN corey_session_bias cs ON DATE(bs.timestamp) = cs.date
            WHERE bs.symbol = ?
              AND bs.timestamp >= ?
              AND bs.signal_type = 'ENTRY'
              AND bs.win_rate IS NOT NULL
              AND cs.data_quality IN ('fresh', 'stale')
            """,
            (symbol.upper(), cutoff),
        ).fetchall()

    if not rows:
        return []

    groups: Dict[str, Dict] = {}
    for row in rows:
        st = row["session_type"] or "unknown"
        if st not in groups:
            groups[st] = {"win_rates": [], "rrs": [], "gains": []}
        groups[st]["win_rates"].append((row["win_rate"] or 0.0) / 100.0)
        if row["rr"] is not None:
            groups[st]["rrs"].append(row["rr"])
        if row["gain"] is not None:
            groups[st]["gains"].append(row["gain"])

    results = []
    for session_type, data in groups.items():
        n = len(data["win_rates"])
        if n < min_signals:
            continue
        results.append({
            "session_type": session_type,
            "signal_count": n,
            "avg_win_rate": round(sum(data["win_rates"]) / n, 4),
            "avg_rr": round(sum(data["rrs"]) / len(data["rrs"]), 4) if data["rrs"] else None,
            "avg_gain": round(sum(data["gains"]) / len(data["gains"]), 4) if data["gains"] else None,
        })

    return sorted(results, key=lambda x: x["signal_count"], reverse=True)


def analyze_conviction_threshold(
    symbol: str,
    lookback_days: int = 90,
    db_path: Optional[str] = None,
    min_signals: int = MIN_SIGNALS_ANALYSIS,
) -> List[dict]:
    """
    Win rate by Corey's conviction bucket (0–0.3 low, 0.3–0.6 med, 0.6–1.0 high).
    A monotone increase validates that the LLM extraction has genuine discriminative
    power; a flat or inverted pattern suggests extraction noise.

    Returns list of dicts: conviction_bucket, conviction_range, signal_count,
        avg_win_rate, avg_rr
    """
    BUCKETS = [
        ("low",    0.0,                    CONVICTION_BUCKET_LOW),
        ("medium", CONVICTION_BUCKET_LOW,  CONVICTION_BUCKET_HIGH),
        ("high",   CONVICTION_BUCKET_HIGH, 1.01),
    ]
    if db_path is None:
        db_path = str(_db_path())
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%dT%H:%M:%S")
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT cs.conviction,
                   bs.win_rate,
                   bs.rr
            FROM discord_bot_signals bs
            JOIN corey_session_bias cs ON DATE(bs.timestamp) = cs.date
            WHERE bs.symbol = ?
              AND bs.timestamp >= ?
              AND bs.signal_type = 'ENTRY'
              AND bs.win_rate IS NOT NULL
              AND cs.conviction IS NOT NULL
              AND cs.data_quality IN ('fresh', 'stale')
            """,
            (symbol.upper(), cutoff),
        ).fetchall()

    if not rows:
        return []

    bucket_data: Dict[str, Dict] = {
        label: {"win_rates": [], "rrs": [], "lo": lo, "hi": hi}
        for label, lo, hi in BUCKETS
    }
    for row in rows:
        conviction = row["conviction"] or 0.0
        for label, lo, hi in BUCKETS:
            if lo <= conviction < hi:
                bucket_data[label]["win_rates"].append((row["win_rate"] or 0.0) / 100.0)
                if row["rr"] is not None:
                    bucket_data[label]["rrs"].append(row["rr"])
                break

    results = []
    for label, data in bucket_data.items():
        n = len(data["win_rates"])
        if n < min_signals:
            continue
        results.append({
            "conviction_bucket": label,
            "conviction_range": f"{data['lo']:.1f}–{data['hi']:.1f}",
            "signal_count": n,
            "avg_win_rate": round(sum(data["win_rates"]) / n, 4),
            "avg_rr": round(sum(data["rrs"]) / len(data["rrs"]), 4) if data["rrs"] else None,
        })

    return results


def get_corey_alignment_summary(
    symbol: str,
    lookback_days: int = 90,
    db_path: Optional[str] = None,
) -> dict:
    """Aggregate all three Corey-bias analyses into a single summary dict.

    summary fields:
      aligned_avg_win_rate / opposed_avg_win_rate  — weighted win rates (0.0–1.0)
      aligned_signal_count / opposed_signal_count  — sample sizes
      edge_present     — True when aligned_wr > opposed_wr (point estimate only)
      p_value          — chi-squared p-value (None if n < 30 per group)
      edge_significant — True when p_value < 0.05 (None if sample too small)
    """
    alignment = analyze_corey_alignment_win_rate(symbol, lookback_days, db_path)
    session_perf = analyze_session_type_performance(symbol, lookback_days, db_path)
    conviction = analyze_conviction_threshold(symbol, lookback_days, db_path)

    aligned_rows = [r for r in alignment if r["aligned"] is True]
    opposed_rows = [r for r in alignment if r["aligned"] is False]

    def _wavg_wr(rows: list) -> Optional[float]:
        total = sum(r["signal_count"] for r in rows)
        if total == 0:
            return None
        return round(sum(r["avg_win_rate"] * r["signal_count"] for r in rows) / total, 4)

    aligned_wr = _wavg_wr(aligned_rows)
    opposed_wr = _wavg_wr(opposed_rows)
    aligned_count = sum(r["signal_count"] for r in aligned_rows)
    opposed_count = sum(r["signal_count"] for r in opposed_rows)

    # Chi-squared significance test — requires ≥30 samples per group.
    # Converts weighted win rates back to integer win/loss counts for the
    # contingency table; rounding error is negligible at n≥30.
    p_value: Optional[float] = None
    edge_significant: Optional[bool] = None
    if aligned_count >= 30 and opposed_count >= 30 and aligned_wr is not None and opposed_wr is not None:
        try:
            from scipy.stats import chi2_contingency  # noqa: PLC0415

            a_wins = round(aligned_wr * aligned_count)
            a_losses = aligned_count - a_wins
            o_wins = round(opposed_wr * opposed_count)
            o_losses = opposed_count - o_wins
            if a_losses >= 0 and o_losses >= 0:
                _, pv, _, _ = chi2_contingency(
                    [[a_wins, a_losses], [o_wins, o_losses]]
                )
                p_value = round(float(pv), 4)
                edge_significant = p_value < 0.05
        except Exception:
            pass  # scipy unavailable or degenerate table — silently omit

    return {
        "symbol": symbol,
        "lookback_days": lookback_days,
        "alignment": alignment,
        "session_type_performance": session_perf,
        "conviction_threshold": conviction,
        "summary": {
            "aligned_avg_win_rate": aligned_wr,
            "opposed_avg_win_rate": opposed_wr,
            "aligned_signal_count": aligned_count,
            "opposed_signal_count": opposed_count,
            "edge_present": (
                aligned_wr is not None
                and opposed_wr is not None
                and aligned_wr > opposed_wr
            ),
            "p_value": p_value,
            "edge_significant": edge_significant,
        },
    }


# ── Main study runner ─────────────────────────────────────────────────────────


def run_correlation_study(
    symbols: Optional[List[str]] = None,
    output_path: Optional[str] = None,
) -> pd.DataFrame:
    """
    Run the full Discord signal correlation study across *symbols*.
    Saves CSV to *output_path* (defaults to data/discord_correlation_study.csv).
    Prints a human-readable summary table to stdout.

    Returns the per-symbol category summary DataFrame.
    """
    output_file = Path(output_path) if output_path else _default_output()
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(_db_path()) as conn:
        # Determine available symbols if not provided
        if symbols is None:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT DISTINCT symbol FROM discord_bot_signals
                WHERE signal_type = 'ENTRY'
                  AND win_rate IS NOT NULL
                  AND direction IS NOT NULL
                ORDER BY symbol
                """
            )
            symbols = [r[0] for r in cur.fetchall()]

        print(f"\n{'='*70}")
        print("JARVIS TRADER — Discord Signal Correlation Study")
        print(f"DB: {_db_path()}")
        print(f"Symbols: {symbols}")
        print(f"{'='*70}\n")

        # ── Section 1: Per-symbol category statistics ─────────────────────────
        summary_rows = []

        for symbol in symbols:
            print(f"  Analysing {symbol}...", end=" ", flush=True)
            df = analyze_signal_alignment(symbol)
            if df.empty:
                print("no data, skipped.")
                continue
            stats = compute_statistics(df)
            print(f"{len(df):,} signals → {len(stats)} categories")

            for cat, s in stats.items():
                if s["signal_count"] < MIN_SIGNALS_FOR_REPORT:
                    continue
                hour_df = df[df["full_category"] == cat]
                hour_wr = hour_df.groupby("hour_of_day")["win_rate_norm"].mean()
                best_hour = int(hour_wr.idxmax()) if not hour_wr.empty else -1
                worst_hour = int(hour_wr.idxmin()) if not hour_wr.empty else -1
                summary_rows.append(
                    {
                        "symbol": symbol,
                        "category": cat,
                        "signal_count": s["signal_count"],
                        "avg_win_rate": s["avg_win_rate"],
                        "avg_gain": s["avg_gain"],
                        "avg_draw": s["avg_draw"],
                        "best_hour": best_hour,
                        "worst_hour": worst_hour,
                    }
                )

        summary_df = pd.DataFrame(summary_rows)

        # ── Section 2: Hour-of-day statistics ────────────────────────────────
        print("\n  Computing hour-of-day patterns across all symbols...")
        all_df = _fetch_signals(conn, symbols=symbols)
        hour_stats_df = _compute_hour_stats(all_df)

        # ── Section 3: Streak analysis ────────────────────────────────────────
        print("  Computing streak patterns...")
        streak_df = _compute_streak_stats(all_df)

        # ── Section 4: Cross-market NQ alignment ─────────────────────────────
        print("  Computing cross-market NQ alignment...")
        cross_df = _compute_cross_market_alignment(conn)

    # ── Save CSV ──────────────────────────────────────────────────────────────
    summary_df.to_csv(output_file, index=False)
    print(f"\n  CSV saved → {output_file}\n")

    # ── Print summary tables ──────────────────────────────────────────────────
    _print_section("1. PER-SYMBOL ALIGNMENT CATEGORY SUMMARY", summary_df)
    _print_cross_market(cross_df)
    _print_streak(streak_df)
    _print_best_hours(hour_stats_df)

    return summary_df


# ── Pretty-print helpers ─────────────────────────────────────────────────────


def _print_section(title: str, df: pd.DataFrame) -> None:
    if df.empty:
        print(f"\n[{title}] — no data\n")
        return

    print(f"\n{'─'*70}")
    print(f"  {title}")
    print(f"{'─'*70}")
    print(
        f"  {'Symbol':<8} {'Category':<28} {'Count':>7} {'WinRate':>8} "
        f"{'AvgGain':>10} {'AvgDraw':>10} {'BestH':>6} {'WorstH':>7}"
    )
    print(f"  {'─'*8} {'─'*28} {'─'*7} {'─'*8} {'─'*10} {'─'*10} {'─'*6} {'─'*7}")

    for _, row in df.iterrows():
        wr = f"{row['avg_win_rate']*100:.1f}%"
        print(
            f"  {row['symbol']:<8} {row['category']:<28} {row['signal_count']:>7,} "
            f"{wr:>8} {row['avg_gain']:>10.2f} {row['avg_draw']:>10.2f} "
            f"{int(row['best_hour']):>5}h {int(row['worst_hour']):>5}h"
        )
    print()


def _print_cross_market(df: pd.DataFrame) -> None:
    if df.empty:
        print("\n[Cross-Market NQ Alignment] — no data\n")
        return

    print(f"\n{'─'*70}")
    print("  2. CROSS-MARKET NQ ALIGNMENT")
    print(f"{'─'*70}")
    print(
        f"  {'Symbol':<8} {'Alignment':<22} {'Count':>7} "
        f"{'WinRate':>8} {'AvgGain':>10} {'AvgDraw':>10}"
    )
    print(f"  {'─'*8} {'─'*22} {'─'*7} {'─'*8} {'─'*10} {'─'*10}")

    for _, row in df.sort_values(["symbol", "alignment_group"]).iterrows():
        wr = f"{row['avg_win_rate']*100:.1f}%"
        print(
            f"  {row['symbol']:<8} {row['alignment_group']:<22} "
            f"{row['signal_count']:>7,} {wr:>8} "
            f"{row['avg_gain']:>10.4f} {row['avg_draw']:>10.4f}"
        )
    print()


def _print_streak(df: pd.DataFrame) -> None:
    if df.empty:
        print("\n[Streak Analysis] — no data\n")
        return

    print(f"\n{'─'*70}")
    print("  3. STREAK ANALYSIS (3+ consecutive same-direction signals)")
    print(f"{'─'*70}")
    print(
        f"  {'Symbol':<8} {'Group':<14} {'Count':>7} "
        f"{'WinRate':>8} {'AvgGain':>10} {'AvgDraw':>10}"
    )
    print(f"  {'─'*8} {'─'*14} {'─'*7} {'─'*8} {'─'*10} {'─'*10}")

    for _, row in df.sort_values(["symbol", "group"]).iterrows():
        wr = f"{row['avg_win_rate']*100:.1f}%" if not pd.isna(row["avg_win_rate"]) else "  n/a"
        gain = f"{row['avg_gain']:10.4f}" if not pd.isna(row["avg_gain"]) else "       n/a"
        draw = f"{row['avg_draw']:10.4f}" if not pd.isna(row["avg_draw"]) else "       n/a"
        print(
            f"  {row['symbol']:<8} {row['group']:<14} "
            f"{row['signal_count']:>7,} {wr:>8} {gain} {draw}"
        )
    print()


def _print_best_hours(df: pd.DataFrame) -> None:
    if df.empty:
        print("\n[Hour-of-Day Analysis] — no data\n")
        return

    print(f"\n{'─'*70}")
    print("  4. TOP 3 BEST HOURS BY WIN RATE (per symbol)")
    print(f"{'─'*70}")
    print(f"  {'Symbol':<8} {'Hour (UTC)':<12} {'Count':>7} " f"{'WinRate':>8} {'AvgGain':>10}")
    print(f"  {'─'*8} {'─'*12} {'─'*7} {'─'*8} {'─'*10}")

    for _symbol, sym_df in df.groupby("symbol"):
        top3 = sym_df.nlargest(3, "avg_win_rate")
        for _, row in top3.iterrows():
            wr = f"{row['avg_win_rate']*100:.1f}%"
            print(
                f"  {row['symbol']:<8} {int(row['hour_of_day']):02d}:xx UTC    "
                f"{row['signal_count']:>7,} {wr:>8} {row['avg_gain']:>10.4f}"
            )
    print()


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Correlate Discord bot signals with JARVIS signal confidence tiers."
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Symbols to analyse (default: all in DB)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=f"CSV output path (default: {_default_output()})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit signals per symbol (0 = unlimited)",
    )
    args = parser.parse_args()

    run_correlation_study(symbols=args.symbols, output_path=args.output)
