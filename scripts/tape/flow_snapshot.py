#!/usr/bin/env python
"""flow_snapshot.py - read-only order-flow snapshot feed for the /tape page. NO ORDERS, NO ACCOUNT DATA.

Every INTERVAL seconds (default 5) it
  * tails the tick recorder CSV (<REC_DIR>/ESZ6_YYYYMMDD.csv, CT trading day) + heartbeat.json
  * optionally reads NQ 1-minute bars from IB (read-only, clientId 98, ports 4001 then 4002)
  * writes   <STATE_DIR>/flow-latest.json          (atomic replace)
  * appends  <STATE_DIR>/flow-history-<YYYY-MM-DD>.jsonl  (one compact row per pass)

It never touches positions, P&L or account fields, and never imports engine code.

Separate source files (written by their own producers, read by the Next.js /api/tape route):
  gex-latest.json         existing GEX format: asof_ct, spot, call_wall, put_wall, flip, max_pain, pin,
                          net_gex, source, pulled_ct, [age_min, stale, history_today]
  doublewide-latest.json  {"as_of_ct": "2026-10-26 20:08", "source": "...", "interval_s": 3600,
                           "levels": [{"name": "DW S2 fade", "px": 7684, "note": "..."}], "note": "..."}
  aaron-latest.json       same shape as doublewide-latest.json
`as_of_ct` ("YYYY-MM-DD HH:MM" CT) is the source's own timestamp; the page computes staleness from it.

tape-config.json (seeded on first run, edit freely; hot-reloaded each pass): cvd gate level, leg swing size,
trigger, price levels, NQ gate. Defaults are tonight's working levels, not recommendations.

Usage:  python flow_snapshot.py            (loop)
        python flow_snapshot.py --once     (single pass, no NQ, prints a summary)
        python flow_snapshot.py --selftest
"""
import argparse, csv, datetime as dt, json, math, os, sys, time
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")
UTC = dt.timezone.utc
HOME = os.path.expanduser("~")
REC_DIR = os.environ.get("TAPE_REC_DIR", os.path.join(HOME, "es_tick_recorder", "data"))
STATE_DIR = os.environ.get("TAPE_STATE_DIR", os.path.join(HOME, "tape", "state"))
NQ_CLIENT_ID = int(os.environ.get("TAPE_NQ_CLIENT_ID", "98"))
NQ_EXPIRY = os.environ.get("TAPE_NQ_EXPIRY", "202612")
IB_PORTS = tuple(int(p) for p in os.environ.get("TAPE_IB_PORTS", "4001,4002").split(","))
SERIES_MAX = 360          # 1-min points exposed (6h)
LEGS_MAX = 14

DEFAULT_CONFIG = {
    "interval_s": 5,
    "cvd_gate": {
        "mode": "z30",           # "z30" (default, origin-free) or "fixed" (absolute level; legacy)
        "window_min": 30,        # z30: CVD change measured over this many minutes
        "lookback_min": 240,     # z30: trailing window of rolling changes that sets the scale
        "min_samples": 60,       # z30: need this many rolling samples before the gate leaves "warming"
        "z_thr": 1.0,            # z30: |z| >= thr = decisive (above/below); inside = at
        "level": 540,            # fixed mode only
        "label": "CVD gate",
        "note": "z30: 30-min CVD change / its own scale this session (zero-centred RMS). Origin-free: the recorder CVD restarts at 0 every trading-day file.",
    },
    "depth": {"levels": 10, "big_mult": 3.0, "big_min_lots": 100, "avg_n": 60, "stale_s": 15},
    "leg_swing_pts": 3.0,
    "trigger": {"px": 7725.75, "dir": "above", "tf_min": 5, "label": "5m close above 7725.75"},
    "levels": [
        {"name": "Target 3", "px": 7730.0, "kind": "target", "dir": "above", "bias": "bull", "note": "7729-7731"},
        {"name": "Target 2", "px": 7727.4, "kind": "target", "dir": "above", "bias": "bull"},
        {"name": "Trigger", "px": 7725.75, "kind": "trigger", "dir": "above", "bias": "bull"},
        {"name": "Overnight VWAP", "px": 7723.0, "kind": "support", "dir": "below", "bias": "bear", "note": "5m close under = fade"},
        {"name": "Down 1", "px": 7721.0, "kind": "target", "dir": "below", "bias": "bear"},
        {"name": "Bear invalidation", "px": 7719.25, "kind": "invalid", "dir": "below", "bias": "bear"},
    ],
    "nq_gate": 29458.0,
}


