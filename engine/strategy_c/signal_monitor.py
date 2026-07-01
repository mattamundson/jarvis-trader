"""
Strategy C+ Signal Health Monitor
==================================
Checks the live signal for staleness, anomalies, and missing fields.
Posts to Discord via DISCORD_WEBHOOK_URL env var when issues are found.
Designed to run as a GitHub Actions cron (every 6 hours) and locally.

Exit codes:
  0 = healthy (no Discord alert)
  1 = anomaly detected (Discord alert sent)
  2 = signal stale / missing (Discord alert sent)
  3 = configuration error (Discord alert sent)
"""
from __future__ import annotations

import json
import math
import os
import statistics
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# ── Paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
SIGNAL_FILE    = Path(__file__).parent / "output" / "strategy_c_plus_live_signal.json"
BASELINE_FILE  = Path(__file__).parent / "output" / "signal_baseline.json"
HISTORY_FILE   = Path(__file__).parent / "output" / "signal_history.json"

# ── Config ────────────────────────────────────────────────────────────────────
SIGNAL_MAX_AGE_DAYS  = 9    # Friday cron → 9 days before Monday MOO = safe window
STALE_WARN_DAYS      = 7    # warn at 7 days even if not yet hard-stale
ANOMALY_SIGMA        = 2.0  # z-score threshold vs bootstrap prior
WEEK_CHANGE_WARN_PCT = 0.30 # flag if combined_scale moves >30% in one week
MIN_LIVE_WEEKS_FOR_LIVE_BASELINE = 10  # switch from bootstrap → live history

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")

# ── Discord ───────────────────────────────────────────────────────────────────

