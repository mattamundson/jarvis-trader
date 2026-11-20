"""Load ES/NQ 1m/5m bars. IB/engine primary; Yahoo labeled fallback when stale/unreachable."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import timezone, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .timeutil import CT, parse_ct

# Box layout mirrors /workspace/tape; override with TAPE_ROOT. Defaults to scripts/tape in the repo.
TAPE_ROOT = Path(os.environ.get("TAPE_ROOT") or Path(__file__).resolve().parents[2])

SYSTEM = (TAPE_ROOT / "system")
DATA = SYSTEM / "data"
DATABENTO = (TAPE_ROOT / "databento")
STATE = (TAPE_ROOT / "state")

# Freshness gate for live price / current bars (Matt: Yahoo only if IB/engine >2 min old).
STALE_MAX_MIN = 2.0

ENGINE_BARS_ES_1M = STATE / "engine-bars-es-1m.json"
ENGINE_BARS_NQ_1M = STATE / "engine-bars-nq-1m.json"
ENGINE_SNAPSHOT = STATE / "engine-prices-snapshot.json"
PRICE_LATEST = STATE / "price-latest.json"
FLOW_LATEST = STATE / "flow-latest.json"

# Optional live HTTP (box rarely has this; files synced from AmoSZN are the normal path).
# Engine routes (on AmoSZN): GET http://127.0.0.1:8010/analyze/bars/{symbol}
#                           GET http://127.0.0.1:8010/prices/snapshot
ENGINE_BASE = os.environ.get("ENGINE_BASE_URL", "").rstrip("/")
ENGINE_API_KEY = os.environ.get("ENGINE_API_KEY", "")


@dataclass
class Bar:
    ts: datetime  # CT-aware, bar open
    o: float
    h: float
    l: float
    c: float
    v: int = 0


def _read_json(path: Path):
    if not path.exists():
        return None
    try:
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def _parse_bar(row) -> Bar:
    ts = datetime.fromisoformat(row[0].replace("Z", "+00:00")).astimezone(CT)
    return Bar(ts=ts, o=float(row[1]), h=float(row[2]), l=float(row[3]), c=float(row[4]), v=int(row[5]) if len(row) > 5 else 0)


def load_json_bars(path: Path) -> List[Bar]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw["bars"] if isinstance(raw, dict) and "bars" in raw else raw
    return [_parse_bar(r) for r in rows]


def _age_min(asof: datetime, now: Optional[datetime] = None) -> float:
    now = now or datetime.now(CT)
    if asof.tzinfo is None:
        asof = asof.replace(tzinfo=CT)
    return (now.astimezone(CT) - asof.astimezone(CT)).total_seconds() / 60.0


def _parse_any_ts(val) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        # engine snapshot uses unix epoch seconds
        try:
            return datetime.fromtimestamp(float(val), tz=CT)
        except Exception:
            return None
    s = str(val).strip()
    if not s:
        return None
    try:
        if "T" in s or s.endswith("Z") or "+" in s[10:]:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=CT)
            return dt.astimezone(CT)
        return parse_ct(s)
    except Exception:
        return None


def _engine_http_json(path: str, timeout: float = 8.0):
    """Optional HTTP to engine. Never used unless ENGINE_BASE_URL is set. Read-only."""
    if not ENGINE_BASE:
        return None
    url = f"{ENGINE_BASE}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "tape-system/prices"})
    if ENGINE_API_KEY:
        req.add_header("X-API-Key", ENGINE_API_KEY)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, Exception):
        return None


def _bars_from_engine_payload(payload: dict) -> List[Bar]:
    out: List[Bar] = []
    for b in payload.get("bars") or []:
        ts = _parse_any_ts(b.get("timestamp") or b.get("ts") or b.get("t"))
        if ts is None:
            continue
        # epoch seconds from flow series → bar open
        if isinstance(b.get("t"), (int, float)) and "timestamp" not in b:
            ts = datetime.fromtimestamp(float(b["t"]), tz=CT)
        out.append(
            Bar(
                ts=ts,
                o=float(b.get("open", b.get("o"))),
                h=float(b.get("high", b.get("h"))),
                l=float(b.get("low", b.get("l"))),
                c=float(b.get("close", b.get("c"))),
                v=int(b.get("volume", b.get("vol", 0)) or 0),
            )
        )
    return sorted(out, key=lambda x: x.ts)


def load_engine_es_1m() -> Tuple[List[Bar], dict]:
    """Load ES 1m from engine file or optional HTTP. Meta includes src + age."""
    meta: Dict = {"src": None, "age_min": None, "asof_ct": None, "fresh": False}
    payload = _engine_http_json("/analyze/bars/ES?timeframe=1m&limit=900")
    src = "engine HTTP /analyze/bars/ES"
    if payload is None:
        payload = _read_json(ENGINE_BARS_ES_1M)
        src = "engine /analyze/bars/ES (state file)"
    if not payload:
        return [], meta
    bars = _bars_from_engine_payload(payload)
    if not bars:
        return [], meta
    age = _age_min(bars[-1].ts)
    meta.update(
        {
            "src": src,
            "age_min": round(age, 2),
            "asof_ct": bars[-1].ts.astimezone(CT).strftime("%Y-%m-%d %H:%M"),
            "fresh": age <= STALE_MAX_MIN,
            "last": bars[-1].c,
            "n": len(bars),
            "url": "http://127.0.0.1:8010/analyze/bars/ES",
        }
    )
    return bars, meta


def load_engine_nq_1m() -> Tuple[List[Bar], dict]:
    meta: Dict = {"src": None, "age_min": None, "asof_ct": None, "fresh": False}
    payload = _engine_http_json("/analyze/bars/NQ?timeframe=1m&limit=120")
    src = "engine HTTP /analyze/bars/NQ"
    if payload is None:
        payload = _read_json(ENGINE_BARS_NQ_1M)
        src = "engine /analyze/bars/NQ (state file)"
    if not payload:
        return [], meta
    bars = _bars_from_engine_payload(payload)
    if not bars:
        return [], meta
    age = _age_min(bars[-1].ts)
    meta.update(
        {
            "src": src,
            "age_min": round(age, 2),
            "asof_ct": bars[-1].ts.astimezone(CT).strftime("%Y-%m-%d %H:%M"),
            "fresh": age <= STALE_MAX_MIN,
            "last": bars[-1].c,
            "n": len(bars),
        }
    )
    return bars, meta


def load_flow_es_1m() -> Tuple[List[Bar], dict]:
    """IB tick-recorder flow-latest series_1m (AmoSZN → mirrored state file)."""
    meta: Dict = {"src": None, "age_min": None, "asof_ct": None, "fresh": False}
    j = _read_json(FLOW_LATEST)
    if not j:
        return [], meta
    asof = _parse_any_ts(j.get("as_of_ct") or j.get("as_of_epoch"))
    bars: List[Bar] = []
    for b in j.get("series_1m") or []:
        ts = datetime.fromtimestamp(float(b["t"]), tz=CT) if "t" in b else _parse_any_ts(b.get("ts"))
        if ts is None:
            continue
        bars.append(
            Bar(
                ts=ts,
                o=float(b["o"]),
                h=float(b["h"]),
                l=float(b["l"]),
                c=float(b["c"]),
                v=int(b.get("vol", 0) or 0),
            )
        )
    bars = sorted(bars, key=lambda x: x.ts)
    if asof is None and bars:
        asof = bars[-1].ts
    if asof is None:
        return bars, meta
    age = _age_min(asof)
    last = None
    if j.get("price") and j["price"].get("last") is not None:
        last = float(j["price"]["last"])
    elif bars:
        last = bars[-1].c
    meta.update(
        {
            "src": "IB flow-latest (tick recorder port 4001)",
            "age_min": round(age, 2),
            "asof_ct": asof.astimezone(CT).strftime("%Y-%m-%d %H:%M:%S"),
            "fresh": age <= STALE_MAX_MIN,
            "last": last,
            "n": len(bars),
        }
    )
    return bars, meta


def live_price_quote(now: Optional[datetime] = None) -> dict:
    """Resolve current ES last with IB/engine primary, Yahoo fallback if >2 min or missing.

    Preference order:
      1) engine /prices/snapshot (MES/ES)
      2) engine price-latest.json
      3) engine /analyze/bars/ES last bar
      4) IB flow-latest.json
      5) Yahoo 1m cache (labeled)
    """
    now = now or datetime.now(CT)
    candidates: List[dict] = []

    # 1) snapshot
    snap = _engine_http_json("/prices/snapshot")
    if snap is None:
        snap = _read_json(ENGINE_SNAPSHOT)
    if snap:
        row = snap.get("MES") or snap.get("ES") or snap.get("ESZ6")
        if row and row.get("last_price") is not None:
            asof = _parse_any_ts(row.get("as_of"))
            if asof is not None:
                age = _age_min(asof, now)
                candidates.append(
                    {
                        "last": float(row["last_price"]),
                        "src": f"engine /prices/snapshot ({row.get('source', 'IB')})",
                        "age_min": round(age, 2),
                        "asof_ct": asof.astimezone(CT).strftime("%Y-%m-%d %H:%M:%S"),
                        "fresh": age <= STALE_MAX_MIN,
                        "url": "http://127.0.0.1:8010/prices/snapshot",
                    }
                )

    # 2) price-latest.json (same file checklist already uses for RTH)
    pl = _read_json(PRICE_LATEST)
    if pl and pl.get("last") is not None:
        asof = _parse_any_ts(pl.get("last_bar_ts") or pl.get("asof_ct"))
        if asof is not None:
            age = _age_min(asof, now)
            candidates.append(
                {
                    "last": float(pl["last"]),
                    "src": pl.get("src") or "engine price-latest",
                    "age_min": round(age, 2),
                    "asof_ct": asof.astimezone(CT).strftime("%Y-%m-%d %H:%M:%S"),
                    "fresh": age <= STALE_MAX_MIN,
                    "url": pl.get("bars_url") or "http://127.0.0.1:8010/analyze/bars/ES",
                    "session_rth_high": pl.get("session_rth_high"),
                    "session_rth_low": pl.get("session_rth_low"),
                }
            )

    # 3) engine bars
    bars, meta = load_engine_es_1m()
    if bars and meta.get("last") is not None:
        candidates.append(
            {
                "last": float(meta["last"]),
                "src": meta["src"],
                "age_min": meta["age_min"],
                "asof_ct": meta["asof_ct"],
                "fresh": meta["fresh"],
                "url": meta.get("url"),
            }
        )

    # 4) flow
    _, fmeta = load_flow_es_1m()
    if fmeta.get("last") is not None:
        candidates.append(
            {
                "last": float(fmeta["last"]),
                "src": fmeta["src"],
                "age_min": fmeta["age_min"],
                "asof_ct": fmeta["asof_ct"],
                "fresh": fmeta["fresh"],
            }
        )

    fresh = [c for c in candidates if c.get("fresh")]
    if fresh:
        # pick youngest
        best = min(fresh, key=lambda c: c["age_min"])
        best["fallback"] = False
        return best

    # Yahoo fallback
    ypath = DATA / "es_yahoo_7d_1m.json"
    if ypath.exists():
        try:
            ybars = load_json_bars(ypath)
            if ybars:
                age = _age_min(ybars[-1].ts, now)
                reason = "IB/engine unreachable or older than 2 min"
                if candidates:
                    ages = ", ".join(f"{c['src']} age={c['age_min']}m" for c in candidates[:3])
                    reason = f"IB/engine stale ({ages})"
                return {
                    "last": ybars[-1].c,
                    "src": f"Yahoo ES=F 1m delayed~10m (fallback: {reason})",
                    "age_min": round(age, 2),
                    "asof_ct": ybars[-1].ts.astimezone(CT).strftime("%Y-%m-%d %H:%M"),
                    "fresh": False,
                    "fallback": True,
                }
        except Exception:
            pass

    if candidates:
        best = min(candidates, key=lambda c: c["age_min"] if c["age_min"] is not None else 1e9)
        best = dict(best)
        best["fallback"] = False
        best["src"] = f"{best['src']} (STALE >{STALE_MAX_MIN}m — no Yahoo available)"
        return best

    return {
        "last": None,
        "src": "missing",
        "age_min": None,
        "asof_ct": None,
        "fresh": False,
        "fallback": True,
        "missing": True,
    }


def load_es_1m(prefer: str = "auto") -> List[Bar]:
    """prefer: auto|engine|yahoo|databento.
    auto/engine: IB engine bars first (then flow), Yahoo only to pad history or if engine empty/stale for live.
    """
    bars: List[Bar] = []
    db_dirs = sorted(DATABENTO.glob("20*/bars_1m.json"))
    for p in db_dirs:
        try:
            bars.extend(load_json_bars(p))
        except Exception:
            continue
    ypath = DATA / "es_yahoo_7d_1m.json"
    ybars = load_json_bars(ypath) if ypath.exists() else []
    ovn = DATA / "es_1m_ovn_2026-11-05_yahoo.json"
    if ovn.exists() and not ybars:
        ybars = load_json_bars(ovn)

    if prefer == "databento":
        return sorted(bars, key=lambda b: b.ts)
    if prefer == "yahoo":
        return sorted(ybars or bars, key=lambda b: b.ts)

    # engine / auto
    ebars, emeta = load_engine_es_1m()
    if not ebars:
        ebars, emeta = load_flow_es_1m()
    if prefer == "engine":
        if emeta.get("fresh") or ebars:
            return sorted(ebars, key=lambda b: b.ts)
        return sorted(ybars or bars, key=lambda b: b.ts)

    # auto: merge databento < yahoo < engine (engine wins on overlap)
    by_ts = {b.ts: b for b in bars}
    for b in ybars:
        by_ts[b.ts] = b
    if emeta.get("fresh") or ebars:
        for b in ebars:
            by_ts[b.ts] = b
    return [by_ts[k] for k in sorted(by_ts)]


def load_es_5m(prefer: str = "auto") -> List[Bar]:
    bars1 = load_es_1m(prefer=prefer)
    if not bars1:
        return []
    out: List[Bar] = []
    bucket: List[Bar] = []
    cur_key = None
    for b in bars1:
        key = b.ts.replace(minute=(b.ts.minute // 5) * 5, second=0, microsecond=0)
        if cur_key is None:
            cur_key = key
        if key != cur_key:
            if bucket:
                out.append(
                    Bar(
                        ts=cur_key,
                        o=bucket[0].o,
                        h=max(x.h for x in bucket),
                        l=min(x.l for x in bucket),
                        c=bucket[-1].c,
                        v=sum(x.v for x in bucket),
                    )
                )
            bucket = [b]
            cur_key = key
        else:
            bucket.append(b)
    if bucket and cur_key is not None:
        out.append(
            Bar(
                ts=cur_key,
                o=bucket[0].o,
                h=max(x.h for x in bucket),
                l=min(x.l for x in bucket),
                c=bucket[-1].c,
                v=sum(x.v for x in bucket),
            )
        )
    return out


def load_nq_1m(prefer: str = "auto") -> Tuple[List[Bar], dict]:
    if prefer == "yahoo":
        nq_path = DATA / "nq_yahoo_7d_1m.json"
        if nq_path.exists():
            bars = load_json_bars(nq_path)
            if bars:
                age = _age_min(bars[-1].ts)
                return bars, {
                    "src": "Yahoo NQ=F 1m delayed~10m",
                    "age_min": round(age, 2),
                    "asof_ct": bars[-1].ts.astimezone(CT).strftime("%Y-%m-%d %H:%M"),
                    "fresh": False,
                    "last": bars[-1].c,
                }
        return [], {"missing": True}
    bars, meta = load_engine_nq_1m()
    if meta.get("fresh") or bars:
        return bars, meta
    nq_path = DATA / "nq_yahoo_7d_1m.json"
    if nq_path.exists():
        ybars = load_json_bars(nq_path)
        if ybars:
            age = _age_min(ybars[-1].ts)
            return ybars, {
                "src": f"Yahoo NQ=F 1m delayed~10m (fallback: engine NQ age={meta.get('age_min')})",
                "age_min": round(age, 2),
                "asof_ct": ybars[-1].ts.astimezone(CT).strftime("%Y-%m-%d %H:%M"),
                "fresh": False,
                "last": ybars[-1].c,
                "fallback": True,
            }
    return [], {"missing": True}


def nq_vs_es(window: int = 60) -> dict:
    """Last-hour relative performance using engine bars when fresh."""
    es_bars, es_meta = load_engine_es_1m()
    if not es_meta.get("fresh"):
        # still ok if we have enough bars from engine file even if slightly stale
        if not es_bars:
            es_bars = load_es_1m(prefer="yahoo")
            es_meta = {"src": "Yahoo ES=F 1m delayed~10m", "fresh": False}
    nq_bars, nq_meta = load_nq_1m(prefer="auto")
    if len(es_bars) < window or len(nq_bars) < window:
        return {"missing": True}
    es_ret = (es_bars[-1].c - es_bars[-window].c) / es_bars[-window].c * 100
    nq_ret = (nq_bars[-1].c - nq_bars[-window].c) / nq_bars[-window].c * 100
    src = f"ES:{es_meta.get('src')}; NQ:{nq_meta.get('src')}"
    return {
        "missing": False,
        "es_last": es_bars[-1].c,
        "nq_last": nq_bars[-1].c,
        "es_ret_1h_pct": round(es_ret, 3),
        "nq_ret_1h_pct": round(nq_ret, 3),
        "nq_outperforming": nq_ret > es_ret,
        "src": src,
        "es_age_min": es_meta.get("age_min"),
        "nq_age_min": nq_meta.get("age_min"),
    }


def price_at(bars: List[Bar], when: datetime) -> Optional[float]:
    """Last close at or before `when`."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=CT)
    last = None
    for b in bars:
        if b.ts <= when:
            last = b.c
        else:
            break
    return last


