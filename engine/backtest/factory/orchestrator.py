"""Funnel orchestrator: cards -> smoke -> robustness, all logged to the results DB.

Two-pass so the Deflated-Sharpe denominator is honest. Pass 1 enumerates every
candidate (card x native-instrument-in-universe x native-timeframe-in-universe) and
sums the total parameterizations the factory will try; that fixed total is the DSR
`n_trials` for EVERY survivor (multiple-testing is global, not per-card). Pass 2
runs smoke, then the robustness gauntlet only on smoke survivors. Every candidate
and every verdict is written to `ResultsDB` -- the audit trail that forecloses the
"quietly tested a tiny subset" failure mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backtest.factory.data import has_cache, load_bars, spec_for
from backtest.factory.funnel import robustness_gauntlet, smoke_test
from backtest.factory.results_db import ResultsDB
from backtest.factory.strategy_card import StrategyCard


@dataclass
class Universe:
    instruments: list[str]
    timeframes: list[str]


# The liquid bar-data universe the factory scans (futures + their ETF proxies).
FACTORY_INSTRUMENTS = [
    "MES",
    "ES",
    "MNQ",
    "NQ",
    "M2K",
    "MGC",
    "GC",
    "MCL",
    "CL",
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "GLD",
    "ZB",
    "ZN",
]
# Intraday only -- daily/low-frequency edges are handled in the calendar track,
# where a single-split + DSR evaluation fits low trade counts (pilot finding B).
INTRADAY_TFS = ["1h", "30m", "15m", "5m"]


def factory_cards() -> list[StrategyCard]:
    """The full intraday card library: one card per factory-compatible generic
    generator, each carrying a real economic rationale and a small param grid.

    Excluded by design: sma_trend (daily/low-freq -> calendar track); ORB/TPO
    (dedicated engines); composite_v3 (takes a `symbol` arg the adapter can't
    thread -> would silently run as MES everywhere); vwap (needs session-anchor
    params -> does not emit the contract with defaults); atr_trail_bounce (absent
    from origin/master). Cross-instrument breadth IS the point -- a generic edge
    is tested on every liquid instrument; the gauntlet's PBO/DSR + the global
    trial counter keep the multiple-testing honest.
    """
    inst = list(FACTORY_INSTRUMENTS)
    tfs = list(INTRADAY_TFS)
    return [
        StrategyCard(
            name="donchian_channel",
            family="breakout",
            signal_ref="backtest.donchian_signals:generate_donchian_signals",
            entry="close breaks the N-bar Donchian high/low",
            exit="opposite M-bar channel / ATR trail",
            economic_rationale="Trend persistence: a fresh N-bar breakout reflects a real "
            "order-flow imbalance (stop runs + breakout entries) that tends to continue for "
            "several bars before reverting.",
            native_instruments=inst,
            native_timeframes=tfs,
            default_params={"lookback_entry": 20, "lookback_exit": 10},
            param_grid={"lookback_entry": [20, 40, 55], "lookback_exit": [10, 20]},
            known_failure_modes=["range/chop regimes whipsaw the breakout"],
        ),
        StrategyCard(
            name="donchian_breakout_vol",
            family="breakout",
            signal_ref="backtest.breakout_signals:generate_donchian_breakout_signals",
            entry="Donchian breakout confirmed by a volume expansion",
            exit="ATR trail",
            economic_rationale="Breakout with a participation filter: requiring above-average "
            "volume on the break screens out low-conviction false breaks, so only moves backed "
            "by genuine order flow are taken.",
            native_instruments=inst,
            native_timeframes=tfs,
            default_params={"donchian_period": 20, "stop_atr_mult": 2.0},
            param_grid={"donchian_period": [20, 40], "vol_mult": [1.0, 1.5]},
            known_failure_modes=["thin-volume instruments give noisy volume filters"],
        ),
        StrategyCard(
            name="bollinger_rsi_meanrev",
            family="meanrev",
            signal_ref="backtest.meanrev_signals:generate_bollinger_rsi_signals",
            entry="price pierces a Bollinger band with RSI confirming exhaustion",
            exit="reversion to the band midline / ATR stop",
            economic_rationale="Short-horizon mean reversion: a 2-sigma band stretch with an "
            "RSI extreme marks a liquidity-driven overshoot that statistically snaps back toward "
            "the moving-average anchor intraday.",
            native_instruments=inst,
            native_timeframes=tfs,
            default_params={"bb_period": 20, "bb_std": 2.0, "rsi_long": 30.0, "rsi_short": 70.0},
            param_grid={"bb_period": [15, 20], "bb_std": [2.0, 2.5], "rsi_long": [25.0, 30.0]},
            known_failure_modes=["strong trends pin price to one band"],
        ),
        StrategyCard(
            name="adx_ema_trend",
            family="trend",
            signal_ref="backtest.adx_ema_signals:generate_adx_ema_signals",
            entry="EMA-slope direction gated by ADX above the strong-trend threshold",
            exit="ADX falls below exit threshold / ATR trail",
            economic_rationale="Trend-following with a strength gate: ADX confirms a directional "
            "regime so the EMA-slope entry only fires when a real trend (not noise) is paying, "
            "capturing autocorrelation in trending instruments.",
            native_instruments=inst,
            native_timeframes=tfs,
            default_params={"adx_threshold": 25.0, "ema_period": 21},
            param_grid={"adx_threshold": [20.0, 25.0], "ema_period": [21, 50]},
            known_failure_modes=["lag at trend turns; ADX gate mutes early entries"],
        ),
        StrategyCard(
            name="atr_channel_trend",
            family="trend",
            signal_ref="backtest.atr_channel_signals:generate_atr_channel_signals",
            entry="close breaks an ATR-width channel around an EMA in an expanding-vol regime",
            exit="ATR stop",
            economic_rationale="Volatility-expansion trend: an ATR-band break during expanding "
            "realized vol captures the start of directional impulses, when range expansion and "
            "trend continuation coincide.",
            native_instruments=inst,
            native_timeframes=tfs,
            default_params={"ema_period": 20, "atr_mult": 2.0, "atr_stop_mult": 2.0},
            param_grid={"ema_period": [20, 50], "atr_mult": [1.5, 2.0]},
            known_failure_modes=["false breaks when vol expands without follow-through"],
        ),
        StrategyCard(
            name="saty_atr_pivots",
            family="breakout",
            signal_ref="backtest.saty_atr_signals:generate_saty_atr_signals",
            entry="ATR-pivot band break with a range-consumed filter (Saty ATR levels)",
            exit="ATR target / opposite band",
            economic_rationale="Intraday ATR levels act as mean-reversion and breakout pivots: "
            "price tends to react at the prior-close +/- ATR bands, so a confirmed band break "
            "with sufficient range consumed signals a directional day.",
            native_instruments=inst,
            native_timeframes=tfs,
            default_params={"entry_band": 1.0, "target_ratio": 1.0, "min_range_consumed": 0.7},
            param_grid={"entry_band": [0.5, 1.0], "target_ratio": [1.0, 1.5]},
            known_failure_modes=["needs a clean prior-close anchor; 24h futures blur the session"],
        ),
        StrategyCard(
            name="initial_balance_breakout",
            family="breakout",
            signal_ref="backtest.ib_breakout_signals:generate_ib_breakout_signals",
            entry="break of the first-hour initial-balance high/low",
            exit="IB-range-multiple targets",
            economic_rationale="Opening-range / initial-balance breakout: the first hour sets the "
            "day's value area, and a decisive break of it tends to run as late participants chase "
            "the established direction.",
            native_instruments=inst,
            native_timeframes=tfs,
            default_params={"open_minutes": 60, "target_mult_1": 1.0, "target_mult_2": 2.0},
            param_grid={"open_minutes": [30, 60], "target_mult_1": [1.0, 1.5]},
            known_failure_modes=["holiday/half sessions distort the initial balance"],
        ),
        StrategyCard(
            name="rsi_breakout",
            family="breakout",
            signal_ref="backtest.rsi_breakout_signals:generate_rsi_breakout_signals",
            entry="momentum breakout confirmed by RSI clearing an extreme",
            exit="opposite channel / ATR stop",
            economic_rationale="Momentum continuation: an RSI thrust through an extreme alongside "
            "a price-channel break signals a momentum regime where the move tends to extend rather "
            "than revert.",
            native_instruments=inst,
            native_timeframes=tfs,
            default_params={"rsi_oversold": 25.0, "rsi_overbought": 75.0, "entry_period": 20},
            param_grid={"rsi_oversold": [20.0, 30.0], "entry_period": [14, 20]},
            known_failure_modes=["fires rarely with strict thresholds; low sample on calm regimes"],
        ),
    ]


def pilot_cards() -> list[StrategyCard]:
    """Four economically-motivated cards on generic column-emitting generators.

    Every card carries a real `economic_rationale` (the gate kills blank ones) and
    a small param grid. ORB/TPO have dedicated engines and are out of pilot scope.
    """
    return [
        StrategyCard(
            name="donchian_breakout",
            family="breakout",
            signal_ref="backtest.donchian_signals:generate_donchian_signals",
            entry="close breaks the N-bar high (channel breakout)",
            exit="opposite M-bar channel / ATR trail",
            economic_rationale="Trend persistence: a fresh N-bar breakout reflects a "
            "genuine order-flow imbalance (stops + breakout buyers) that tends to "
            "continue for several bars before mean-reverting.",
            native_instruments=["MES", "SPY"],
            native_timeframes=["1h"],
            default_params={"lookback_entry": 20, "lookback_exit": 10},
            param_grid={"lookback_entry": [20, 40, 55], "lookback_exit": [10, 20]},
            known_failure_modes=["chop/range regimes whipsaw the breakout"],
        ),
        StrategyCard(
            name="bollinger_rsi_meanrev",
            family="meanrev",
            signal_ref="backtest.meanrev_signals:generate_bollinger_rsi_signals",
            entry="price pierces lower/upper Bollinger band with RSI confirming exhaustion",
            exit="reversion to the band midline / ATR stop",
            economic_rationale="Short-horizon mean reversion: a 2-sigma band stretch with "
            "an RSI extreme marks a liquidity-driven overshoot that statistically snaps "
            "back toward the moving-average anchor intraday.",
            native_instruments=["MES", "SPY"],
            native_timeframes=["1h"],
            default_params={"bb_period": 20, "bb_std": 2.0, "rsi_long": 30.0, "rsi_short": 70.0},
            param_grid={"bb_period": [15, 20], "rsi_long": [25.0, 30.0]},
            known_failure_modes=["strong trends keep price pinned to one band"],
        ),
        StrategyCard(
            name="adx_ema_trend",
            family="trend",
            signal_ref="backtest.adx_ema_signals:generate_adx_ema_signals",
            entry="EMA slope direction with ADX above the strong-trend threshold",
            exit="ADX falls below exit threshold / ATR trail",
            economic_rationale="Trend-following with a strength gate: ADX confirms a "
            "directional regime so the EMA-slope entry only fires when a real trend (not "
            "noise) is paying, capturing the autocorrelation in trending instruments.",
            native_instruments=["MES", "SPY"],
            native_timeframes=["1h", "1d"],
            default_params={"adx_threshold": 25.0, "ema_period": 21},
            param_grid={"adx_threshold": [20.0, 25.0], "ema_period": [21, 50]},
            known_failure_modes=["lag at trend turns; ADX gate mutes early entries"],
        ),
        StrategyCard(
            name="sma_trend",
            family="trend",
            signal_ref="backtest.trend_signals:generate_sma_trend_signals",
            entry="fast SMA above/below slow SMA (classic dual-MA trend)",
            exit="opposite cross / ATR trail",
            economic_rationale="Long-horizon trend premium: the dual-SMA cross harvests "
            "the documented time-series momentum premium in equity indices, which is "
            "strongest on the daily timeframe over multi-month holds.",
            native_instruments=["MES", "SPY"],
            native_timeframes=["1d"],
            default_params={"fast": 60, "slow": 200},
            param_grid={"fast": [40, 60], "slow": [150, 200]},
            known_failure_modes=["range-bound years bleed via repeated false crosses"],
        ),
    ]


def enumerate_candidates(
    cards: list[StrategyCard], universe: Universe
) -> list[tuple[StrategyCard, str, str]]:
    """Card x (native instruments ∩ universe) x (native timeframes ∩ universe)."""
    inst = set(universe.instruments)
    tfs = set(universe.timeframes)
    out = []
    for card in cards:
        for sym in [s for s in card.native_instruments if s in inst]:
            for tf in [t for t in card.native_timeframes if t in tfs]:
                out.append((card, sym, tf))
    return out


def run_funnel(
    cards: list[StrategyCard],
    universe: Universe,
    cache_dir: str | Path,
    db_path: str | Path,
    created_at: str,
) -> dict:
    """Run the full pilot funnel. Returns a summary dict; full detail is in the DB."""
    db = ResultsDB(db_path)
    run_id = db.new_run(
        created_at,
        {"universe": vars(universe), "n_cards": len(cards), "cache_dir": str(cache_dir)},
    )

    all_candidates = enumerate_candidates(cards, universe)
    # Drop combos with no cached data BEFORE counting trials, so the global DSR
    # denominator reflects only configurations that actually run (no phantom
    # inflation from missing instrument/timeframe cells).
    candidates = [(c, s, t) for c, s, t in all_candidates if has_cache(s, t, cache_dir)]
    skipped = [(c, s, t) for c, s, t in all_candidates if not has_cache(s, t, cache_dir)]
    # Global DSR denominator = total parameterizations the factory will try.
    global_trials = sum(c.n_param_combos() for c, _, _ in candidates)

    rows = []
    for card, sym, tf in skipped:
        rows.append(
            {"card": card.name, "sym": sym, "tf": tf, "stage": "skip", "reason": "no cache"}
        )
    for card, sym, tf in candidates:
        cid = db.record_candidate(run_id, card.name, sym, tf, card.default_params, "smoke")
        try:
            bars = load_bars(sym, tf, cache_dir)
        except FileNotFoundError as e:
            db.record_result(cid, "smoke", {"error": str(e)}, verdict="SKIP", kill_reason="no data")
            rows.append(
                {"card": card.name, "sym": sym, "tf": tf, "stage": "skip", "reason": "no data"}
            )
            continue
        mult = float(spec_for(sym)["multiplier"])

        survives, sm = smoke_test(card, bars, sym, mult)
        db.record_result(
            cid,
            "smoke",
            sm,
            verdict="PASS" if survives else "KILL",
            kill_reason=sm.get("kill_reason"),
        )
        row = {"card": card.name, "sym": sym, "tf": tf, "smoke": sm, "smoke_pass": survives}
        if not survives:
            row["stage"] = "killed_smoke"
            rows.append(row)
            continue

        gate = robustness_gauntlet(card, bars, sym, mult, global_trials)
        verdict = gate.get("verdict", "FAIL")
        db.record_result(cid, "robustness", gate, verdict=verdict)
        row["stage"] = "robustness"
        row["gate"] = gate
        row["verdict"] = verdict
        rows.append(row)

    summary = {
        "run_id": run_id,
        "created_at": created_at,
        "global_trials": global_trials,
        "n_candidates": len(candidates),
        "n_skipped_no_cache": len(skipped),
        "n_smoke_pass": sum(1 for r in rows if r.get("smoke_pass")),
        "n_robustness_pass": sum(1 for r in rows if r.get("verdict") == "PASS"),
        "rows": rows,
    }
    db.close()
    return summary


def render_report(summary: dict) -> str:
    """Markdown report -- survivors, kills with reasons, and the global wiring."""
    s = summary
    lines = [
        "# Strategy-Factory Report",
        "",
        f"- Run ID: `{s['run_id']}`  |  Created: {s['created_at']}",
        f"- Candidates screened: **{s['n_candidates']}**  "
        f"(global DSR n_trials = **{s['global_trials']}** parameterizations)"
        + (
            f"  |  skipped (no cache): {s['n_skipped_no_cache']}"
            if s.get("n_skipped_no_cache")
            else ""
        ),
        f"- Smoke survivors: **{s['n_smoke_pass']}**  |  Robustness PASS: **{s['n_robustness_pass']}**",
        "",
    ]

    ran = [r for r in s["rows"] if r.get("stage") != "skip"]
    survivors = [r for r in ran if r.get("verdict") == "PASS"]

    # Headline: robustness PASS survivors (the only rows worth a forward-shadow).
    lines += ["## Survivors (robustness PASS -> forward-shadow candidates)", ""]
    if survivors:
        for r in survivors:
            g = r.get("gate", {})
            lines.append(
                f"- **{r['card']} {r['sym']} {r['tf']}** via {g.get('passed_via', '?')} "
                f"| pf_ci_lower {_fmt(g.get('pf_ci_lower'))} | dsr {_fmt(g.get('dsr'))} "
                f"| dsr_global {_fmt(g.get('dsr_global'))} | PBO {_fmt(g.get('pbo'))} "
                f"| mc_dd {_fmt(g.get('mc_95th_dd_pct'))}%"
            )
    else:
        lines.append("_None. No configuration cleared gate-v2 after PBO + global DSR._")

    # Robustness-tested table (smoke survivors that reached the gauntlet).
    tested = [r for r in ran if r.get("smoke_pass")]
    lines += [
        "",
        "## Robustness-tested (smoke survivors)",
        "",
        "| Card | Sym | TF | Verdict | pf_ci | mc_dd% | dsr | dsr_global | PBO |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in tested:
        g = r.get("gate", {}) or {}
        lines.append(
            f"| {r['card']} | {r['sym']} | {r['tf']} | {r.get('verdict', '-')} "
            f"| {_fmt(g.get('pf_ci_lower'))} | {_fmt(g.get('mc_95th_dd_pct'))} "
            f"| {_fmt(g.get('dsr'))} | {_fmt(g.get('dsr_global'))} | {_fmt(g.get('pbo'))} |"
        )
    if not tested:
        lines.append("| _none_ | | | | | | | | |")

    # Kill / fail reasons (Amo's explicit ask: why each failed is as valuable).
    lines += ["", "## Kill / fail reasons", ""]
    for r in ran:
        if r.get("verdict") == "PASS":
            continue
        if not r.get("smoke_pass"):
            reason = (r.get("smoke", {}) or {}).get("kill_reason") or "below smoke floor"
            lines.append(f"- **{r['card']} {r['sym']} {r['tf']}** — smoke KILL: {reason}")
        else:
            g = r.get("gate", {}) or {}
            reason = g.get("reason") or _gate_fail_reason(g)
            lines.append(
                f"- **{r['card']} {r['sym']} {r['tf']}** — robustness {r.get('verdict')}: {reason}"
            )

    # Aggregate coverage gaps (no point listing each no-cache cell).
    skips = [r for r in s["rows"] if r.get("stage") == "skip"]
    if skips:
        gaps = sorted({f"{r['sym']} {r['tf']}" for r in skips})
        lines += [
            "",
            "## Coverage gaps (no cache)",
            "",
            f"{len(skips)} combos skipped: " + ", ".join(gaps),
        ]
    return "\n".join(lines)


def _fmt(v) -> str:
    if v is None:
        return "-"
    try:
        return f"{float(v):.3f}"
    except (TypeError, ValueError):
        return str(v)


def _gate_fail_reason(gate: dict) -> str:
    """Best-effort human reason from gate sub-metrics."""
    bits = []
    if gate.get("pf_ci_lower") is not None and gate["pf_ci_lower"] < 1.10:
        bits.append(f"pf_ci_lower {gate['pf_ci_lower']:.2f}<1.10")
    if gate.get("p_edge") is not None and gate["p_edge"] < 0.95:
        bits.append(f"p_edge {gate['p_edge']:.2f}<0.95")
    dd = gate.get("mc_95th_dd_pct", gate.get("mc_95th_dd"))
    if dd is not None and dd > 5.0:
        bits.append(f"mc_dd {dd:.1f}%>5%")
    if gate.get("dsr") is not None and gate["dsr"] < 0.10:
        bits.append(f"dsr {gate['dsr']:.2f}<0.10")
    if gate.get("pbo") is not None and gate["pbo"] > 0.5:
        bits.append(f"PBO {gate['pbo']:.2f}>0.5 (overfit)")
    return "; ".join(bits) if bits else "did not clear gate-v2 core or ALT"