# ----------------------------------------------------------------------------- time helpers
def trading_day(t):
    """CT trading date; the 17:00 CT open belongs to the NEXT calendar date (matches the recorder)."""
    t = t.astimezone(CT)
    return (t + dt.timedelta(hours=7)).date() if t.time() >= dt.time(17, 0) else t.date()


def iso_to_epoch(s):
    return dt.datetime.fromisoformat(s).timestamp()


def epoch_ct(e, fmt="%H:%M:%S"):
    return dt.datetime.fromtimestamp(e, CT).strftime(fmt)


def iso_ct(e):
    return dt.datetime.fromtimestamp(e, CT).isoformat(timespec="seconds")


# ----------------------------------------------------------------------------- aggregation
class Aggregator:
    """Incremental aggregation of recorder rows into 1-minute bars + session stats."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.bars = {}                 # minute_epoch -> dict
        self.offset = 0
        self.n = 0; self.vol = 0; self.pxvol = 0.0
        self.hi = None; self.lo = None; self.last = None; self.bid = None; self.ask = None
        self.cvd = 0; self.last_ts = None; self.first_ts = None
        self.n_bidask = 0; self.n_tick = 0

    def ingest(self, r):
        ts = iso_to_epoch(r["ts_utc"]); px = float(r["price"]); sz = int(float(r["size"]))
        d = int(float(r["delta"])); cvd = int(float(r["cvd"]))
        m = int(ts // 60) * 60
        b = self.bars.get(m)
        if b is None:
            b = self.bars[m] = dict(t=m, o=px, h=px, l=px, c=px, vol=0, delta=0, n=0, cvd=cvd)
        b["h"] = max(b["h"], px); b["l"] = min(b["l"], px); b["c"] = px
        b["vol"] += sz; b["delta"] += d; b["n"] += 1; b["cvd"] = cvd
        self.n += 1; self.vol += sz; self.pxvol += px * sz
        self.hi = px if self.hi is None else max(self.hi, px)
        self.lo = px if self.lo is None else min(self.lo, px)
        self.last = px; self.cvd = cvd; self.last_ts = ts
        if self.first_ts is None: self.first_ts = ts
        try:
            self.bid = float(r["bid"]) if r.get("bid") not in (None, "") else self.bid
            self.ask = float(r["ask"]) if r.get("ask") not in (None, "") else self.ask
        except ValueError: pass
        if r.get("basis") == "bidask": self.n_bidask += 1
        else: self.n_tick += 1

    @property
    def vwap(self):
        return self.pxvol / self.vol if self.vol else None


def read_new_rows(path, agg):
    """Read complete new CSV lines since agg.offset. Returns number of rows ingested."""
    if not os.path.exists(path): return 0
    size = os.path.getsize(path)
    if size < agg.offset: agg.reset()            # file replaced/truncated
    if size == agg.offset: return 0
    with open(path, "rb") as f:
        f.seek(0)
        header = f.readline().decode().strip().split(",")
        start = max(agg.offset, f.tell())
        f.seek(start)
        chunk = f.read()
    end = chunk.rfind(b"\n")
    if end < 0: return 0
    lines = chunk[:end + 1].decode(errors="replace").splitlines()
    agg.offset = start + end + 1
    n = 0
    for row in csv.DictReader(lines, fieldnames=header):
        try: agg.ingest(row); n += 1
        except (KeyError, ValueError, TypeError): continue
    return n


def sorted_bars(agg):
    return [agg.bars[k] for k in sorted(agg.bars)]


# ----------------------------------------------------------------------------- analytics
def zigzag_legs(bars, swing):
    """Swing legs on 1-min closes. A leg ends when price retraces >= swing from its extreme."""
    if len(bars) < 2: return []
    closes = [b["c"] for b in bars]
    pivots = [0]; direction = 0; ext_i = 0
    for i in range(1, len(closes)):
        if direction == 0:
            if closes[i] - closes[pivots[0]] >= swing: direction, ext_i = 1, i
            elif closes[pivots[0]] - closes[i] >= swing: direction, ext_i = -1, i
        elif direction == 1:
            if closes[i] > closes[ext_i]: ext_i = i
            elif closes[ext_i] - closes[i] >= swing: pivots.append(ext_i); direction, ext_i = -1, i
        else:
            if closes[i] < closes[ext_i]: ext_i = i
            elif closes[i] - closes[ext_i] >= swing: pivots.append(ext_i); direction, ext_i = 1, i
    if direction != 0 and ext_i != pivots[-1]: pivots.append(ext_i)
    last = len(bars) - 1
    legs = []
    seq = pivots + ([last] if pivots[-1] != last else [])
    for a, bidx in zip(seq, seq[1:]):
        seg = bars[a + 1: bidx + 1]
        if not seg: continue
        mins = max(1, int((bars[bidx]["t"] - bars[a]["t"]) // 60))
        vol = sum(x["vol"] for x in seg); delta = sum(x["delta"] for x in seg)
        legs.append(dict(dir="up" if closes[bidx] >= closes[a] else "down",
                         t0=bars[a]["t"], t1=bars[bidx]["t"], px0=closes[a], px1=closes[bidx],
                         pts=round(closes[bidx] - closes[a], 2), minutes=mins, vol=vol, delta=delta,
                         lpm=round(vol / mins, 1), cvd0=bars[a]["cvd"], cvd1=bars[bidx]["cvd"],
                         open=False))
    for i, g in enumerate(legs): g["n"] = i + 1
    if legs: legs[-1]["open"] = True   # newest leg is always unconfirmed (no reversal yet)
    return legs[-LEGS_MAX:]


def lots_per_min(bars, now_epoch):
    """Rates over *calendar* minutes (empty minutes count as zero), excluding the still-forming minute."""
    if not bars: return dict(last=None, avg5=None, avg30=None, peak=None)
    cur = int(now_epoch // 60) * 60
    byt = {b["t"]: b["vol"] for b in bars}
    def avg(n): return round(sum(byt.get(cur - 60 * k, 0) for k in range(1, n + 1)) / n, 1)
    return dict(last=byt.get(cur - 60, 0), avg5=avg(5), avg30=avg(30), peak=max(byt.values()))


def five_min_closes(bars, now_epoch):
    """Completed 5-minute closes (CT-aligned buckets)."""
    out = {}
    for b in bars:
        k = int(b["t"] // 300) * 300
        out[k] = b["c"]
    cur5 = int(now_epoch // 300) * 300
    return [(k, v) for k, v in sorted(out.items()) if k < cur5]


def cvd_gate_fixed(bars, level, cvd):
    side = "above" if cvd > level else "below" if cvd < level else "at"
    crossed_t = None; prev = None
    for b in bars:
        s = b["cvd"] > level
        if prev is not None and s != prev: crossed_t = b["t"]
        prev = s
    return dict(mode="fixed", level=level, cvd=cvd, side=side, dist=cvd - level, last_cross_t=crossed_t,
                last_cross_ct=epoch_ct(crossed_t, "%H:%M") if crossed_t else None,
                lean="up" if side == "above" else "down" if side == "below" else None, state="ok")


def cvd_gate_z30(bars, cvd, window_min=30, lookback_min=240, min_samples=60, z_thr=1.0):
    """Origin-free CVD gate: z-score of the trailing `window_min` CVD change.

    The recorder's CVD restarts at 0 in every trading-day file, so an absolute gate level goes stale the
    moment the origin differs. This rule only looks at CVD *changes*:
      delta_w(m) = CVD(end of minute m) - CVD(end of minute m - window_min)         (calendar minutes, ffilled)
      scale      = sqrt(mean(delta_w(m)^2)) over the last `lookback_min` minutes of the session
                   (zero-centred RMS: no drift is assumed, so a one-way session still scores as extreme)
      z          = delta_w(now) / scale
    side: above if z >= z_thr, below if z <= -z_thr, else "at" (no decisive flow). lean = sign(z) (used by
    the bias vote). state "warming" until `min_samples` rolling samples exist (default 90 min into the session).
    level = CVD `window_min` ago, so dist = the 30-minute CVD change. Rolling samples overlap, so z is a
    descriptive ranking of flow, not a calibrated probability.
    """
    if not bars:
        return None
    w = int(window_min) * 60
    first, last = bars[0]["t"], bars[-1]["t"]
    base = bars[0]["cvd"] - bars[0].get("delta", 0)           # CVD at the very start of the first bar
    by_t = {b["t"]: b["cvd"] for b in bars}
    def at(t):
        if t < first: return base
        while t not in by_t: t -= 60                          # ffill across empty minutes
        return by_t[t]
    ref = at(last - w)
    d_now = cvd - ref
    lo = max(first + w, last - int(lookback_min) * 60)
    samples = []
    m = lo
    while m <= last:
        samples.append(at(m) - at(m - w)); m += 60
    n = len(samples)
    scale = math.sqrt(sum(x * x for x in samples) / n) if n else 0.0
    warming = last - first < w or n < int(min_samples) or scale <= 0
    z = None if warming else d_now / scale
    side = "at" if warming else "above" if z >= z_thr else "below" if z <= -z_thr else "at"
    lean = None if (warming or d_now == 0) else "up" if d_now > 0 else "down"
    # last time the 30m change flipped sign
    cross_t = None; prev = None; m = lo
    while m <= last:
        v = at(m) - at(m - w); sg = (v > 0) - (v < 0)
        if sg != 0:
            if prev is not None and sg != prev: cross_t = m
            prev = sg
        m += 60
    return dict(mode="z30", level=ref, cvd=cvd, side=side, dist=d_now, z=None if z is None else round(z, 2),
                scale=round(scale, 1), n=n, window_min=int(window_min), z_thr=float(z_thr), lean=lean,
                state="warming" if warming else "ok", last_cross_t=cross_t,
                last_cross_ct=epoch_ct(cross_t, "%H:%M") if cross_t else None)


def cvd_gate_state(bars, level, cvd, gate_cfg=None):
    """Dispatch on gate_cfg["mode"]: "z30" (origin-free, default in DEFAULT_CONFIG) or "fixed" (legacy level)."""
    g = gate_cfg or {}
    if g.get("mode") == "z30":
        return cvd_gate_z30(bars, cvd, g.get("window_min", 30), g.get("lookback_min", 240),
                            g.get("min_samples", 60), g.get("z_thr", 1.0))
    return cvd_gate_fixed(bars, level, cvd)


def level_states(levels, price, closes5):
    last5 = closes5[-1][1] if closes5 else None
    out = []
    for lv in levels:
        px = float(lv["px"]); d = lv.get("dir", "above")
        taken_now = price is not None and ((price > px) if d == "above" else (price < px))
        taken_close = last5 is not None and ((last5 > px) if d == "above" else (last5 < px))
        status = "confirmed" if taken_close else "touched" if taken_now else "pending"
        dist = None if price is None else round(price - px, 2)
        out.append(dict(name=lv.get("name"), px=px, kind=lv.get("kind", "level"), dir=d,
                        bias=lv.get("bias", "neutral"), note=lv.get("note"), status=status,
                        price_vs="above" if dist and dist > 0 else "below" if dist and dist < 0 else "at",
                        dist=dist))
    return out


def trigger_state(trig, price, closes5):
    if not trig: return None
    px = float(trig["px"]); d = trig.get("dir", "above")
    last5 = closes5[-1][1] if closes5 else None
    ok = lambda v: v is not None and ((v > px) if d == "above" else (v < px))
    state = "confirmed" if ok(last5) else "pressing" if ok(price) else "pending"
    return dict(px=px, dir=d, label=trig.get("label"), tf_min=trig.get("tf_min", 5), state=state, last_5m_close=last5)


def nq_relative(nq_bars, es_bars, nq_gate):
    """NQ vs ES % change from the same start bar, for 30m / 60m / session windows."""
    if not nq_bars or not es_bars:
        return None
    es_close = {b["t"]: b["c"] for b in es_bars}
    common = [(b["t"], b["c"]) for b in nq_bars if b["t"] in es_close]
    if len(common) < 2: return None
    def window(mins):
        end_t = common[-1][0]
        cand = [x for x in common if x[0] >= end_t - 60 * mins] if mins else common
        if len(cand) < 2: return None
        t0, n0 = cand[0]; t1, n1 = cand[-1]
        nq_pct = (n1 / n0 - 1) * 100; es_pct = (es_close[t1] / es_close[t0] - 1) * 100
        return dict(nq_pct=round(nq_pct, 3), es_pct=round(es_pct, 3), rs=round(nq_pct - es_pct, 3))
    w = {"30m": window(30), "60m": window(60), "session": window(0)}
    lead = None
    if w["30m"]: lead = "NQ leading" if w["30m"]["rs"] > 0.02 else "NQ lagging" if w["30m"]["rs"] < -0.02 else "in line"
    last = nq_bars[-1]["c"]
    return dict(last=last, windows=w, lead=lead,
                gate=dict(level=nq_gate, side=None if nq_gate is None else ("above" if last > nq_gate else "below" if last < nq_gate else "at")))


def bias_rule(cvd_gate, price, vwap, nq_rel):
    """Transparent 3-input vote; descriptive, not a signal."""
    votes = []
    lean = cvd_gate.get("lean")
    if "lean" not in cvd_gate: votes.append(("cvd>gate", cvd_gate["side"] == "above"))   # legacy gate dict
    elif lean is not None: votes.append(("cvd30>0" if cvd_gate.get("mode") == "z30" else "cvd>gate", lean == "up"))
    if price is not None and vwap is not None: votes.append(("px>vwap", price > vwap))
    if nq_rel and nq_rel.get("windows", {}).get("30m"): votes.append(("nq_rs30>0", nq_rel["windows"]["30m"]["rs"] > 0))
    up = sum(1 for _, v in votes if v)
    label = "BULL" if up == len(votes) and votes else "BEAR" if up == 0 and votes else "MIXED"
    return dict(label=label, votes=[dict(name=n, up=v) for n, v in votes], rule="all inputs up = BULL, all down = BEAR, else MIXED")


# ----------------------------------------------------------------------------- IO helpers
def atomic_write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)


def load_config(state_dir):
    p = os.path.join(state_dir, "tape-config.json")
    if not os.path.exists(p):
        os.makedirs(state_dir, exist_ok=True); atomic_write(p, DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(p, encoding="utf-8") as f: cfg = json.load(f)
    except Exception:
        return json.loads(json.dumps(DEFAULT_CONFIG))
    merged = json.loads(json.dumps(DEFAULT_CONFIG)); merged.update(cfg)
    for k in ("cvd_gate", "depth"):                       # nested blocks merge key-by-key over the defaults
        if isinstance(cfg.get(k), dict): merged[k] = {**DEFAULT_CONFIG[k], **cfg[k]}
    return merged


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except Exception: return None


# ----------------------------------------------------------------------------- NQ (read-only IB)
class NQFeed:
    """Streams NQ 1-min bars (keepUpToDate) through a read-only IB connection (clientId 98)."""

    def __init__(self):
        self.ib = None; self.bars = None; self.status = "down"; self.error = None; self.next_try = 0

    def poll(self):
        now = time.time()
        if self.ib is not None and self.ib.isConnected(): return
        if now < self.next_try: return
        self.next_try = now + 30
        try:
            from ib_async import IB, Future
            ib = IB()
            for p in IB_PORTS:
                try: ib.connect("127.0.0.1", p, clientId=NQ_CLIENT_ID, readonly=True, timeout=6); break
                except Exception as e: self.error = f"port {p}: {type(e).__name__}"
            if not ib.isConnected(): self.status = "down"; return
            c = ib.qualifyContracts(Future("NQ", NQ_EXPIRY, "CME"))[0]
            self.bars = ib.reqHistoricalData(c, endDateTime="", durationStr="1 D", barSizeSetting="1 min",
                                             whatToShow="TRADES", useRTH=False, formatDate=2, keepUpToDate=True)
            self.ib = ib; self.status = "ok"; self.error = None
        except Exception as e:
            self.status = "down"; self.error = f"{type(e).__name__}"

    def pump(self, seconds):
        if self.ib is not None and self.ib.isConnected(): self.ib.sleep(seconds)
        else: time.sleep(seconds)

    def read(self):
        if self.status != "ok" or not self.bars: return [], None
        out = [dict(t=int(b.date.timestamp()) // 60 * 60, c=float(b.close)) for b in self.bars if b.close]
        return out, (out[-1]["t"] + 60 if out else None)


# ----------------------------------------------------------------------------- L2 / DOM depth (sibling CSV)
DEPTH_LEVELS = 10


def depth_path(rec_dir, sym, day):
    return os.path.join(rec_dir, f"{sym}_depth_{day:%Y%m%d}.csv")


def _depth_rows(path, n):
    """Last n complete rows of the depth CSV as dicts (header read separately; tail read only)."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            header = f.readline().decode().strip().split(","); hdr_end = f.tell()
            start = max(hdr_end, size - 700 * (n + 2))
            f.seek(start)
            chunk = f.read()
    except OSError:
        return []
    end = chunk.rfind(b"\n")
    if end < 0: return []
    lines = chunk[:end + 1].decode(errors="replace").splitlines()
    if start > hdr_end and lines: lines = lines[1:]               # first line may be cut mid-row
    out = []
    for row in csv.DictReader(lines[-n:], fieldnames=header):
        out.append(row)
    return out


