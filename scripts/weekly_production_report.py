#!/usr/bin/env python3
"""JARVIS Weekly Production Report — no_agent cron (Mon 08:30 CT, deliver=all).

The weekly QC + dashboard + attribution + risk + live-monitoring pipeline.

Consumes (all READ-ONLY):
  - Overnight sweep output: engine/backtest/results/iterate_*_overnight.json
    (honest metrics: observed-frequency annualization, CAGR, MC p(edge)).
  - Deep gate_v2 verdict fallback: engine/data/gate_v2_verdicts/MES_trend_rank11*.json
  - Paper ledger: engine/data/jarvis_trader.db (mode=ro) — closed trades + analyst signals.
  - Live monitoring archive: docs/monitoring/daily/YYYY-MM-DD.jsonl (15m snapshots).
  - Risk limit: MAX_DRAWDOWN_PCT from engine/.env.

Produces:
  - docs/reports/weekly/WEEKLY_REPORT_<date>.md   (full report)
  - docs/reports/weekly/WEEKLY_REPORT_<date>.html (standalone performance dashboard)
  - docs/reports/weekly/WEEKLY_REPORT_<date>.json (machine-readable, feeds dashboard widgets)

Prints the full report to stdout — no_agent cron delivers it verbatim.

Design invariants:
  - NEVER writes to the trading DB (mode=ro everywhere).
  - Pure stdlib (runs under any Python 3.9+; no pandas/streamlit RAM weight).
  - Honest metrics only: uses the sweep's annualization_trades_per_year / cagr_pct;
    never quotes inflated 252-annualized Sharpe.
"""

from __future__ import annotations

import html
import importlib.util
import json
import os
import sqlite3
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(r"C:/Users/mattm/ThinkorSwim/jarvis-trader")
DB = REPO / "engine" / "data" / "jarvis_trader.db"
MONITOR_DIR = REPO / "docs" / "monitoring" / "daily"
RESULTS_DIR = REPO / "engine" / "backtest" / "results"
VERDICT_DIR = REPO / "engine" / "data" / "gate_v2_verdicts"
OUT_DIR = REPO / "docs" / "reports" / "weekly"
ENV_FILE = REPO / "engine" / ".env"
ENGINE_URL = "http://127.0.0.1:8010/health"

# Certified live champion: MES SMA trend, fast=50 slow=200, ATR trail 2.0x
# (memory/audit 2026-08-17: "certified live champion 50/200/2.0"; CLAUDE.md
#  notes paper config may run SMA(60,200) 2.0 — report both if sweep has them).
CHAMPION = {"fast": 50, "slow": 200, "atr_trail_mult": 2.0}
VERDICT_PREFERRED = "MES_trend_rank11_honest_dsr.json"
VERDICT_FALLBACK = "MES_trend_rank11.json"

ANALYST_SLOTS = [
    "technical", "news", "social", "fundamental", "corey",
    "pattern_vision", "kronos", "options", "regime_adjust", "other",
]


# ── Helpers ──────────────────────────────────────────────────────────────────


def parse_env(path: Path) -> dict[str, str]:
    """Parse .env key=value lines. Returns dict; caller only reads non-secret keys."""
    out: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def db_connect() -> sqlite3.Connection | None:
    try:
        return sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def engine_probe() -> tuple[str, float | None]:
    """Live /health probe, 4s timeout. Returns (status, latency_ms)."""
    try:
        req = urllib.request.Request(ENGINE_URL, method="GET")
        t0 = datetime.now()
        with urllib.request.urlopen(req, timeout=4) as resp:
            latency = (datetime.now() - t0).total_seconds() * 1000.0
            body = resp.read(200).decode("utf-8", errors="ignore")
            ok = resp.status == 200 and '"ok"' in body.lower()
            return ("UP" if ok else "DOWN", round(latency, 1))
    except Exception:  # noqa: BLE001 - any failure = down for monitoring purposes
        return ("DOWN", None)