def window_hlc(bars: List[Bar], start: datetime, end: datetime) -> Optional[Tuple[float, float, float]]:
    """High, low, last-close in window."""
    if start.tzinfo is None:
        start = start.replace(tzinfo=CT)
    if end.tzinfo is None:
        end = end.replace(tzinfo=CT)
    chunk2 = [b for b in bars if start <= b.ts <= end]
    use = chunk2
    if not use:
        return None
    return max(b.h for b in use), min(b.l for b in use), use[-1].c


def last_closed_15m_close(bars_5m: List[Bar], asof: datetime) -> Optional[Tuple[datetime, float]]:
    """Most recent fully closed 15m bar close at or before asof."""
    if asof.tzinfo is None:
        asof = asof.replace(tzinfo=CT)
    closed = []
    i = 0
    while i < len(bars_5m):
        b = bars_5m[i]
        if b.ts.minute % 15 != 0:
            i += 1
            continue
        group = [b]
        for j in range(1, 3):
            if i + j < len(bars_5m) and bars_5m[i + j].ts == b.ts + timedelta(minutes=5 * j):
                group.append(bars_5m[i + j])
        close_time = b.ts + timedelta(minutes=15)
        if len(group) == 3 and close_time <= asof:
            closed.append((close_time, group[-1].c, b.ts, max(x.h for x in group), min(x.l for x in group)))
        i += 1
    if not closed:
        return None
    ct, c, *_ = closed[-1]
    return ct, c