def post_discord(embed: dict) -> None:
    if not DISCORD_WEBHOOK:
        print("[monitor] DISCORD_WEBHOOK_URL not set — skipping Discord post.")
        return
    payload = json.dumps({"embeds": [embed]}).encode()
    req = urllib.request.Request(
        DISCORD_WEBHOOK,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status not in (200, 204):
                print(f"[monitor] Discord returned {resp.status}")
    except urllib.error.URLError as e:
        print(f"[monitor] Discord post failed: {e}")


def post_healthy(signal: dict, history_count: int) -> None:
    scale = signal.get("combined_scale", 0)
    holdings = signal.get("holdings", {})
    eff_date = signal.get("effective_date", "?")
    gen_at = signal.get("generated_at", "?")
    layers = signal.get("layers", {})
    vol = layers.get("vol_targeting", {})
    vix = layers.get("vix_composite", {})

    holdings_str = "  ".join(
        f"{tk} {wt:.1%}" for tk, wt in sorted(holdings.items(), key=lambda x: -x[1])
    )
    embed = {
        "title": "✅ Strategy C+ Signal — Healthy",
        "color": 3066993,
        "fields": [
            {"name": "Effective Date",   "value": eff_date,                          "inline": True},
            {"name": "Combined Scale",   "value": f"{scale:.3f} ({scale*100:.1f}%)", "inline": True},
            {"name": "Holdings",         "value": holdings_str,                       "inline": False},
            {"name": "VIX Level",        "value": f"{vix.get('vix',0):.1f}  [{vix.get('vix_regime','?')}]  composite={vix.get('composite_regime','?')}", "inline": True},
            {"name": "RealVol Regime",   "value": f"{vol.get('realized_vol_pct',0):.1f}%  [{vol.get('vol_regime','?')}]  scale={vol.get('scale',0):.3f}", "inline": True},
            {"name": "Generated",        "value": gen_at[:19] if gen_at != "?" else "?", "inline": True},
            {"name": "Live History",     "value": f"{history_count} weeks accumulated", "inline": True},
        ],
        "footer": {"text": "Jarvis Trader · Signal Monitor · every 6 hours"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    post_discord(embed)


def post_alert(title: str, description: str, flags: list[str], signal: dict, color: int = 16776960) -> None:
    scale = signal.get("combined_scale", "?")
    eff_date = signal.get("effective_date", "?")
    flags_str = "\n".join(f"• {f}" for f in flags) if flags else "see description"
    embed = {
        "title": title,
        "description": description,
        "color": color,
        "fields": [
            {"name": "Flags",          "value": flags_str,                                             "inline": False},
            {"name": "Scale",          "value": f"{scale:.3f}" if isinstance(scale, float) else "?",  "inline": True},
            {"name": "Signal Date",    "value": eff_date,                                              "inline": True},
        ],
        "footer": {"text": "Jarvis Trader · Signal Monitor"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    post_discord(embed)

# ── Signal history accumulator ─────────────────────────────────────────────────

def append_to_history(signal: dict) -> int:
    """Append current signal to rolling history. Returns total count."""
    history: dict[str, Any] = {"signals": []}
    if HISTORY_FILE.exists():
        try:
            history = json.loads(HISTORY_FILE.read_text())
        except Exception:
            history = {"signals": []}

    signals: list[dict] = history.get("signals", [])
    eff_date = signal.get("effective_date", "")
    # Deduplicate by effective_date
    if not any(s.get("effective_date") == eff_date for s in signals):
        layers = signal.get("layers", {})
        vol = layers.get("vol_targeting", {})
        vix = layers.get("vix_composite", {})
        macro = layers.get("macro_filter", {})
        record = {
            "generated_at":    signal.get("generated_at", ""),
            "effective_date":  eff_date,
            "combined_scale":  signal.get("combined_scale"),
            "pre_mtf_scale":   signal.get("pre_mtf_scale"),
            "holdings":        signal.get("holdings", {}),
            "risk_regime":     layers.get("momentum_signal", {}).get("risk_regime"),
            "vol_scale":       vol.get("scale"),
            "realized_vol_pct":vol.get("realized_vol_pct"),
            "vol_regime":      vol.get("vol_regime"),
            "vix":             vix.get("vix"),
            "vix_regime":      vix.get("vix_regime"),
            "composite_score": vix.get("composite_score"),
            "composite_regime":vix.get("composite_regime"),
            "fear_score":      vix.get("fear_score"),
            "macro_multiplier":macro.get("multiplier"),
        }
        signals.append(record)
        # Keep last 104 weeks (2 years)
        history["signals"] = signals[-104:]
        history["last_updated"] = datetime.now(timezone.utc).isoformat()
        history["count"] = len(history["signals"])
        HISTORY_FILE.write_text(json.dumps(history, indent=2))
        print(f"[monitor] Appended {eff_date} to signal history ({len(history['signals'])} total)")
    else:
        print(f"[monitor] {eff_date} already in history — skipping append")

    return len(history.get("signals", []))


def get_live_priors() -> dict | None:
    """Return rolling stats from live history if >= MIN_LIVE_WEEKS_FOR_LIVE_BASELINE."""
    if not HISTORY_FILE.exists():
        return None
    try:
        history = json.loads(HISTORY_FILE.read_text())
    except Exception:
        return None
    signals = history.get("signals", [])
    if len(signals) < MIN_LIVE_WEEKS_FOR_LIVE_BASELINE:
        return None

    # Compute rolling mean/sd from live history
    scales  = [s["combined_scale"] for s in signals if s.get("combined_scale") is not None]
    vols    = [s["vol_scale"]       for s in signals if s.get("vol_scale") is not None]
    if len(scales) < 4:
        return None
    return {
        "combined_scale": {"mean": statistics.mean(scales), "sd": statistics.stdev(scales)},
        "vol_scale":      {"mean": statistics.mean(vols),   "sd": statistics.stdev(vols)},
        "count": len(signals),
    }

# ── Anomaly checks ─────────────────────────────────────────────────────────────

def check_signal(signal: dict, baseline: dict, history_count: int) -> tuple[list[str], list[str]]:
    """
    Returns (warnings, critical_flags).
    warnings  = amber — notable deviation, not execution-blocking
    critical  = red   — execution should be reviewed before Monday MOO
    """
    warnings: list[str] = []
    critical: list[str] = []

    # ── 1. Staleness ──────────────────────────────────────────────────────────
    gen_str = signal.get("generated_at", "")
    if gen_str:
        try:
            gen_dt = datetime.fromisoformat(gen_str).replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - gen_dt).days
            if age_days >= SIGNAL_MAX_AGE_DAYS:
                critical.append(f"Signal is {age_days}d old — exceeds {SIGNAL_MAX_AGE_DAYS}d max. Cron may have missed a run.")
            elif age_days >= STALE_WARN_DAYS:
                warnings.append(f"Signal is {age_days}d old — approaching stale threshold ({SIGNAL_MAX_AGE_DAYS}d).")
        except ValueError:
            warnings.append(f"Cannot parse generated_at: {gen_str!r}")

    # ── 2. Required fields present ─────────────────────────────────────────────
    required = ["combined_scale", "holdings", "layers", "effective_date"]
    for field in required:
        if field not in signal or signal[field] is None:
            critical.append(f"Missing required field: {field}")

    layers = signal.get("layers", {})
    layer_keys = ["momentum_signal", "vol_targeting", "vix_composite", "macro_filter"]
    for lk in layer_keys:
        if lk not in layers:
            critical.append(f"Missing signal layer: {lk}")

    # ── 3. Numeric range checks vs bootstrap prior ────────────────────────────
    priors = baseline.get("priors", {})

    # Try live priors first if enough history
    live_p = get_live_priors()
    baseline_source = "bootstrap"
    if live_p:
        priors["combined_scale"] = {**priors.get("combined_scale", {}), **live_p["combined_scale"]}
        priors["vol_scale"]      = {**priors.get("vol_scale", {}),      **live_p["vol_scale"]}
        baseline_source = f"live_history({live_p['count']}w)"

    scale = signal.get("combined_scale")
    vol_layer = layers.get("vol_targeting", {})
    vol_scale = vol_layer.get("scale")

    def z_check(label: str, val: float | None, prior_key: str) -> None:
        if val is None or prior_key not in priors:
            return
        p = priors[prior_key]
        mean, sd = p.get("mean", 0), p.get("sd", 1)
        if sd == 0:
            return
        z = (val - mean) / sd
        # Use pre-computed anomaly bounds where available
        lo = p.get("anomaly_lo", mean - ANOMALY_SIGMA * sd)
        hi = p.get("anomaly_hi", mean + ANOMALY_SIGMA * sd)
        if val < lo or val > hi:
            direction = "LOW" if val < mean else "HIGH"
            warnings.append(
                f"{label}={val:.4f} is {direction} vs {baseline_source} prior "
                f"(mean={mean:.4f}  z={z:+.1f}  bounds=[{lo:.3f},{hi:.3f}])"
            )

    z_check("combined_scale", scale, "combined_scale")
    z_check("vol_scale", vol_scale, "vol_scale")

    # ── 4. Risk/vol regime conflict ────────────────────────────────────────────
    mom = layers.get("momentum_signal", {})
    vix = layers.get("vix_composite", {})
    risk_regime = mom.get("risk_regime", "")
    vix_regime  = vix.get("vix_regime", "")
    vol_regime  = vol_layer.get("vol_regime", "")

    if risk_regime == "RISK_ON" and vix_regime in ("ELEVATED", "EXTREME"):
        warnings.append(
            f"Regime conflict: RISK_ON momentum but VIX_LEVEL={vix_regime}. "
            f"VIX={vix.get('vix',0):.1f}. Review composite_regime before executing."
        )

    if risk_regime == "RISK_ON" and vol_regime == "CRISIS":
        critical.append(
            f"Regime conflict: RISK_ON momentum but RealVolRegime=CRISIS "
            f"(realized_vol={vol_layer.get('realized_vol_pct',0):.1f}%). "
            f"Vol targeting should have reduced scale significantly."
        )

    # ── 5. Week-over-week scale change ──────────────────────────────────────────
    if HISTORY_FILE.exists():
        try:
            hist = json.loads(HISTORY_FILE.read_text())
            sigs = hist.get("signals", [])
            if len(sigs) >= 2 and scale is not None:
                prev_scale = sigs[-2].get("combined_scale")
                if prev_scale and prev_scale > 0:
                    change = abs(scale - prev_scale) / prev_scale
                    if change > WEEK_CHANGE_WARN_PCT:
                        direction = "▲" if scale > prev_scale else "▼"
                        warnings.append(
                            f"Large week-over-week scale change: {direction} "
                            f"{prev_scale:.3f} → {scale:.3f} ({change*100:.0f}% change)"
                        )
        except Exception:
            pass

    # ── 6. Holdings sanity ─────────────────────────────────────────────────────
    holdings = signal.get("holdings", {})
    if holdings:
        total_wt = sum(holdings.values())
        if not (0.95 <= total_wt <= 1.05):
            critical.append(f"Holdings weights sum to {total_wt:.3f} — expected ~1.0")
        if scale is not None and scale > 0.05:
            # In RISK_ON, SHY > 80% is unusual
            shy_wt = holdings.get("SHY", 0)
            if risk_regime == "RISK_ON" and shy_wt > 0.85:
                warnings.append(
                    f"RISK_ON regime but SHY allocation={shy_wt:.1%} — "
                    f"unusually defensive. Verify vol targeting scale is correct."
                )

    # ── 7. Fear score context ──────────────────────────────────────────────────
    fear_score = vix.get("fear_score")
    composite_score = vix.get("composite_score")
    if fear_score is not None and composite_score is not None:
        if fear_score < 0.1 and composite_score > 0.65 and risk_regime == "RISK_ON":
            pass  # complacency + bullish composite = valid RISK_ON — no flag
        elif fear_score > 0.7 and risk_regime == "RISK_ON":
            warnings.append(
                f"High fear_score={fear_score:.3f} with RISK_ON regime. "
                f"Implied vol >> realized vol. Market may be pricing tail risk not in price yet."
            )

    return warnings, critical


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    print(f"[monitor] Strategy C+ signal health check — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    # Load signal
    if not SIGNAL_FILE.exists():
        post_alert(
            "🚨 Strategy C+ Signal MISSING",
            f"`{SIGNAL_FILE.name}` not found. Engine may not have run.",
            ["Signal file does not exist"],
            {},
            color=15158332,
        )
        return 2

    try:
        signal = json.loads(SIGNAL_FILE.read_text())
    except Exception as e:
        post_alert("🚨 Signal File Corrupt", str(e), ["JSON parse failed"], {}, color=15158332)
        return 2

    # Load baseline
    if not BASELINE_FILE.exists():
        post_alert("🚨 Baseline File Missing", f"`{BASELINE_FILE.name}` not found.", ["No baseline"], signal, color=15158332)
        return 3
    try:
        baseline = json.loads(BASELINE_FILE.read_text())
    except Exception as e:
        post_alert("🚨 Baseline File Corrupt", str(e), ["Baseline JSON parse failed"], signal, color=15158332)
        return 3

    # Accumulate history
    history_count = append_to_history(signal)

    # Run checks
    warnings, critical = check_signal(signal, baseline, history_count)

    print(f"[monitor] Checks complete — {len(critical)} critical, {len(warnings)} warnings")
    for f in critical:
        print(f"  [CRITICAL] {f}")
    for f in warnings:
        print(f"  [WARNING]  {f}")

    if critical:
        post_alert(
            "🚨 Strategy C+ Signal — CRITICAL",
            "Execution-blocking issues detected. Review before Monday MOO.",
            critical + warnings,
            signal,
            color=15158332,
        )
        return 1
    elif warnings:
        post_alert(
            "⚠️ Strategy C+ Signal — Anomaly Detected",
            "Signal is within execution bounds but has notable deviations from baseline.",
            warnings,
            signal,
            color=16776960,
        )
        return 1
    else:
        print("[monitor] All checks passed — posting healthy status to Discord.")
        post_healthy(signal, history_count)
        return 0


if __name__ == "__main__":
    sys.exit(main())