def load_monitoring(window_start: date, window_end: date) -> dict:
    """Parse the 15m snapshot JSONL archive for the window."""
    samples: list[dict] = []
    alerts: dict[str, int] = {}
    down_count = 0
    for f in sorted(MONITOR_DIR.glob("*.jsonl")):
        try:
            day = date.fromisoformat(f.stem)
        except ValueError:
            continue
        if not (window_start <= day <= window_end):
            continue
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            samples.append(rec)
            health = rec.get("health")
            if health is None or (isinstance(health, dict) and str(health.get("status", "")).lower() != "ok"):
                down_count += 1
            for a in rec.get("alerts") or []:
                alerts[str(a)] = alerts.get(str(a), 0) + 1
    latest = samples[-1] if samples else {}
    return {
        "n_samples": len(samples),
        "engine_down_samples": down_count,
        "alerts": dict(sorted(alerts.items(), key=lambda kv: -kv[1])),
        "latest": latest,
    }


def latest_sweep_json() -> Path | None:
    sweeps = sorted(RESULTS_DIR.glob("iterate_*_overnight.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return sweeps[0] if sweeps else None


def pick_champion(rows: list[dict]) -> dict | None:
    for r in rows:
        if (r.get("fast") == CHAMPION["fast"] and r.get("slow") == CHAMPION["slow"]
                and r.get("atr_trail_mult") == CHAMPION["atr_trail_mult"]):
            return r
    return None


def best_shortlist(rows: list[dict]) -> dict | None:
    cands = [r for r in rows if (r.get("total_trades") or 0) >= 10 and (r.get("mc_p_positive_edge") or 0) >= 0.6]
    if not cands:
        cands = [r for r in rows if (r.get("total_trades") or 0) >= 10]
    if not cands:
        return None
    return max(cands, key=lambda r: (r.get("mc_p_positive_edge") or 0, r.get("profit_factor") or 0))


def backtest_section() -> dict:
    sweep = latest_sweep_json()
    if sweep:
        try:
            data = json.loads(sweep.read_text(encoding="utf-8"))
            rows = data.get("rows", [])
            champ = pick_champion(rows)
            best = best_shortlist(rows)
            n_bars = data.get("n_bars")
            span_years = data.get("span_years")
            return {
                "source": "overnight_sweep",
                "sweep_file": sweep.name,
                "n_rows": len(rows),
                "n_bars": n_bars,
                "span_years": span_years,
                "champion": champ,
                "best_shortlist": best,
                "verdict_fallback": None,
            }
        except (json.JSONDecodeError, OSError) as exc:
            return {"source": "sweep_error", "error": str(exc), "sweep_file": sweep.name,
                    "champion": None, "best_shortlist": None, "verdict_fallback": None}
    # Deep gate_v2 verdict fallback (certified evidence until first sweep lands)
    for name in (VERDICT_PREFERRED, VERDICT_FALLBACK):
        vf = VERDICT_DIR / name
        if vf.exists():
            try:
                v = json.loads(vf.read_text(encoding="utf-8"))
                metrics = v.get("gate_v2_metrics") or {}
                cp = v.get("champion_params") or {}
                row = {
                    "verdict": v.get("verdict"),
                    "core_verdict": v.get("core_verdict"),
                    "alt_verdict": v.get("alt_verdict"),
                    "gate_v2_metrics": metrics,
                    "champion_params": cp,
                }
                return {"source": "deep_verdict", "sweep_file": None, "n_rows": None,
                        "n_bars": None, "span_years": None, "champion": None,
                        "best_shortlist": None, "verdict_fallback": row}
            except (json.JSONDecodeError, OSError) as exc:
                return {"source": "verdict_error", "error": str(exc), "sweep_file": None,
                        "champion": None, "best_shortlist": None, "verdict_fallback": None}
    return {"source": "pending", "sweep_file": None, "n_rows": None, "n_bars": None,
            "span_years": None, "champion": None, "best_shortlist": None, "verdict_fallback": None}


def forward_evidence(window_start: date, window_end: date) -> dict:
    conn = db_connect()
    if not conn:
        return {"error": "DB unavailable", "rows": [], "total_pnl": 0.0, "n_trades": 0}
    try:
        cur = conn.cursor()
        start_s = window_start.isoformat()
        end_s = window_end.isoformat()
        cur.execute(
            """
            SELECT COALESCE(strategy_id, 'unattributed') AS sid, COUNT(*) AS n,
                   ROUND(SUM(COALESCE(pnl, 0)), 2) AS pnl,
                   ROUND(100.0 * SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS wr
            FROM paper_trades
            WHERE LOWER(status) = 'closed' AND pnl IS NOT NULL
              AND substr(exit_time, 1, 10) >= ? AND substr(exit_time, 1, 10) <= ?
            GROUP BY sid
            ORDER BY pnl DESC
            """,
            (start_s, end_s),
        )
        rows = [{"strategy_id": r[0], "n": r[1], "pnl": float(r[2]), "win_rate": float(r[3] or 0.0)}
                for r in cur.fetchall()]
        # Open positions
        cur.execute("SELECT symbol, side, entry_price, quantity, status FROM paper_trades WHERE LOWER(status) = 'open'")
        open_rows = [{"symbol": r[0], "side": r[1], "entry_price": r[2], "qty": r[3]} for r in cur.fetchall()][:12]
        # risk_pct_used stats in window
        cur.execute(
            """
            SELECT ROUND(AVG(COALESCE(risk_pct_used, 0)), 2), ROUND(MAX(COALESCE(risk_pct_used, 0)), 2)
            FROM paper_trades
            WHERE LOWER(status) = 'closed' AND substr(exit_time, 1, 10) >= ? AND substr(exit_time, 1, 10) <= ?
            """,
            (start_s, end_s),
        )
        risk_row = cur.fetchone()
        conn.close()
        return {
            "rows": rows,
            "total_pnl": round(sum(r["pnl"] for r in rows), 2),
            "n_trades": sum(r["n"] for r in rows),
            "open_positions": open_rows,
            "avg_risk_pct_used": risk_row[0] if risk_row else None,
            "max_risk_pct_used": risk_row[1] if risk_row else None,
        }
    except sqlite3.Error as exc:
        conn.close()
        return {"error": str(exc), "rows": [], "total_pnl": 0.0, "n_trades": 0,
                "open_positions": [], "avg_risk_pct_used": None, "max_risk_pct_used": None}


def attribution_section(window_start: date, window_end: date) -> dict:
    """Reuse the canonical risk_attribution.attribute_window (pure stdlib)."""
    ra = REPO / "engine" / "analytics" / "risk_attribution.py"
    try:
        spec = importlib.util.spec_from_file_location("risk_attribution", ra)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        # dataclasses requires the module registered in sys.modules (it resolves
        # cls.__module__ via sys.modules during class construction).
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        w = mod.attribute_window(window_start, window_end, db_path=str(DB))
        per = {k: v for k, v in w.per_analyst.items() if abs(v.get("total", 0.0)) > 0.001}
        return {
            "days_with_trades": w.days_with_trades,
            "total_pnl": round(w.total_pnl, 2),
            "n_trades": w.n_trades,
            "top_contributor_by_abs": w.top_contributor_by_abs,
            "per_analyst": per,
        }
    except Exception as exc:  # noqa: BLE001 - attribution is best-effort
        return {"error": str(exc)}


def risk_section(bt: dict, fe: dict, attribution: dict, env: dict, monitor: dict) -> dict:
    max_dd_limit = 100.0 * float(env.get("MAX_DRAWDOWN_PCT", 0.20))
    champ = (bt.get("champion") or {}) if bt.get("source") == "overnight_sweep" else None
    bt_max_dd = None
    if champ:
        bt_max_dd = champ.get("max_drawdown_pct")
    elif bt.get("verdict_fallback"):
        gm = bt["verdict_fallback"].get("gate_v2_metrics") or {}
        # Units: mc_95th_dd_pct is already %, mc_95th_dd is a fraction.
        bt_max_dd = gm.get("mc_95th_dd_pct") or gm.get("max_drawdown_pct") or gm.get("max_dd_pct")
        if bt_max_dd is None and gm.get("mc_95th_dd") is not None:
            bt_max_dd = round(100.0 * float(gm["mc_95th_dd"]), 4)

    dd_status = "OK"
    if bt_max_dd is not None:
        ratio = bt_max_dd / max_dd_limit if max_dd_limit else 0.0
        dd_status = "AT LIMIT" if ratio >= 1.0 else ("WARN" if ratio >= 0.9 else "OK")

    # Realized-PnL drawdown proxy from the closed-trade cumulative curve.
    # Dollar-denominated (peak→trough decline); no % because the ledger has no
    # capital base. [ASSUMPTION — proxy only, not the engine's true equity DD.]
    proxy_dd = None
    conn = db_connect()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT pnl FROM paper_trades WHERE LOWER(status)='closed' AND pnl IS NOT NULL ORDER BY id")
            cum = 0.0
            peak = 0.0
            peak_at = None
            trough = None
            trough_at = None
            max_decline = 0.0
            idx = 0
            for (p,) in cur.fetchall():
                idx += 1
                cum += float(p)
                if cum > peak:
                    peak = cum
                    peak_at = idx
                decline = peak - cum
                if decline > max_decline:
                    max_decline = decline
                    trough = cum
                    trough_at = idx
            if max_decline > 0:
                proxy_dd = {
                    "peak_cum_pnl": round(peak, 2),
                    "trough_cum_pnl": round(trough, 2),
                    "decline_usd": round(max_decline, 2),
                    "note": "peak-to-trough decline on cumulative realized PnL (no capital base in ledger)",
                }
        except sqlite3.Error:
            pass
        finally:
            conn.close()

    worst_day = None
    if attribution and "per_analyst" in attribution and "error" not in attribution:
        # daily totals live in attribution.daily; we only kept the summary — recompute worst day
        pass
    # Worst single-day closed PnL in window (direct query)
    conn2 = db_connect()
    worst_day_pnl = None
    if conn2:
        try:
            cur = conn2.cursor()
            cur.execute(
                """
                SELECT substr(exit_time, 1, 10) AS d, ROUND(SUM(COALESCE(pnl, 0)), 2) AS s
                FROM paper_trades
                WHERE LOWER(status)='closed' AND pnl IS NOT NULL
                  AND substr(exit_time, 1, 10) >= ? AND substr(exit_time, 1, 10) <= ?
                GROUP BY d ORDER BY s ASC LIMIT 1
                """,
                (bt_date_start().isoformat(), bt_date_end().isoformat()),
            )
            row = cur.fetchone()
            if row:
                worst_day_pnl = {"day": row[0], "pnl": float(row[1])}
        except sqlite3.Error:
            pass
        finally:
            conn2.close()

    return {
        "max_drawdown_limit_pct": round(max_dd_limit, 1),
        "backtest_max_dd_pct": bt_max_dd,
        "drawdown_status": dd_status,
        "realized_pnl_dd_proxy_pct": proxy_dd,
        "week_pnl": fe.get("total_pnl"),
        "week_trades": fe.get("n_trades"),
        "worst_day": worst_day_pnl,
        "open_positions": fe.get("open_positions", []),
        "avg_risk_pct_used": fe.get("avg_risk_pct_used"),
        "max_risk_pct_used": fe.get("max_risk_pct_used"),
        "engine_down_ratio_pct": round(100.0 * monitor["engine_down_samples"] / monitor["n_samples"], 1)
        if monitor["n_samples"] else None,
    }


def bt_date_start() -> date:
    return date.today() - timedelta(days=6)


def bt_date_end() -> date:
    return date.today()


# ── Rendering ────────────────────────────────────────────────────────────────


def fmt_row(r: dict) -> str:
    if r is None:
        return "n/a"
    keys = ("fast", "slow", "atr_trail_mult")
    return f"{r.get('fast')}/{r.get('slow')}/{r.get('atr_trail_mult')}" if all(k in r for k in keys) else "n/a"


def build_markdown(data: dict) -> str:
    w = data["window"]
    bt = data["backtest"]
    fe = data["forward_evidence"]
    at = data["attribution"]
    rk = data["risk"]
    mo = data["monitoring"]
    eng = data["engine_probe"]
    lines: list[str] = []
    lines.append("📊 JARVIS WEEKLY PRODUCTION REPORT")
    lines.append(f"window: {w['start']} → {w['end']} · generated {w['generated_ct']}")
    lines.append("")

    lines.append("1) BACKTEST (weekly QC)")
    if bt["source"] == "overnight_sweep":
        lines.append(f"   source: overnight sweep `{bt['sweep_file']}` ({bt['n_rows']} combos, "
                     f"{bt['n_bars'] or '?'} bars, {bt['span_years'] or '?'}y)")
        c = bt.get("champion")
        if c:
            lines.append(f"   champion {fmt_row(c)}: {c.get('total_trades')} trades · WR {c.get('win_rate')}% · "
                         f"PF {c.get('profit_factor')} · honest Sharpe {c.get('sharpe_ratio')} "
                         f"({c.get('annualization_trades_per_year')}/yr) · CAGR {c.get('cagr_pct')}% · "
                         f"maxDD {c.get('max_drawdown_pct')}% · MC p(edge) {c.get('mc_p_positive_edge')}")
        b = bt.get("best_shortlist")
        if b and b is not c:
            lines.append(f"   best shortlist {fmt_row(b)}: {b.get('total_trades')} trades · PF {b.get('profit_factor')} · "
                         f"MC p(edge) {b.get('mc_p_positive_edge')}")
        if not c and not b:
            lines.append("   no qualifying rows (trades<10 or p(edge)<0.6)")
    elif bt["source"] == "deep_verdict":
        vf = bt["verdict_fallback"]
        cp = vf.get("champion_params") or {}
        gm = vf.get("gate_v2_metrics") or {}
        lines.append(f"   source: deep gate_v2 verdict → {vf.get('verdict')} "
                     f"(core {vf.get('core_verdict')} / alt {vf.get('alt_verdict')})")
        cp_txt = ", ".join(f"{k}={v}" for k, v in cp.items())
        lines.append(f"   champion params: {cp_txt}")
        lines.append(f"   p(edge) {gm.get('p_edge')} · DSR(honest) {gm.get('dsr_honest_n_trials')} · "
                     f"95th DD {gm.get('mc_95th_dd_pct')}% · WFO {gm.get('wfo_consistency')} · "
                     f"fixed-param PF {gm.get('fixed_params_min_pf')} · OOS trades {gm.get('total_oos_trades')} · "
                     f"cost {gm.get('cost_survives_through')}")
    else:
        lines.append(f"   source: {bt.get('source')} — no backtest data yet "
                     f"(first overnight sweep lands Sat 03:00; report will pick it up)")

    lines.append("")
    lines.append("2) FORWARD EVIDENCE (paper ledger, closed, 7d)")
    if fe.get("error"):
        lines.append(f"   ERROR: {fe['error']}")
    elif fe["rows"]:
        for r in fe["rows"]:
            lines.append(f"   {str(r['strategy_id'])[:32]:<34} n={r['n']:<3} pnl=${r['pnl']:>9.2f}  win%={r['win_rate']}")
        lines.append(f"   {'TOTAL':<34} n={fe['n_trades']:<3} pnl=${fe['total_pnl']:>9.2f}")
    else:
        lines.append("   no closed trades this week")

    lines.append("")
    lines.append("3) ATTRIBUTION (analyst, 7d)")
    if "error" in at:
        lines.append(f"   ERROR: {at['error']}")
    elif at.get("per_analyst"):
        for slot, v in sorted(at["per_analyst"].items(), key=lambda kv: -abs(kv[1]["total"])):
            lines.append(f"   {slot:<16} ${v['total']:>9.2f}  (mean {v['mean']}, max_loss {v['max_loss']})")
        lines.append(f"   top |contributor|: {at['top_contributor_by_abs']} · {at['n_trades']} trades "
                     f"· ${at['total_pnl']} window PnL")
    else:
        lines.append("   no attributable trades (no analyst_signals verdicts in window)")

    lines.append("")
    lines.append("4) RISK")
    lines.append(f"   max drawdown limit: {rk['max_drawdown_limit_pct']}% (engine MAX_DRAWDOWN_PCT)")
    if rk["backtest_max_dd_pct"] is not None:
        lines.append(f"   backtest maxDD: {rk['backtest_max_dd_pct']}% → {rk['drawdown_status']}")
    if rk["realized_pnl_dd_proxy_pct"] is not None:
        p = rk["realized_pnl_dd_proxy_pct"]
        lines.append(f"   realized-PnL DD proxy: peak ${p['peak_cum_pnl']} → trough ${p['trough_cum_pnl']} "
                     f"(−${p['decline_usd']}) [ASSUMPTION — no capital base in ledger]")
    lines.append(f"   week PnL: ${rk['week_pnl']} · trades {rk['week_trades']}")
    if rk["worst_day"]:
        lines.append(f"   worst day: {rk['worst_day']['day']} ${rk['worst_day']['pnl']}")
    if rk["avg_risk_pct_used"] is not None:
        lines.append(f"   risk_pct_used: avg {rk['avg_risk_pct_used']}% / max {rk['max_risk_pct_used']}%")
    if rk["open_positions"]:
        syms = ", ".join(f"{p['symbol']}({p['side']})" for p in rk["open_positions"])
        lines.append(f"   open positions ({len(rk['open_positions'])}): {syms}")
    else:
        lines.append("   open positions: none")

    lines.append("")
    lines.append("5) LIVE MONITORING")
    lines.append(f"   engine: {eng['status']}" + (f" ({eng['latency_ms']}ms)" if eng["latency_ms"] else "") +
                 (" ⚠" if eng["status"] == "DOWN" else ""))
    if mo["n_samples"]:
        lines.append(f"   week: {mo['n_samples']} snapshots · engine-down {mo['engine_down_samples']} "
                     f"({rk['engine_down_ratio_pct']}%)")
        if mo["alerts"]:
            top = ", ".join(f"{k}×{v}" for k, v in list(mo["alerts"].items())[:5])
            lines.append(f"   alerts: {top}")
    else:
        lines.append("   week: no monitoring snapshots on file")
    return "\n".join(lines)


def build_html(data: dict) -> str:
    bt = data["backtest"]
    fe = data["forward_evidence"]
    at = data["attribution"]
    rk = data["risk"]
    mo = data["monitoring"]
    eng = data["engine_probe"]
    w = data["window"]

    def esc(x) -> str:
        return html.escape(str(x))

    fe_rows = "".join(
        f"<tr><td>{esc(r['strategy_id'])}</td><td>{r['n']}</td><td>{r['pnl']:.2f}</td>"
        f"<td>{r['win_rate']}</td></tr>" for r in fe.get("rows", [])
    )
    at_rows = "".join(
        f"<tr><td>{esc(k)}</td><td>{v['total']:.2f}</td><td>{v['mean']:.2f}</td><td>{v['max_loss']:.2f}</td></tr>"
        for k, v in sorted(at.get("per_analyst", {}).items(), key=lambda kv: -abs(kv[1]["total"]))
    )
    dd_color = {"OK": "#0a7d33", "WARN": "#b7791f", "AT LIMIT": "#b91c1c"}.get(rk["drawdown_status"], "#333")
    dd_proxy_txt = "n/a"
    if isinstance(rk.get("realized_pnl_dd_proxy_pct"), dict):
        p = rk["realized_pnl_dd_proxy_pct"]
        dd_proxy_txt = f"peak ${p['peak_cum_pnl']} → trough ${p['trough_cum_pnl']} (−${p['decline_usd']})"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>JARVIS Weekly Report {esc(w['end'])}</title>
<style>
 body{{font-family:system-ui,Segoe UI,Roboto,sans-serif;margin:2rem auto;max-width:900px;color:#1a1a1a;background:#fafafa}}
 h1{{font-size:1.4rem}} h2{{font-size:1.05rem;border-bottom:2px solid #ddd;padding-bottom:.25rem;margin-top:1.6rem}}
 table{{border-collapse:collapse;width:100%;margin:.5rem 0}} th,td{{border:1px solid #ccc;padding:.35rem .6rem;text-align:left;font-size:.9rem}}
 th{{background:#eee}} .badge{{display:inline-block;padding:.15rem .6rem;border-radius:999px;color:#fff;font-size:.8rem;background:{dd_color}}}
 .ok{{color:#0a7d33;font-weight:600}} .down{{color:#b91c1c;font-weight:600}}
 .muted{{color:#666;font-size:.85rem}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:.6rem;margin:.6rem 0}}
 .card{{background:#fff;border:1px solid #ddd;border-radius:8px;padding:.7rem .9rem}}
 .card b{{display:block;font-size:.78rem;text-transform:uppercase;color:#666}}
 .card span{{font-size:1.15rem;font-weight:600}}
</style></head><body>
<h1>📊 JARVIS Weekly Production Report</h1>
<p class="muted">window {esc(w['start'])} → {esc(w['end'])} · generated {esc(w['generated_ct'])} · source {esc(bt['source'])}</p>
<div class="grid">
 <div class="card"><b>Engine</b><span class="{'ok' if eng['status']=='UP' else 'down'}">{esc(eng['status'])}</span></div>
 <div class="card"><b>Week PnL</b><span>${esc(rk['week_pnl'])}</span></div>
 <div class="card"><b>Trades</b><span>{esc(rk['week_trades'])}</span></div>
 <div class="card"><b>Backtest maxDD</b><span>{esc(rk['backtest_max_dd_pct'])}%</span></div>
 <div class="card"><b>DD limit</b><span>{esc(rk['max_drawdown_limit_pct'])}% <span class="badge">{esc(rk['drawdown_status'])}</span></span></div>
 <div class="card"><b>Snapshots</b><span>{esc(mo['n_samples'])} ({esc(rk['engine_down_ratio_pct'])}% down)</span></div>
</div>
<h2>1 · Backtest (weekly QC)</h2>
<p>{esc(bt['source'])}</p>
<pre>{esc(json.dumps((bt.get('champion') or bt.get('verdict_fallback') or {}), indent=1, default=str)[:1600])}</pre>
<h2>2 · Forward evidence (closed paper trades, 7d)</h2>
<table><tr><th>strategy</th><th>n</th><th>pnl $</th><th>win%</th></tr>{fe_rows}
<tr><th>TOTAL</th><th>{fe['n_trades']}</th><th>{fe['total_pnl']:.2f}</th><th></th></tr></table>
<h2>3 · Attribution (analyst, 7d)</h2>
<table><tr><th>analyst</th><th>total $</th><th>mean</th><th>max_loss</th></tr>{at_rows}</table>
<h2>4 · Risk</h2>
<table><tr><th>item</th><th>value</th></tr>
<tr><td>Backtest maxDD</td><td>{esc(rk['backtest_max_dd_pct'])}% vs limit {esc(rk['max_drawdown_limit_pct'])}% → <span class="badge">{esc(rk['drawdown_status'])}</span></td></tr>
<tr><td>Realized-PnL DD proxy</td><td>{esc(dd_proxy_txt)} <span class="muted">[ASSUMPTION — no capital base in ledger]</span></td></tr>
<tr><td>Worst day</td><td>{esc(rk['worst_day'])}</td></tr>
<tr><td>risk_pct_used</td><td>avg {esc(rk['avg_risk_pct_used'])}% / max {esc(rk['max_risk_pct_used'])}%</td></tr>
<tr><td>Open positions</td><td>{esc(len(rk['open_positions']))} — {esc(', '.join(p['symbol'] for p in rk['open_positions']))}</td></tr></table>
<h2>5 · Live monitoring (7d)</h2>
<p>engine {esc(eng['status'])} · {esc(mo['n_samples'])} snapshots · down {esc(mo['engine_down_samples'])} ({esc(rk['engine_down_ratio_pct'])}%)</p>
<p class="muted">alerts: {esc(mo['alerts'])}</p>
</body></html>
"""


def main() -> int:
    days = 7
    if len(sys.argv) > 1 and sys.argv[1].startswith("--days="):
        try:
            days = max(1, int(sys.argv[1].split("=", 1)[1]))
        except ValueError:
            pass
    end = date.today()
    start = end - timedelta(days=days - 1)

    env = parse_env(ENV_FILE)
    monitor = load_monitoring(start, end)
    probe = engine_probe()
    bt = backtest_section()
    fe = forward_evidence(start, end)
    at = attribution_section(start, end)
    rk = risk_section(bt, fe, at, env, monitor)

    data = {
        "window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": days,
            "generated_ct": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
        "engine_probe": {"status": probe[0], "latency_ms": probe[1]},
        "monitoring": monitor,
        "backtest": bt,
        "forward_evidence": fe,
        "attribution": at,
        "risk": rk,
    }

    md = build_markdown(data)
    print(md)
    print("\n[weekly-report] artifacts: see docs/reports/weekly/WEEKLY_REPORT_%s.{md,html,json}" % end.isoformat())

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = end.isoformat()
    (OUT_DIR / f"WEEKLY_REPORT_{stamp}.md").write_text(md + "\n", encoding="utf-8")
    (OUT_DIR / f"WEEKLY_REPORT_{stamp}.json").write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8")
    (OUT_DIR / f"WEEKLY_REPORT_{stamp}.html").write_text(build_html(data), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