IB_CONTEXT = (TAPE_ROOT / "context/raw/ib_context.json")


def _meta_complete(m: dict) -> bool:
    """True only if the databento session runs to the 15:00 CT RTH close."""
    end = m.get("end_utc")
    if not end or not m.get("date"):
        return False
    try:
        end_dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        close_ct = datetime.fromisoformat(m["date"]).replace(hour=15, minute=0, tzinfo=CT)
        return end_dt >= close_ct
    except Exception:
        return False


def _ib_daily_rows() -> dict:
    j = _read_json(IB_CONTEXT) or {}
    out = {}
    for d in j.get("daily_rth") or []:
        try:
            out[d["date"]] = {"date": d["date"], "rth_high": float(d["h"]), "rth_low": float(d["l"]),
                              "last_close": float(d["c"]), "_src": "IB daily RTH (close unconfirmed vs CME settle)"}
        except Exception:
            pass
    return out


def _session_metas() -> List[dict]:
    """Databento metas that reach the RTH close; partial ones replaced by IB daily, else dropped."""
    ib = _ib_daily_rows()
    rows = []
    for p in sorted(DATABENTO.glob("20*/meta.json")):
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if m.get("rth_high") is None or m.get("rth_low") is None:
            continue
        if _meta_complete(m):
            rows.append(m)
        elif m.get("date") in ib:
            rows.append(ib[m["date"]])
    have = {r["date"] for r in rows}
    for d, r in ib.items():
        if d not in have and rows and d > rows[0]["date"]:
            rows.append(r)
    return sorted(rows, key=lambda r: r["date"])


