#!/usr/bin/env python3
"""Build persistent ES (ESZ26 / ESZ6) context markdown for overnight / pre-NFP reads.

Writes:
  /workspace/tape/context/es-context-latest.md
  /workspace/tape/context/es-context-YYYYMMDD-HHMM.md

Read-only. Never places orders. Never touches IB engine processes beyond optional
read-only historical pulls when run ON AmoSZN with Gateway on 127.0.0.1:4001.

Typical use:
  # On the box (uses raw/ caches + live web ZeroGEX/Yahoo/FF):
  python3 /workspace/tape/context/build_context.py

  # On AmoSZN (refreshes IB + tick recorder into raw/, then same render):
  python build_context.py --pull-ib

Matt approved 2026-11-05 22:48 CT.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Box layout mirrors /workspace/tape; override with TAPE_ROOT. Defaults to scripts/tape in the repo.
TAPE_ROOT = Path(os.environ.get("TAPE_ROOT") or Path(__file__).resolve().parents[1])

CT = ZoneInfo("America/Chicago")
ROOT = (TAPE_ROOT / "context")
RAW = ROOT / "raw"
STATE = (TAPE_ROOT / "state")
GEX_PULL = (TAPE_ROOT / "gex_pull.py")

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def now_ct() -> datetime:
    return datetime.now(CT)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def fetch(url: str, timeout: float = 30.0) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (es-context)", "Cache-Control": "no-cache"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def fmt_num(x, nd=2):
    if x is None:
        return "unavailable"
    if isinstance(x, float):
        return f"{x:.{nd}f}".rstrip("0").rstrip(".") if nd else str(x)
    return str(x)


def age_minutes(asof_iso: str | None, pulled: datetime) -> int | None:
    if not asof_iso:
        return None
    try:
        asof = datetime.fromisoformat(asof_iso.replace("Z", "+00:00"))
        if asof.tzinfo is None:
            asof = asof.replace(tzinfo=CT)
        return int((pulled.astimezone(asof.tzinfo) - asof).total_seconds() // 60)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# optional AmoSZN pulls
# ---------------------------------------------------------------------------

def pull_ib_and_ticks(client_ids=(111, 112, 113, 114)) -> dict:
    """Read-only IB Gateway + tick recorder. Run on AmoSZN only."""
    failures = []
    try:
        from ib_insync import IB, Future, Index  # type: ignore
    except Exception as e:
        return {"ok": False, "error": f"ib_insync missing: {e}"}

    ib = IB()
    connected = None
    err = None
    for cid in client_ids:
        try:
            ib.connect("127.0.0.1", 4001, clientId=cid, readonly=True, timeout=12)
            connected = cid
            break
        except Exception as e:
            err = e
    if not connected:
        return {"ok": False, "error": f"IB connect failed: {err}"}

    es = Future(symbol="ES", lastTradeDateOrContractMonth="202612", exchange="CME", currency="USD")
    ib.qualifyContracts(es)

    def to_ct(dt):
        try:
            return dt.astimezone(CT) if getattr(dt, "tzinfo", None) else dt.replace(tzinfo=CT)
        except Exception:
            return dt

    # daily RTH
    dailies = ib.reqHistoricalData(
        es, "", "1 M", "1 day", "TRADES", useRTH=True, formatDate=1
    )
    daily_rows = [
        {"date": str(b.date), "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": int(b.volume)}
        for b in dailies[-12:]
    ]

    bars5 = ib.reqHistoricalData(
        es, "", "5 D", "5 mins", "TRADES", useRTH=True, formatDate=1
    )
    sessions: dict[str, list] = defaultdict(list)
    for b in bars5:
        day = to_ct(b.date).strftime("%Y-%m-%d")
        sessions[day].append(b)
    session_out = []
    for day in sorted(sessions.keys())[-6:]:
        bs = sessions[day]
        buckets: dict[float, float] = defaultdict(float)
        for x in bs:
            typ = (x.high + x.low + x.close) / 3
            buckets[round(typ * 4) / 4] += x.volume
        poc = max(buckets, key=buckets.get) if buckets else None
        tot = sum(buckets.values()) or 1
        ordered = sorted(buckets.items(), key=lambda kv: -kv[1])
        acc = 0.0
        va: set[float] = set()
        for px, vol in ordered:
            va.add(px)
            acc += vol
            if acc / tot >= 0.7:
                break
        session_out.append(
            {
                "date": day,
                "open": bs[0].open,
                "high": max(x.high for x in bs),
                "low": min(x.low for x in bs),
                "close": bs[-1].close,
                "poc": poc,
                "vah": max(va) if va else None,
                "val": min(va) if va else None,
                "n_bars": len(bs),
                "volume": int(sum(x.volume for x in bs)),
            }
        )

    bars_eth = ib.reqHistoricalData(
        es, "", "2 D", "5 mins", "TRADES", useRTH=False, formatDate=1
    )
    # tonight Globex from prior 17:00
    n = now_ct()
    # if before 17:00, Globex started yesterday 17:00; if after, today 17:00
    if n.hour >= 17:
        start = n.replace(hour=17, minute=0, second=0, microsecond=0)
    else:
        start = (n - timedelta(days=1)).replace(hour=17, minute=0, second=0, microsecond=0)
    eth = [(to_ct(b.date), b) for b in bars_eth if to_ct(b.date) >= start]
    globex = None
    if eth:
        num = sum(b.volume * (b.high + b.low + b.close) / 3 for _, b in eth)
        den = sum(b.volume for _, b in eth) or 1
        buckets = defaultdict(float)
        for _, b in eth:
            buckets[round(((b.high + b.low + b.close) / 3) * 4) / 4] += b.volume
        globex = {
            "onh": max(b.high for _, b in eth),
            "onl": min(b.low for _, b in eth),
            "last": eth[-1][1].close,
            "vwap": round(num / den, 2),
            "poc": max(buckets, key=buckets.get) if buckets else None,
            "n_bars": len(eth),
            "asof": eth[-1][0].isoformat(),
            "window_start": start.isoformat(),
        }

    # VIX spot daily
    vix = Index("VIX", "CBOE")
    ib.qualifyContracts(vix)
    vix_d = ib.reqHistoricalData(vix, "", "1 M", "1 day", "TRADES", useRTH=True, formatDate=1)
    vix_rows = [
        {"date": str(b.date), "o": b.open, "h": b.high, "l": b.low, "c": b.close}
        for b in vix_d[-10:]
    ]

    # VX monthly front two
    vx_rows = []
    try:
        cds = ib.reqContractDetails(
            Future(symbol="VIX", exchange="CFE", currency="USD", tradingClass="VX")
        )
        monthly = sorted(
            [cd for cd in cds if cd.contract.tradingClass == "VX"],
            key=lambda c: c.contract.lastTradeDateOrContractMonth,
        )
        for cd in monthly[:2]:
            c = cd.contract
            ib.qualifyContracts(c)
            b = ib.reqHistoricalData(c, "", "5 D", "1 day", "TRADES", useRTH=True, formatDate=1)
            last = b[-1] if b else None
            vx_rows.append(
                {
                    "local": c.localSymbol,
                    "expiry": c.lastTradeDateOrContractMonth,
                    "last": None if not last else last.close,
                    "date": None if not last else str(last.date),
                }
            )
    except Exception as e:
        failures.append(f"VX futures: {e}")

    # overnight extremes preceding last 6 RTH days
    bars10 = ib.reqHistoricalData(
        es, "", "10 D", "5 mins", "TRADES", useRTH=False, formatDate=1
    )
    rth_dates = sorted(sessions.keys())[-6:]
    ovn = {}
    for d in rth_dates:
        day = datetime.fromisoformat(d).date()
        start_ovn = datetime(day.year, day.month, day.day, tzinfo=CT) - timedelta(hours=7)
        end_ovn = datetime(day.year, day.month, day.day, 8, 30, tzinfo=CT)
        window = [b for b in bars10 if start_ovn <= to_ct(b.date) < end_ovn]
        if window:
            ovn[d] = {
                "onh": max(b.high for b in window),
                "onl": min(b.low for b in window),
                "n": len(window),
            }
        else:
            ovn[d] = {"onh": None, "onl": None, "n": 0}

    # recent NFP Fridays
    nfp_dates = ["2026-10-02", "2026-09-04", "2026-08-07", "2026-07-02", "2026-06-05", "2026-05-01"]
    nfp_out = []
    for d in nfp_dates:
        end = d.replace("-", "") + " 16:00:00 US/Central"
        try:
            beth = ib.reqHistoricalData(
                es, end, "1 D", "5 mins", "TRADES", useRTH=False, formatDate=1
            )
        except Exception as e:
            nfp_out.append({"date": d, "error": str(e)})
            continue
        if not beth:
            nfp_out.append({"date": d, "error": "no bars"})
            continue

        def find(hh, mm):
            for b in beth:
                t = to_ct(b.date)
                if t.hour == hh and t.minute == mm:
                    return b
            return None

        b730, b800 = find(7, 30), find(8, 0)
        rth = [
            b
            for b in beth
            if (to_ct(b.date).hour > 8 or (to_ct(b.date).hour == 8 and to_ct(b.date).minute >= 30))
            and (to_ct(b.date).hour < 15 or (to_ct(b.date).hour == 15 and to_ct(b.date).minute == 0))
        ]
        close_bar = rth[-1] if rth else None
        px730 = b730.close if b730 else None
        px800 = b800.close if b800 else None
        nfp_out.append(
            {
                "date": d,
                "px_0730_close": px730,
                "px_0730_open": b730.open if b730 else None,
                "px_0800_close": px800,
                "rth_high": max((b.high for b in rth), default=None),
                "rth_low": min((b.low for b in rth), default=None),
                "rth_close": close_bar.close if close_bar else None,
                "move_0730c_0800": None
                if px730 is None or px800 is None
                else round(px800 - px730, 2),
                "move_0730c_close": None
                if px730 is None or close_bar is None
                else round(close_bar.close - px730, 2),
            }
        )

    ib.disconnect()

    ib_context = {
        "pulled_ct": iso(now_ct()),
        "es_contract": es.localSymbol,
        "daily_rth": daily_rows,
        "sessions_5m": session_out,
        "globex": globex,
        "vix_daily": vix_rows,
        "vx_futures": vx_rows,
    }
    ib_ovn_nfp = {
        "pulled": iso(now_ct()),
        "contract": es.localSymbol,
        "ovn_by_rth": ovn,
        "nfp": nfp_out,
        "vx_monthly": vx_rows,
    }
    save_json(RAW / "ib_context.json", ib_context)
    save_json(RAW / "ib_ovn_nfp.json", ib_ovn_nfp)

    # tick recorder Globex CVD
    tick_paths = [
        Path(os.environ.get("ES_TICK_DIR", r"C:\Users\mattm\es_tick_recorder\data")),
    ]
    tick_out = None
    for td in tick_paths:
        if not td.exists():
            continue
        # prefer newest ESZ*_YYYYMMDD.csv that is not depth
        cands = sorted(
            [p for p in td.glob("ESZ*_20*.csv") if "_depth_" not in p.name],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not cands:
            continue
        path = cands[0]
        buys = sells = 0.0
        hi = lo = last = None
        num = den = 0.0
        buckets = defaultdict(float)
        n = 0
        last_cvd = None
        first_ct = last_ct = None
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                # filter to current Globex window via ts_ct if present
                ts = row.get("ts_ct") or row.get("ts_utc")
                if first_ct is None:
                    first_ct = ts
                last_ct = ts
                try:
                    px = float(row["price"])
                    sz = float(row["size"])
                except Exception:
                    continue
                n += 1
                last = px
                hi = px if hi is None or px > hi else hi
                lo = px if lo is None or px < lo else lo
                num += px * sz
                den += sz
                buckets[round(px * 4) / 4] += sz
                side = (row.get("side") or "").upper()
                if side == "A":
                    buys += sz
                elif side == "B":
                    sells += sz
                if row.get("cvd") not in (None, ""):
                    try:
                        last_cvd = float(row["cvd"])
                    except Exception:
                        pass
        tick_out = {
            "source": str(path),
            "ticks": n,
            "first_ct": first_ct,
            "asof_ct": last_ct,
            "onh": hi,
            "onl": lo,
            "last": last,
            "vwap": round(num / den, 2) if den else None,
            "poc": max(buckets, key=buckets.get) if buckets else None,
            "buy_vol": buys,
            "sell_vol": sells,
            "cvd_recomputed": buys - sells,
            "cvd_file_last": last_cvd,
            "total_vol": den,
        }
        save_json(RAW / "tick_globex.json", tick_out)
        break
    if tick_out is None:
        failures.append("tick recorder: data dir/file not found (expected on AmoSZN)")

    return {"ok": True, "failures": failures, "connected": connected}


# ---------------------------------------------------------------------------
# web / cache refreshes (safe on box)
# ---------------------------------------------------------------------------

def refresh_gex() -> list[str]:
    fails = []
    # Prefer existing gex_pull.py for ES
    if GEX_PULL.exists():
        import subprocess

        try:
            subprocess.run([sys.executable, str(GEX_PULL)], check=False, timeout=60)
            if (STATE / "gex-latest.json").exists():
                shutil.copy(STATE / "gex-latest.json", RAW / "gex-latest.json")
        except Exception as e:
            fails.append(f"gex_pull.py: {e}")
    # SPY page
    try:
        html = fetch("https://zerogex.io/spy-gamma-levels")
        s = html.replace('\\"', '"')
        m = re.search(
            r'"levels":\{"symbol":"SPY","gammaFlip":(null|-?[\d.]+),"callWall":(-?[\d.]+),'
            r'"putWall":(-?[\d.]+),"maxPain":(-?[\d.]+),"asOf":"([^"]+)"',
            s,
        )
        if not m:
            fails.append("ZeroGEX SPY: levels regex miss")
        else:
            nm = re.search(r'"netGexAtSpot":(-?[\d.eE+]+)', s)
            sm = re.search(r'"quote":\{"close":(-?[\d.]+)', s)
            save_json(
                RAW / "gex_spy.json",
                {
                    "symbol": "SPY",
                    "flip": None if m.group(1) == "null" else float(m.group(1)),
                    "call_wall": float(m.group(2)),
                    "put_wall": float(m.group(3)),
                    "max_pain": float(m.group(4)),
                    "asof": m.group(5),
                    "net_gex": float(nm.group(1)) if nm else None,
                    "spot": float(sm.group(1)) if sm else None,
                    "source": "ZeroGEX SPY free (~15m delayed)",
                    "pulled_ct": iso(now_ct()),
                },
            )
    except Exception as e:
        fails.append(f"ZeroGEX SPY: {e}")
    return fails


def refresh_vix_yahoo() -> list[str]:
    fails = []
    out = {"pulled_ct": iso(now_ct())}
    for sym, key in [("^VIX", "vix"), ("^VIX9D", "vix9d")]:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1mo"
            data = json.loads(fetch(url))
            res = data["chart"]["result"][0]
            meta = res["meta"]
            ts = res["timestamp"]
            q = res["indicators"]["quote"][0]
            rows = []
            for i, t in enumerate(ts[-8:]):
                day = datetime.fromtimestamp(t, CT).strftime("%Y-%m-%d")
                rows.append(
                    {
                        "date": day,
                        "o": q["open"][-8 + i],
                        "h": q["high"][-8 + i],
                        "l": q["low"][-8 + i],
                        "c": q["close"][-8 + i],
                    }
                )
            out[key] = {
                "last": meta.get("regularMarketPrice"),
                "rows": rows,
                "source": "Yahoo Finance chart API",
            }
        except Exception as e:
            fails.append(f"Yahoo {sym}: {e}")
    save_json(RAW / "vix_yahoo.json", out)
    return fails


def refresh_calendar() -> list[str]:
    fails = []
    try:
        data = json.loads(fetch("https://nfs.faireconomy.media/ff_calendar_thisweek.json"))
        save_json(RAW / "ff_calendar_thisweek.json", data)
    except Exception as e:
        fails.append(f"FF calendar: {e}")
    return fails


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

def render(failures: list[str]) -> str:
    pulled = now_ct()
    ib = load_json(RAW / "ib_context.json") or {}
    ovn_nfp = load_json(RAW / "ib_ovn_nfp.json") or {}
    tick = load_json(RAW / "tick_globex.json") or {}
    gex = load_json(RAW / "gex-latest.json") or load_json(STATE / "gex-latest.json") or {}
    gex_spy = load_json(RAW / "gex_spy.json") or {}
    vix_y = load_json(RAW / "vix_yahoo.json") or {}
    stradd = load_json(RAW / "spy_straddle_nfp.json") or {}
    cal = load_json(RAW / "ff_calendar_thisweek.json") or []

    lines: list[str] = []
    lines.append(f"# ES context — ESZ26 (ESZ6)")
    lines.append("")
    lines.append(f"- **Built (CT):** {pulled.strftime('%Y-%m-%d %H:%M %Z')}")
    lines.append(f"- **Contract:** {ib.get('es_contract') or 'ESZ6 / 202612'}")
    lines.append("- **Mode:** read-only context file. Live legal? NO, size 0")
    lines.append("- **Rule:** every number below is sourced; unavailable stays unavailable (never invent).")
    lines.append("")

    # 1) last 5 RTH
    lines.append("## 1) Last 5 RTH sessions")
    lines.append("")
    lines.append(
        f"_Source: IB Gateway read-only historical on AmoSZN (`ib_context.json` pulled "
        f"{ib.get('pulled_ct', 'unavailable')}). POC/VAH/VAL approximate from 5-min RTH volume "
        f"buckets (0.25 pt). Overnight H/L = Globex 17:00 prior → 08:30 CT that day "
        f"(`ib_ovn_nfp.json`). Settlement = IB 1-day RTH close (CME official settle not pulled)._"
    )
    lines.append("")
    sessions = ib.get("sessions_5m") or []
    daily = {str(r["date"])[:10]: r for r in (ib.get("daily_rth") or [])}
    ovn_map = ovn_nfp.get("ovn_by_rth") or {}
    last5 = sessions[-5:] if len(sessions) >= 5 else sessions
    if not last5:
        lines.append("**unavailable** — no IB session cache in `raw/ib_context.json`. Re-run with `--pull-ib` on AmoSZN.")
        failures.append("last 5 RTH sessions: no ib_context cache")
    else:
        lines.append("| Date | High | Low | Close (5m last) | IB daily close* | Approx POC | VAH | VAL | ONH | ONL |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for s in last5:
            d = s["date"]
            dd = daily.get(d) or {}
            oo = ovn_map.get(d) or {}
            lines.append(
                f"| {d} | {fmt_num(s.get('high'))} | {fmt_num(s.get('low'))} | {fmt_num(s.get('close'))} | "
                f"{fmt_num(dd.get('c'))} | {fmt_num(s.get('poc'))} | {fmt_num(s.get('vah'))} | {fmt_num(s.get('val'))} | "
                f"{fmt_num(oo.get('onh'))} | {fmt_num(oo.get('onl'))} |"
            )
        lines.append("")
        lines.append("\\*IB daily close used as settlement proxy; official CME settlement not fetched.")
    lines.append("")

    # 2) tonight Globex
    lines.append("## 2) Tonight's Globex")
    lines.append("")
    if tick:
        lines.append(
            f"_Primary source: AmoSZN tick recorder `{tick.get('source')}` "
            f"(first {tick.get('first_ct')}, asof {tick.get('asof_ct')}). "
            f"Side map A=buy / B=sell; CVD from file column matches recomputed._"
        )
        lines.append("")
        lines.append(f"| Field | Value |")
        lines.append(f"|---|---|")
        lines.append(f"| ONH | {fmt_num(tick.get('onh'))} |")
        lines.append(f"| ONL | {fmt_num(tick.get('onl'))} |")
        lines.append(f"| Last | {fmt_num(tick.get('last'))} |")
        lines.append(f"| Overnight VWAP | {fmt_num(tick.get('vwap'))} |")
        lines.append(f"| POC (tick) | {fmt_num(tick.get('poc'))} |")
        lines.append(f"| Session CVD | {fmt_num(tick.get('cvd_file_last'), 0)} (buy {fmt_num(tick.get('buy_vol'),0)} / sell {fmt_num(tick.get('sell_vol'),0)}) |")
        lines.append(f"| Ticks / volume | {tick.get('ticks')} / {fmt_num(tick.get('total_vol'),0)} |")
    elif ib.get("globex"):
        g = ib["globex"]
        lines.append(f"_Fallback source: IB 5-min ETH (`ib_context.globex` asof {g.get('asof')}). CVD unavailable without ticks._")
        lines.append("")
        lines.append(f"| ONH | ONL | Last | VWAP | POC | CVD |")
        lines.append(f"|---:|---:|---:|---:|---:|---|")
        lines.append(
            f"| {fmt_num(g.get('onh'))} | {fmt_num(g.get('onl'))} | {fmt_num(g.get('last'))} | "
            f"{fmt_num(g.get('vwap'))} | {fmt_num(g.get('poc'))} | unavailable |"
        )
        failures.append("Globex CVD: tick recorder cache missing")
    else:
        lines.append("**unavailable** — no tick or IB Globex cache.")
        failures.append("tonight Globex: no data")
    lines.append("")

    # 3) VIX
    lines.append("## 3) VIX")
    lines.append("")
    vix_ib = ib.get("vix_daily") or []
    vx = ovn_nfp.get("vx_monthly") or ib.get("vx_futures") or []
    # Prefer true monthly VX (local like VXX6/VXZ6); drop VX## weeklies if mixed
    monthly = [x for x in vx if x.get("local") and len(str(x.get("local"))) <= 5 and str(x.get("local","")).startswith("VX")]
    if len(monthly) >= 2:
        vx = monthly
    elif monthly:
        vx = monthly + [x for x in vx if x not in monthly]
    vy = vix_y.get("vix") or {}
    v9 = vix_y.get("vix9d") or {}
    lines.append(
        f"_Spot: Yahoo `^VIX` / `^VIX9D` pulled {vix_y.get('pulled_ct','unavailable')}; "
        f"cross-check IB Index VIX daily in `ib_context`. "
        f"VX futures: IB CFE tradingClass=VX monthly._"
    )
    lines.append("")
    lines.append(f"- **VIX spot:** {fmt_num(vy.get('last'))} (Yahoo); IB last daily close {fmt_num(vix_ib[-1]['c'] if vix_ib else None)}")
    lines.append(f"- **VIX9D:** {fmt_num(v9.get('last'))}")
    if len(vx) >= 2:
        lines.append(
            f"- **VX front two months:** {vx[0].get('local')} (exp {vx[0].get('expiry')}) last {fmt_num(vx[0].get('last'))} on {vx[0].get('date')}; "
            f"{vx[1].get('local')} (exp {vx[1].get('expiry')}) last {fmt_num(vx[1].get('last'))} on {vx[1].get('date')}"
        )
    elif len(vx) == 1:
        lines.append(f"- **VX front:** {vx[0]} ; second month unavailable")
        failures.append("VX second month missing")
    else:
        lines.append("- **VX futures:** unavailable")
        failures.append("VX futures unavailable")
    # 5-day trend from Yahoo rows
    rows = vy.get("rows") or []
    if len(rows) >= 5:
        last5 = rows[-5:]
        lines.append("- **VIX last 5 sessions (Yahoo O/H/L/C):**")
        for r in last5:
            lines.append(
                f"  - {r['date']}: {fmt_num(r['o'])} / {fmt_num(r['h'])} / {fmt_num(r['l'])} / {fmt_num(r['c'])}"
            )
        c0, c1 = last5[0].get("c"), last5[-1].get("c")
        if c0 and c1:
            lines.append(f"- **5-day trend:** {fmt_num(c0)} → {fmt_num(c1)} ({fmt_num(c1-c0)} pts)")
    else:
        lines.append("- **5-day trend:** unavailable")
        failures.append("VIX 5-day Yahoo rows missing")
    lines.append("")

    # 4) NFP implied move
    lines.append("## 4) Expected NFP move (SPY 11/6 ATM straddle → ES pts)")
    lines.append("")
    if stradd:
        lines.append(
            f"_Source: {stradd.get('source')} ; quote updated {stradd.get('quote_updated_at_utc')} "
            f"({stradd.get('quote_asof_ct')}). {stradd.get('note','')}_"
        )
        lines.append("")
        lines.append(f"| Field | Value |")
        lines.append(f"|---|---|")
        lines.append(f"| Expiration | {stradd.get('expiration')} |")
        lines.append(f"| ATM strike | {fmt_num(stradd.get('strike_atm'))} |")
        lines.append(f"| Call mark | {fmt_num(stradd.get('call_mark'))} |")
        lines.append(f"| Put mark | {fmt_num(stradd.get('put_mark'))} |")
        lines.append(f"| Straddle | {fmt_num(stradd.get('straddle_mark'))} SPY pts |")
        lines.append(f"| ES ref / mult | {fmt_num(stradd.get('es_spot_ref'))} / {fmt_num(stradd.get('spy_to_es_mult'),4)} |")
        lines.append(f"| **Implied ES move** | **±{fmt_num(stradd.get('implied_es_points'),1)} pts** (to Fri expiration) |")
    else:
        lines.append("**unavailable** — no `raw/spy_straddle_nfp.json`. Refresh via Robinhood option quotes when connected.")
        failures.append("NFP implied move: no straddle cache")
    lines.append("")

    # 5) Gamma
    lines.append("## 5) Gamma (ZeroGEX)")
    lines.append("")
    if gex:
        age = age_minutes(gex.get("source_asof_iso") or gex.get("source_ts"), pulled)
        # also try asof_ct
        if age is None and gex.get("asof_ct"):
            try:
                asof = datetime.strptime(gex["asof_ct"], "%Y-%m-%d %H:%M").replace(tzinfo=CT)
                age = int((pulled - asof).total_seconds() // 60)
            except Exception:
                pass
        lines.append(
            f"_ES source: {gex.get('source','ZeroGEX')} ; vendor asof {gex.get('asof_ct') or gex.get('source_asof_iso')} ; "
            f"pulled {gex.get('pulled_ct')}_"
        )
        lines.append("")
        lines.append(f"| | ES | SPY |")
        lines.append(f"|---|---|---|")
        lines.append(f"| Spot (vendor) | {fmt_num(gex.get('spot'))} | {fmt_num(gex_spy.get('spot'))} |")
        flip = gex.get("flip")
        flip_s = "unresolved" if flip is None else fmt_num(flip)
        lines.append(f"| Flip | {flip_s} ({gex.get('flip_status','')}) | {fmt_num(gex_spy.get('flip'))} |")
        lines.append(f"| Call wall | {fmt_num(gex.get('call_wall'))} | {fmt_num(gex_spy.get('call_wall'))} |")
        lines.append(f"| Put wall | {fmt_num(gex.get('put_wall'))} | {fmt_num(gex_spy.get('put_wall'))} |")
        lines.append(f"| Max pain | {fmt_num(gex.get('max_pain'))} | {fmt_num(gex_spy.get('max_pain'))} |")
        spy_net = gex_spy.get('net_gex')
        if isinstance(spy_net, (int, float)):
            spy_net_s = f"{spy_net/1e9:.2f}B" if abs(spy_net)>=1e9 else (f"{spy_net/1e6:.2f}M" if abs(spy_net)>=1e6 else fmt_num(spy_net,0))
        else:
            spy_net_s = 'unavailable'
        lines.append(f"| Net GEX | {gex.get('net_gex')} | {spy_net_s} |")
        lines.append(f"| Snapshot age | **{age} min**" if age is not None else "| Snapshot age | unavailable")
        if gex_spy.get("asof"):
            age_s = age_minutes(gex_spy.get("asof"), pulled)
            lines.append(f"| SPY vendor asof | {gex_spy.get('asof')} (age {age_s} min)" if age_s is not None else f"| SPY vendor asof | {gex_spy.get('asof')}")
        if age is not None and age > 60:
            lines.append("")
            lines.append(f"**Stale flag:** ES gamma snapshot is {age} minutes old.")
    else:
        lines.append("**unavailable** — no gex-latest cache / ZeroGEX pull failed.")
        failures.append("gamma: no ES gex-latest")
    lines.append("")

    # 6) NFP history
    lines.append("## 6) Last NFP days — ES 07:30→08:00 and → RTH close")
    lines.append("")
    lines.append(
        "_Source: IB Gateway 5-min ETH historical ending each NFP Friday (`ib_ovn_nfp.json`). "
        "Move uses 07:30 bar **close** → 08:00 close, and 07:30 close → RTH close. "
        "Open of 07:30 bar also shown (release spike often inside that bar)._"
    )
    lines.append("")
    nfp = ovn_nfp.get("nfp") or []
    if not nfp:
        lines.append("**unavailable**")
        failures.append("NFP history: no cache")
    else:
        lines.append("| NFP date | 07:30 open | 07:30 close | 08:00 close | Δ 7:30→8:00 | RTH H/L | RTH close | Δ 7:30→close |")
        lines.append("|---|---:|---:|---:|---:|---|---:|---:|")
        for r in nfp:
            if r.get("error"):
                lines.append(f"| {r.get('date')} | unavailable ({r['error']}) | | | | | | |")
                continue
            hl = f"{fmt_num(r.get('rth_high'))}/{fmt_num(r.get('rth_low'))}"
            lines.append(
                f"| {r.get('date')} | {fmt_num(r.get('px_0730_open'))} | {fmt_num(r.get('px_0730_close'))} | "
                f"{fmt_num(r.get('px_0800_close'))} | {fmt_num(r.get('move_0730c_0800'))} | {hl} | "
                f"{fmt_num(r.get('rth_close'))} | {fmt_num(r.get('move_0730c_close'))} |"
            )
    lines.append("")

    # 7) events tomorrow
    lines.append("## 7) Upcoming events tomorrow (CT)")
    lines.append("")
    lines.append("_Source: Forex Factory week JSON (`nfs.faireconomy.media`), times converted from event offset to America/Chicago._")
    lines.append("")
    tomorrow = (pulled + timedelta(days=1)).strftime("%Y-%m-%d")
    # If built after midnight, "tomorrow" for overnight context is still the next RTH day from session view.
    # Prefer calendar day after the Globex date: if pulled evening Nov 5, tomorrow = Nov 6.
    day_target = tomorrow
    usd = []
    for e in cal if isinstance(cal, list) else []:
        if e.get("country") not in ("USD", "USA"):
            continue
        try:
            dt = datetime.fromisoformat(e["date"])
            dt_ct = dt.astimezone(CT)
        except Exception:
            continue
        if dt_ct.strftime("%Y-%m-%d") != day_target:
            continue
        usd.append((dt_ct, e))
    usd.sort(key=lambda x: x[0])
    if not usd:
        lines.append(f"**No USD events found for {day_target}** (or calendar refresh failed).")
        if not cal:
            failures.append("events: FF calendar missing")
    else:
        lines.append(f"Date: **{day_target}**")
        lines.append("")
        lines.append("| CT | Impact | Event | Forecast | Previous |")
        lines.append("|---|---|---|---|---|")
        for dt_ct, e in usd:
            lines.append(
                f"| {dt_ct.strftime('%H:%M')} | {e.get('impact')} | {e.get('title')} | {e.get('forecast') or '—'} | {e.get('previous') or '—'} |"
            )
    lines.append("")

    # merge static notes
    notes = load_json(RAW / "build_notes.json") or {}
    for g in notes.get("gaps") or []:
        if g not in failures:
            failures.append(g)

    # failures
    lines.append("## Sources that failed / gaps")
    lines.append("")
    if failures:
        for f in failures:
            lines.append(f"- {f}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("---")
    lines.append("Live legal? NO, size 0")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Build ES context markdown")
    ap.add_argument("--pull-ib", action="store_true", help="Refresh IB+ticks (run on AmoSZN)")
    ap.add_argument("--skip-web", action="store_true", help="Do not refresh ZeroGEX/Yahoo/FF")
    args = ap.parse_args()

    ROOT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []

    if args.pull_ib:
        res = pull_ib_and_ticks()
        if not res.get("ok"):
            failures.append(f"IB/tick pull: {res.get('error')}")
        else:
            failures.extend(res.get("failures") or [])

    if not args.skip_web:
        failures.extend(refresh_gex())
        failures.extend(refresh_vix_yahoo())
        failures.extend(refresh_calendar())

    md = render(failures)
    latest = ROOT / "es-context-latest.md"
    stamp = now_ct().strftime("%Y%m%d-%H%M")
    stamped = ROOT / f"es-context-{stamp}.md"
    latest.write_text(md, encoding="utf-8")
    stamped.write_text(md, encoding="utf-8")
    print(f"WROTE {latest}")
    print(f"WROTE {stamped}")
    print(f"failures={len(failures)}")
    for f in failures:
        print(" -", f)


if __name__ == "__main__":
    main()
