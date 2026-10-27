"""
Strategy C+ Signal Monitor (v2 — 2026-09-27/28 false-positive audit)
======================================================================
Modes
  --mode check      Every 6h. Posts to Discord ONLY when the issue set changes
                    (fingerprint dedupe via output/monitor_state.json). Silent when healthy.
  --mode premarket  Sunday evening. Always posts one digest: freshness vs the
                    most recent Friday, week-over-week drift with per-layer
                    attribution, and any active flags. This is the "before
                    Monday open" gate.

Trigger rules (fire rates replayed on the production v1 engine's same-Friday signal
values, 498 weekly bars 2017-03 → 2026-09; see docs/2026-09-28_strategy_c_benchmark_study.md):
  T1 RISK_ON & VIX>=30              WARN      (~1.7/yr)
  T2 RISK_ON & RealVol CRISIS       CRITICAL only if vol targeting FAILED to compress
                                    scale (> 1.25x target/RV): 0 weeks in history.
                                    Otherwise INFO (~2.5/yr).
  T3 RISK_ON & SHY>85%              INFO (redundant with T2 compression)
  T4 RISK_ON & fear_score>0.7       REMOVED (fired 42% of weeks; median fear 0.71 —
                                    VIX > realized vol is the normal state)
  T5 week-over-week |Δscale|        >= p97.5 of history (0.451)  ~1.4/yr
                                    (old rel>30% rule fired ~16/yr)
  T6 scale out of band              < p2.5 or > p97.5 of full 498w history  ~1.4/yr
                                    (a 2y window fired ~6.8/yr). Live history replaces
                                    the band only at >= 104 weeks, percentile-based.
Exit codes: 0 healthy/info only · 1 warning · 2 critical/stale · 3 config error ·
            4 alert delivery failed · 5 monitor crashed
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

OUT = Path(__file__).parent / "output"
SIGNAL_FILE = OUT / "strategy_c_plus_live_signal.json"
BASELINE_FILE = OUT / "signal_baseline.json"
HISTORY_FILE = OUT / "signal_history.json"
STATE_FILE = OUT / "monitor_state.json"

DEFAULT_VOL_TARGET_PCT = (
    8.0  # v1 live config; read per-signal from layers.vol_targeting.vol_target_pct
)
SCALE_FAIL_TOLERANCE = 1.25  # T2: scale > 1.25x (target/realized) = targeting failed
WOW_ABS_DEFAULT = 0.45  # T5: p97.5 of |Δscale| on 498w v1 history (baseline overrides)
MIN_LIVE_WEEKS = 104  # live history replaces the backtest band only after ~2y
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")

RED, AMBER, GREEN, BLUE = 15158332, 16776960, 3066993, 3447003


# ── helpers ──────────────────────────────────────────────────────────────────
def _load(p: Path, default: Any) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def last_friday(today: date | None = None) -> date:
    """Most recent Friday on or before `today` (calendar only; used for week keys)."""
    t = today or datetime.now(timezone.utc).date()
    return t - timedelta(days=(t.weekday() - 4) % 7)


# Generation runs Sat 01:30 UTC (yfinance `end` is exclusive, so a Friday-dated
# run would omit Friday's bar). Allow 90 min for the run to land.
GENERATION_READY_UTC = (3, 0)  # Saturday


def expected_signal_friday(now: datetime | None = None) -> date:
    """The Friday whose signal should exist at `now`.

    Until this week's generation has landed (Saturday 03:00 UTC), the valid
    signal is still last week's — otherwise every Friday check would raise a
    false CRITICAL.
    """
    n = now or datetime.now(timezone.utc)
    lf = last_friday(n.date())
    ready = n.date() > lf + timedelta(days=1) or (
        n.date() == lf + timedelta(days=1) and (n.hour, n.minute) >= GENERATION_READY_UTC
    )
    if not ready:
        lf -= timedelta(days=7)
    return lf


def post_discord(embed: dict) -> bool:
    """Returns True only if Discord accepted the message (or no webhook is configured)."""
    if not DISCORD_WEBHOOK:
        print("[monitor] DISCORD_WEBHOOK_URL not set — printing embed instead")
        print(json.dumps(embed, indent=1)[:3000])
        return True
    req = urllib.request.Request(
        DISCORD_WEBHOOK,
        data=json.dumps({"embeds": [embed]}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "jarvis-signal-monitor"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return 200 <= r.status < 300
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[monitor] Discord post failed: {e}")
        return False


def flat(sig: dict) -> dict:
    L = sig.get("layers", {})
    vol, vix = L.get("vol_targeting", {}), L.get("vix_composite", {})
    try:
        wk = last_friday(date.fromisoformat(str(sig.get("effective_date"))[:10])).isoformat()
    except Exception:
        wk = None
    return {
        "week_of": wk,
        "generated_at": sig.get("generated_at"),
        "effective_date": sig.get("effective_date"),
        "combined_scale": sig.get("combined_scale"),
        "pre_mtf_scale": sig.get("pre_mtf_scale"),
        "holdings": sig.get("holdings", {}),
        "risk_regime": L.get("momentum_signal", {}).get("risk_regime"),
        "vol_scale": vol.get("scale"),
        "realized_vol_pct": vol.get("realized_vol_pct"),
        "vol_regime": vol.get("vol_regime"),
        "vix": vix.get("vix"),
        "vix_regime": vix.get("vix_regime"),
        "composite_regime": vix.get("composite_regime"),
        "vix_multiplier": vix.get("position_multiplier"),
        "fear_score": vix.get("fear_score"),
        "macro_multiplier": L.get("macro_filter", {}).get("multiplier"),
        "mtf_scale": L.get("mtf_signal", {}).get("mtf_scale"),
    }


def append_history(sig: dict) -> list[dict]:
    hist = _load(HISTORY_FILE, {"signals": []})
    sigs = hist.get("signals", [])
    rec = flat(sig)
    for s in sigs:  # back-fill week_of on legacy rows
        if not s.get("week_of") and s.get("effective_date"):
            s["week_of"] = last_friday(date.fromisoformat(s["effective_date"][:10])).isoformat()
    if rec["week_of"]:
        sigs = [s for s in sigs if s.get("week_of") != rec["week_of"]] + [
            rec
        ]  # latest run per week wins
        sigs.sort(key=lambda s: s.get("week_of") or "")
        hist = {
            "signals": sigs[-104:],
            "count": len(sigs[-104:]),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        HISTORY_FILE.write_text(json.dumps(hist, indent=2))
    return hist.get("signals", sigs)


def scale_bounds(baseline: dict, history: list[dict]) -> tuple[float, float, str]:
    # The live signal is produced by the same code as the backtest, so the
    # 498-week backtest distribution is the right reference. A mean±2σ band from
    # a few live weeks understates dispersion and would itself raise false alarms.
    live = sorted(
        s["combined_scale"] for s in history if isinstance(s.get("combined_scale"), (int, float))
    )
    if len(live) >= MIN_LIVE_WEEKS:
        lo_i, hi_i = int(0.025 * (len(live) - 1)), int(0.975 * (len(live) - 1))
        return live[lo_i], live[hi_i], f"live({len(live)}w)"
    p = baseline.get("priors", {}).get("combined_scale", {})
    return p.get("p2_5", 0.08), p.get("p97_5", 1.1), "v1-backtest-498w"


# ── checks ───────────────────────────────────────────────────────────────────
def evaluate(sig: dict, baseline: dict, history: list[dict], mode: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"critical": [], "warning": [], "info": []}
    f = flat(sig)

    # Required structure
    for k in ("combined_scale", "holdings", "effective_date"):
        if f.get(k) in (None, {}, ""):
            out["critical"].append(f"Missing field: {k}")
    for lk in ("momentum_signal", "vol_targeting", "vix_composite"):
        if lk not in sig.get("layers", {}):
            out["critical"].append(f"Missing layer: {lk}")

    # Freshness — the signal must be for the most recent Friday
    lf = expected_signal_friday()
    try:
        eff = date.fromisoformat(str(f["week_of"]))
        lag_days = (lf - eff).days
        if lag_days >= 7:
            out["critical"].append(
                f"Signal is for {eff} — expected {lf}. Friday generation did not run ({lag_days}d behind)."
            )
        elif lag_days < 0:
            out["critical"].append(
                f"Signal is for {eff} — in the future vs expected {lf}. Clock or date bug."
            )
        elif mode == "premarket" and lag_days > 0:
            out["warning"].append(f"Signal effective {eff}, last Friday {lf}.")
    except Exception:
        out["critical"].append(f"Unparseable effective_date: {f.get('effective_date')!r}")

    scale, rv, regime = (
        f.get("combined_scale"),
        f.get("realized_vol_pct"),
        f.get("risk_regime") or "",
    )
    risk_on = regime.startswith("RISK_ON")

    # Holdings sanity
    h = f.get("holdings") or {}
    if h:
        bad = {k: v for k, v in h.items() if not isinstance(v, (int, float)) or not 0.0 <= v <= 1.0}
        if bad:
            out["critical"].append(f"Allocation weights out of range [0, 1]: {bad}")
        tot = sum(v for v in h.values() if isinstance(v, (int, float)))
        if not 0.98 <= tot <= 1.02:
            out["critical"].append(f"Holdings sum to {tot:.3f} (expected 1.0)")

    # T1
    if risk_on and f.get("vix_regime") in ("ELEVATED", "EXTREME"):
        out["warning"].append(
            f"RISK_ON with VIX {f.get('vix', 0):.1f} [{f['vix_regime']}] — review composite={f.get('composite_regime')}"
        )

    # T2 — only a problem if vol targeting did NOT compress
    if (
        risk_on
        and f.get("vol_regime") == "CRISIS"
        and isinstance(rv, (int, float))
        and rv > 0
        and isinstance(scale, (int, float))
    ):
        vt = (
            sig.get("layers", {}).get("vol_targeting", {}).get("vol_target_pct")
            or DEFAULT_VOL_TARGET_PCT
        )
        expected_max = min(1.0, vt / rv) * SCALE_FAIL_TOLERANCE
        # Judge the vol layer itself: combined_scale also carries VIX/macro/MTF
        # multipliers, which can mask a failed vol layer.
        vol_s = f.get("vol_scale")
        judged = vol_s if isinstance(vol_s, (int, float)) else scale
        if judged > expected_max:
            out["critical"].append(
                f"RealVol CRISIS ({rv:.1f}%) but vol scale {judged:.3f} > {expected_max:.3f} — vol targeting not compressing"
            )
        else:
            out["info"].append(
                f"RealVol CRISIS ({rv:.1f}%) — scale correctly compressed to {scale:.3f}"
            )

    # T3 (info)
    if risk_on and h.get("SHY", 0) > 0.85:
        out["info"].append(f"RISK_ON but SHY {h['SHY']:.0%} — defensive via scale compression")

    # T5 — week-over-week
    prev = [s for s in history if (s.get("week_of") or "") < (f.get("week_of") or "")]
    if (
        prev
        and isinstance(scale, (int, float))
        and isinstance(prev[-1].get("combined_scale"), (int, float))
    ):
        ps = prev[-1]["combined_scale"]
        d = scale - ps
        wow_abs = baseline.get("wow_abs_threshold") or WOW_ABS_DEFAULT
        if abs(d) >= wow_abs:
            out["warning"].append(
                f"Scale {'▲' if d > 0 else '▼'} {ps:.3f} → {scale:.3f} (Δ{d:+.3f})"
            )

    # T6 — distribution bounds
    lo, hi, src = scale_bounds(baseline, history)
    if isinstance(scale, (int, float)) and not lo <= scale <= hi:
        out["warning"].append(f"Scale {scale:.3f} outside {src} 95% band [{lo:.3f}, {hi:.3f}]")
    return out


def drift_lines(sig: dict, history: list[dict]) -> list[str]:
    f = flat(sig)
    prev = [s for s in history if (s.get("week_of") or "") < (f.get("week_of") or "")]
    if not prev:
        return ["No prior week in live history — drift unavailable (history accumulates weekly)."]
    p = prev[-1]
    lines = [f"week {p.get('week_of')} → {f.get('week_of')}:"]
    for k, lbl in (
        ("combined_scale", "scale"),
        ("vol_scale", "vol"),
        ("vix_multiplier", "vix×"),
        ("macro_multiplier", "macro×"),
        ("mtf_scale", "mtf×"),
        ("realized_vol_pct", "RV%"),
        ("vix", "VIX"),
    ):
        a, b = p.get(k), f.get(k)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            lines.append(f"{lbl:7s} {a:.3f} → {b:.3f} ({b - a:+.3f})")
    ph, ch = p.get("holdings") or {}, f.get("holdings") or {}
    added, removed = sorted(set(ch) - set(ph)), sorted(set(ph) - set(ch))
    if added or removed:
        lines.append(f"holdings: +{','.join(added) or '-'} / -{','.join(removed) or '-'}")
    if p.get("risk_regime") != f.get("risk_regime"):
        lines.append(f"regime: {p.get('risk_regime')} → {f.get('risk_regime')}")
    return lines


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["check", "premarket"], default="check")
    mode = ap.parse_args().mode
    now = datetime.now(timezone.utc)

    if os.environ.get("GITHUB_ACTIONS") == "true" and not DISCORD_WEBHOOK:
        # In CI a missing/renamed secret must not look like a delivered alert.
        print("::error::DISCORD_WEBHOOK_URL secret is not configured — alerts cannot be delivered")
        return 3

    sig = _load(SIGNAL_FILE, None)
    if not sig:
        post_discord(
            {
                "title": "🚨 Strategy C+ signal missing/corrupt",
                "color": RED,
                "description": f"`{SIGNAL_FILE.name}` unreadable.",
                "timestamp": now.isoformat(),
            }
        )
        return 2
    baseline = _load(BASELINE_FILE, None)
    if not baseline:
        post_discord(
            {"title": "🚨 Signal baseline missing", "color": RED, "timestamp": now.isoformat()}
        )
        return 3

    history = append_history(sig)
    res = evaluate(sig, baseline, history, mode)
    sev = "critical" if res["critical"] else "warning" if res["warning"] else "ok"
    for k in ("critical", "warning", "info"):
        for m in res[k]:
            print(f"[{k.upper()}] {m}")

    f = flat(sig)
    hold = "  ".join(
        f"{k} {v:.1%}" for k, v in sorted((f["holdings"] or {}).items(), key=lambda x: -x[1])
    )
    flags = (
        "\n".join(
            [f"🔴 {m}" for m in res["critical"]]
            + [f"🟡 {m}" for m in res["warning"]]
            + [f"ℹ️ {m}" for m in res["info"]]
        )
        or "none"
    )

    if mode == "premarket":
        title = {
            "critical": "🚨 Pre-Market Gate — DO NOT EXECUTE",
            "warning": "⚠️ Pre-Market Gate — review before open",
            "ok": "✅ Pre-Market Gate — clear to execute",
        }[sev]
        pm_delivered = post_discord(
            {
                "title": f"{title} ({f.get('effective_date')})",
                "color": {"critical": RED, "warning": AMBER, "ok": GREEN}[sev],
                "fields": [
                    {
                        "name": "Target",
                        "value": f"scale {f['combined_scale']:.3f} · {hold}"[:1024],
                        "inline": False,
                    },
                    {
                        "name": "Drift",
                        "value": "```\n" + "\n".join(drift_lines(sig, history))[:990] + "\n```",
                        "inline": False,
                    },
                    {"name": "Flags", "value": flags[:1024], "inline": False},
                    {
                        "name": "Regime",
                        "value": f"{f.get('risk_regime')} · VIX {f.get('vix')} [{f.get('vix_regime')}] · RV {f.get('realized_vol_pct')}% [{f.get('vol_regime')}]",
                        "inline": False,
                    },
                ],
                "footer": {
                    "text": f"Jarvis · Strategy C+ pre-market · live history {len(history)}w"
                },
                "timestamp": now.isoformat(),
            }
        )
        if not pm_delivered:
            print("[monitor] pre-market gate NOT delivered to Discord")
            return 4
    else:
        fp = hashlib.sha1(
            json.dumps([f.get("effective_date"), res["critical"], res["warning"]]).encode()
        ).hexdigest()[:12]
        state = _load(STATE_FILE, {})
        delivered = True
        if sev != "ok" and state.get("last_fingerprint") != fp:
            delivered = post_discord(
                {
                    "title": f"{'🚨' if sev == 'critical' else '⚠️'} Strategy C+ signal {sev.upper()}",
                    "color": RED if sev == "critical" else AMBER,
                    "description": flags[:4000],
                    "footer": {"text": "Jarvis · 6h check · posts only on change"},
                    "timestamp": now.isoformat(),
                }
            )
        elif sev == "ok" and state.get("last_severity") not in (None, "ok"):
            delivered = post_discord(
                {
                    "title": "✅ Strategy C+ signal recovered",
                    "color": GREEN,
                    "timestamp": now.isoformat(),
                }
            )
        # Only advance the dedupe fingerprint once the alert was actually delivered;
        # otherwise the next check retries instead of suppressing an unsent alert.
        if delivered:
            STATE_FILE.write_text(
                json.dumps(
                    {"last_fingerprint": fp, "last_severity": sev, "checked_at": now.isoformat()},
                    indent=2,
                )
            )
        else:
            print("[monitor] alert not delivered — fingerprint not advanced (will retry)")
            return 4

    return {"critical": 2, "warning": 1, "ok": 0}[sev]


def run() -> int:
    """Entry point: uncaught exceptions exit 5 so a crash is never read as a warning (1)."""
    try:
        return main()
    except SystemExit:
        raise
    except Exception:
        import traceback

        traceback.print_exc()
        return 5


if __name__ == "__main__":
    sys.exit(run())