def _engine_rth_override() -> Optional[dict]:
    """Prefer engine price-latest RTH when databento meta is truncated mid-session."""
    j = _read_json(PRICE_LATEST)
    if not j:
        return None
    if j.get("session_rth_high") is None or j.get("session_rth_low") is None:
        return None
    return {
        "date": j.get("date"),
        "high": float(j["session_rth_high"]),
        "low": float(j["session_rth_low"]),
        "close": float(j["last"]) if j.get("last") is not None else None,
        "src": "engine price-latest RTH",
    }


def prior_session_range(es_daily_path: Path = DATA / "es_daily.json",
                        asof: Optional[datetime] = None) -> Optional[dict]:
    """Just-completed RTH range relative to asof."""
    rows = _session_metas()
    eng = _engine_rth_override()
    if eng and eng.get("date"):
        rows = [r for r in rows if r.get("date") != eng["date"]]
        rows.append(
            {
                "date": eng["date"],
                "rth_high": eng["high"],
                "rth_low": eng["low"],
                "last_close": eng["close"],
                "_src": eng["src"],
            }
        )
        rows = sorted(rows, key=lambda r: r["date"])
    if asof is not None:
        if asof.tzinfo is None:
            asof = asof.replace(tzinfo=CT)
        local = asof.astimezone(CT)
        if local.hour >= 17:
            want = local.date().isoformat()
            same = [r for r in rows if r["date"] == want]
            if same:
                last = same[-1]
                return {
                    "date": last["date"],
                    "high": float(last["rth_high"]),
                    "low": float(last["rth_low"]),
                    "close": float(last["last_close"]) if last.get("last_close") is not None else None,
                    "src": last.get("_src") or "databento meta RTH",
                }
            cutoff = want
        else:
            cutoff = local.date().isoformat()
        rows = [r for r in rows if r["date"] < cutoff]
    if rows:
        last = rows[-1]
        return {
            "date": last["date"],
            "high": float(last["rth_high"]),
            "low": float(last["rth_low"]),
            "close": float(last["last_close"]) if last.get("last_close") is not None else None,
            "src": last.get("_src") or "databento meta RTH",
        }
    if not es_daily_path.exists():
        return None
    daily = json.loads(es_daily_path.read_text(encoding="utf-8"))["bars_daily"]
    if len(daily) < 2:
        return None
    d = daily[-2]
    return {"date": d[0], "high": d[2], "low": d[3], "close": d[4], "src": "yahoo daily"}