def _ladder(row, side, k=DEPTH_LEVELS):
    p, z = ("bp", "bs") if side == "bid" else ("ap", "as")
    out = []
    for i in range(1, k + 1):
        try:
            px = float(row.get(f"{p}{i}") or "nan"); sz = int(float(row.get(f"{z}{i}") or 0))
        except ValueError:
            continue
        if sz > 0 and not math.isnan(px):
            if out and out[-1][0] == px: out[-1] = (px, out[-1][1] + sz)   # IB can list one price on two rows: one ladder rung per price
            else: out.append((px, sz))
    return out


def _imb(bids, asks, k):
    b = sum(z for _, z in bids[:k]); a = sum(z for _, z in asks[:k])
    return round((b - a) / (b + a), 3) if (b + a) else None


def depth_snapshot(rec_dir, sym, day, cfg, now_epoch):
    """Top-of-book imbalance + large resting-order outliers from the 1 s depth CSV. Read-only, no orders.

    imb_* = (bid lots - ask lots) / (bid lots + ask lots) over the top 1 / 5 / 10 levels, in [-1, +1];
    imb_avg = mean of imb_5 over the last avg_n snapshots (about avg_n seconds).
    big     = levels whose size >= max(big_min_lots, big_mult x median level size on the visible book);
              seen_s = how many consecutive snapshots (about seconds) that price held >= half that size.
    status  = ok | stale | off (no depth file) | no_permission (IB refused depth) | down.
    """
    dc = {**DEFAULT_CONFIG["depth"], **(cfg.get("depth") or {})}
    st = read_json(os.path.join(rec_dir, "depth-status.json")) or {}
    path = depth_path(rec_dir, sym, day)
    base = dict(status="off", age_s=None, levels=0, bid_lots=None, ask_lots=None, imb_top=None, imb_5=None,
                imb_10=None, imb_avg=None, spread=None, bids=[], asks=[], big=[], note=None)
    if st.get("state") in ("no_permission", "down") and not os.path.exists(path):
        base["status"] = st["state"]; base["note"] = (st.get("reason") or "")[:120] or None
        return base
    rows = _depth_rows(path, max(int(dc["avg_n"]), 2) + 1) if os.path.exists(path) else []
    if not rows:
        if st.get("state") in ("no_permission", "down"): base["status"] = st["state"]; base["note"] = (st.get("reason") or "")[:120] or None
        return base
    last = rows[-1]
    try: ts = iso_to_epoch(last["ts_utc"])
    except (KeyError, ValueError): return base
    bids = _ladder(last, "bid", int(dc["levels"])); asks = _ladder(last, "ask", int(dc["levels"]))
    age = round(now_epoch - ts, 1)
    out = dict(base)
    out.update(status="ok" if age <= float(dc["stale_s"]) else "stale", age_s=age, levels=min(len(bids), len(asks)),
               bid_lots=sum(z for _, z in bids), ask_lots=sum(z for _, z in asks),
               imb_top=_imb(bids, asks, 1), imb_5=_imb(bids, asks, 5), imb_10=_imb(bids, asks, 10),
               spread=round(asks[0][0] - bids[0][0], 2) if bids and asks else None,
               bids=[dict(px=p, lots=z) for p, z in bids], asks=[dict(px=p, lots=z) for p, z in asks])
    avgs = []
    for r in rows:
        b = _ladder(r, "bid", int(dc["levels"])); a = _ladder(r, "ask", int(dc["levels"]))
        v = _imb(b, a, 5)
        if v is not None: avgs.append(v)
    out["imb_avg"] = round(sum(avgs) / len(avgs), 3) if avgs else None
    sizes = sorted(z for _, z in bids + asks)
    if sizes:
        med = sizes[len(sizes) // 2]
        thr = max(float(dc["big_min_lots"]), float(dc["big_mult"]) * med)
        mid = (bids[0][0] + asks[0][0]) / 2 if bids and asks else None
        hist = [(_ladder(r, "bid", int(dc["levels"])), _ladder(r, "ask", int(dc["levels"]))) for r in rows]
        big = []
        for side, lad in (("bid", bids), ("ask", asks)):
            for px, z in lad:
                if z < thr: continue
                seen = 0
                for hb, ha in reversed(hist):
                    m = dict(hb if side == "bid" else ha)
                    if m.get(px, 0) >= z / 2: seen += 1
                    else: break
                big.append(dict(side=side, px=px, lots=z, mult=round(z / med, 1) if med else None,
                                away=round(abs(px - mid), 2) if mid is not None else None, seen_s=seen))
        out["big"] = sorted(big, key=lambda x: -x["lots"])[:6]
    return out


# ----------------------------------------------------------------------------- one pass
def build_snapshot(agg, cfg, hb, nq_bars, nq_status, now_epoch, rec_file, depth=None):
    bars = sorted_bars(agg)
    price = agg.last; vwap = agg.vwap
    series = [dict(t=b["t"], o=b["o"], h=b["h"], l=b["l"], c=b["c"], vol=b["vol"], delta=b["delta"], cvd=b["cvd"])
              for b in bars[-SERIES_MAX:]]
    gate_cfg = cfg.get("cvd_gate") or {}
    gate = cvd_gate_state(bars, gate_cfg.get("level", 0), agg.cvd, gate_cfg) if bars else None
    if gate: gate["label"] = gate_cfg.get("label", "CVD gate"); gate["note"] = gate_cfg.get("note")
    closes5 = five_min_closes(bars, now_epoch)
    nq_rel = nq_relative(nq_bars, bars, cfg.get("nq_gate")) if nq_bars else None
    tot = max(1, agg.n_bidask + agg.n_tick)
    hb_age = None
    if hb and hb.get("written_utc"):
        hb_age = round(now_epoch - dt.datetime.fromisoformat(hb["written_utc"]).timestamp(), 1)
    last_tick_age = round(now_epoch - agg.last_ts, 1) if agg.last_ts else None
    return {
        "schema": 1,
        "as_of_epoch": round(now_epoch, 1), "as_of_ct": iso_ct(now_epoch), "interval_s": cfg.get("interval_s", 5),
        "live_legal": False, "size": 0,
        "session": dict(trading_day=str(trading_day(dt.datetime.fromtimestamp(now_epoch, UTC))),
                        since_ct=iso_ct(agg.first_ts) if agg.first_ts else None, trades=agg.n, lots=agg.vol,
                        file=os.path.basename(rec_file) if rec_file else None),
        "recorder": dict(state=(hb or {}).get("state", "no heartbeat"), heartbeat_age_s=hb_age,
                         last_tick_age_s=last_tick_age, reconnects=(hb or {}).get("reconnects"),
                         connected_port=(hb or {}).get("connected_port"), contract=(hb or {}).get("contract")),
        "basis": dict(label="bid/ask" if agg.n_bidask >= agg.n_tick else "tick-rule",
                      bidask_pct=round(100 * agg.n_bidask / tot, 1), bidask_trades=agg.n_bidask, tickrule_trades=agg.n_tick),
        "price": dict(last=price, bid=agg.bid, ask=agg.ask, vwap=None if vwap is None else round(vwap, 2),
                      hi=agg.hi, lo=agg.lo),
        "cvd": dict(value=agg.cvd, since_ct=iso_ct(agg.first_ts) if agg.first_ts else None),
        "gate_cvd": gate,
        "series_1m": series,
        "legs": zigzag_legs(bars, float(cfg.get("leg_swing_pts", 3.0))),
        "lots_per_min": lots_per_min(bars, now_epoch),
        "levels": level_states(cfg.get("levels", []), price, closes5),
        "trigger": trigger_state(cfg.get("trigger"), price, closes5),
        "bias": bias_rule(gate, price, vwap, nq_rel) if gate else None,
        "depth": depth,
        "nq": dict(status=nq_status, rel=nq_rel, series=[dict(t=b["t"], c=b["c"]) for b in nq_bars[-SERIES_MAX:]],
                   as_of_epoch=(nq_bars[-1]["t"] + 60) if nq_bars else None, interval_s=60),
    }


def one_pass(agg, state_dir, rec_dir, nq=None, now=None):
    now = now or time.time()
    cfg = load_config(state_dir)
    day = trading_day(dt.datetime.fromtimestamp(now, UTC))
    hb = read_json(os.path.join(rec_dir, "heartbeat.json"))
    sym = (hb or {}).get("contract") or "ESZ6"
    path = os.path.join(rec_dir, f"{sym}_{day:%Y%m%d}.csv")
    if getattr(agg, "day", None) != day: agg.reset(); agg.day = day
    read_new_rows(path, agg)
    nq_bars, nq_status = ([], "off")
    if nq is not None:
        nq.poll(); nq_bars, _ = nq.read(); nq_status = nq.status
    try: depth = depth_snapshot(rec_dir, sym, day, cfg, now)
    except Exception as e: depth = dict(status="down", note=type(e).__name__)
    snap = build_snapshot(agg, cfg, hb, nq_bars, nq_status, now, path if os.path.exists(path) else None, depth)
    os.makedirs(state_dir, exist_ok=True)
    atomic_write(os.path.join(state_dir, "flow-latest.json"), snap)
    hist = dict(t=snap["as_of_ct"], px=snap["price"]["last"], cvd=agg.cvd, lpm5=snap["lots_per_min"]["avg5"],
                gate=(snap["gate_cvd"] or {}).get("side"), trig=(snap["trigger"] or {}).get("state"),
                nq=(snap["nq"]["rel"] or {}).get("last") if snap["nq"]["rel"] else None)
    with open(os.path.join(state_dir, f"flow-history-{day}.jsonl"), "a") as f: f.write(json.dumps(hist) + "\n")
    return snap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true"); ap.add_argument("--no-nq", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--state-dir", default=STATE_DIR); ap.add_argument("--rec-dir", default=REC_DIR)
    a = ap.parse_args()
    if a.selftest:
        import pytest; sys.exit(pytest.main([os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_flow_snapshot.py"), "-q"]))
    agg = Aggregator(); nq = None if (a.once or a.no_nq) else NQFeed()
    if a.once:
        s = one_pass(agg, a.state_dir, a.rec_dir, None)
        print(json.dumps({k: s[k] for k in ("as_of_ct", "session", "recorder", "basis", "price", "cvd", "lots_per_min", "trigger", "bias")}, indent=1)); return
    print(f"flow_snapshot loop: rec={a.rec_dir} state={a.state_dir} nq={'on' if nq else 'off'}", flush=True)
    while True:
        t0 = time.time(); interval = 5
        try:
            s = one_pass(agg, a.state_dir, a.rec_dir, nq); interval = s["interval_s"]
        except Exception as e:
            print("pass failed:", type(e).__name__, e, flush=True)
        left = max(0.5, interval - (time.time() - t0))
        if nq: nq.pump(left)
        else: time.sleep(left)


if __name__ == "__main__":
    main()