def prior_n_sessions(n: int = 5, asof: Optional[datetime] = None) -> List[dict]:
    rows = [
        {
            "date": m["date"],
            "high": float(m["rth_high"]),
            "low": float(m["rth_low"]),
            "close": float(m["last_close"]) if m.get("last_close") is not None else None,
            "src": m.get("_src") or "databento meta RTH",
        }
        for m in _session_metas()
    ]
    eng = _engine_rth_override()
    if eng and eng.get("date"):
        rows = [r for r in rows if r["date"] != eng["date"]]
        rows.append(
            {
                "date": eng["date"],
                "high": eng["high"],
                "low": eng["low"],
                "close": eng["close"],
                "src": eng["src"],
            }
        )
        rows = sorted(rows, key=lambda r: r["date"])
    if asof is not None:
        if asof.tzinfo is None:
            asof = asof.replace(tzinfo=CT)
        local = asof.astimezone(CT)
        cutoff = local.date().isoformat()
        if local.hour >= 17:
            rows = [r for r in rows if r["date"] <= cutoff]
        else:
            rows = [r for r in rows if r["date"] < cutoff]
    if len(rows) >= n:
        return rows[-n:]
    ypath = DATA / "es_daily.json"
    if ypath.exists():
        daily = json.loads(ypath.read_text(encoding="utf-8"))["bars_daily"]
        have = {r["date"] for r in rows}
        for d in daily:
            if d[0] in have:
                continue
            rows.append({"date": d[0], "high": d[2], "low": d[3], "close": d[4], "src": "yahoo daily"})
        rows = sorted(rows, key=lambda r: r["date"])
        if asof is not None:
            cutoff = asof.astimezone(CT).date().isoformat()
            rows = [r for r in rows if r["date"] < cutoff]
    return rows[-n:]
