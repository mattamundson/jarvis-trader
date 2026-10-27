import csv, datetime as dt, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flow_snapshot as fs

UTC = dt.timezone.utc
FIELDS = ["ts_utc", "ts_ct", "price", "size", "bid", "ask", "side", "delta", "cvd", "quote_age_ms", "basis"]


def mk_rows(start, pxs, size=2, basis="bidask"):
    rows, cvd = [], 0
    for i, px in enumerate(pxs):
        t = start + dt.timedelta(seconds=15 * i)
        d = size if i % 3 else -size
        cvd += d
        rows.append(dict(ts_utc=t.isoformat(timespec="milliseconds"), ts_ct=t.astimezone(fs.CT).isoformat(timespec="milliseconds"),
                         price=px, size=size, bid=px - .25, ask=px, side="A" if d > 0 else "B", delta=d, cvd=cvd, quote_age_ms=5, basis=basis))
    return rows


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, FIELDS); w.writeheader(); w.writerows(rows)


def test_zigzag_legs_and_open_leg():
    start = dt.datetime(2026, 10, 27, 4, 0, tzinfo=UTC)
    # up 8 pts, down 5, up 4 in one-minute steps
    pxs = [7700 + i for i in range(9)] + [7708 - i for i in range(1, 6)] + [7703 + i for i in range(1, 5)]
    agg = fs.Aggregator()
    for r in mk_rows(start, [p for p in pxs for _ in range(4)]): agg.ingest(r)   # 4 trades per minute
    bars = fs.sorted_bars(agg)
    legs = fs.zigzag_legs(bars, 3.0)
    assert [g["dir"] for g in legs] == ["up", "down", "up"], legs
    assert legs[0]["pts"] == 8 and legs[1]["pts"] == -5
    assert legs[-1]["open"] is True and legs[0]["open"] is False
    assert all(g["vol"] > 0 and g["lpm"] > 0 for g in legs)


def test_gate_levels_and_trigger():
    bars = [dict(t=60 * i, o=1, h=1, l=1, c=1, vol=1, delta=0, n=1, cvd=c) for i, c in enumerate([100, 600, 520, 700])]
    g = fs.cvd_gate_state(bars, 540, 700)
    assert g["side"] == "above" and g["dist"] == 160 and g["last_cross_t"] == 180
    closes5 = [(0, 7725.0), (300, 7726.0)]
    st = fs.level_states([dict(name="T", px=7725.75, dir="above"), dict(name="S", px=7723, dir="below"), dict(name="U", px=7730, dir="above")], 7726.5, closes5)
    assert [s["status"] for s in st] == ["confirmed", "pending", "pending"]
    tr = fs.trigger_state(dict(px=7725.75, dir="above"), 7725.5, [(0, 7725.0)])
    assert tr["state"] == "pending"
    tr = fs.trigger_state(dict(px=7725.75, dir="above"), 7726.0, [(0, 7725.0)])
    assert tr["state"] == "pressing"


def test_lots_per_min_counts_empty_minutes():
    now = 600.0
    bars = [dict(t=540, vol=50), dict(t=300, vol=100)]
    r = fs.lots_per_min(bars, now)
    assert r["last"] == 50 and r["avg5"] == (50 + 100) / 5 and r["peak"] == 100


def test_nq_relative_and_bias():
    es = [dict(t=60 * i, c=7700 + i) for i in range(40)]
    nq = [dict(t=60 * i, c=29000 + 10 * i) for i in range(40)]
    rel = fs.nq_relative(nq, es, 29300.0)
    assert rel["lead"] == "NQ leading" and rel["gate"]["side"] == "above"
    b = fs.bias_rule(dict(side="above"), 7739.0, 7730.0, rel)
    assert b["label"] == "BULL"
    b = fs.bias_rule(dict(side="below"), 7739.0, 7730.0, rel)
    assert b["label"] == "MIXED"


def test_incremental_reader_ignores_partial_line_and_one_pass(tmp_path):
    rec = tmp_path / "rec"; st = tmp_path / "state"; rec.mkdir()
    now = dt.datetime(2026, 10, 27, 4, 20, tzinfo=UTC)          # 23:20 CT Mon -> trading day 10-27
    rows = mk_rows(now - dt.timedelta(minutes=30), [7720 + (i % 6) for i in range(120)])
    p = rec / "ESZ6_20261027.csv"; write_csv(p, rows)
    with open(p, "a") as f: f.write("2026-10-27T04:19:59.000+00:00,partial")      # no newline -> must be ignored
    (rec / "heartbeat.json").write_text(json.dumps(dict(state="recording", written_utc=now.isoformat(), contract="ESZ6", reconnects=0)))
    agg = fs.Aggregator()
    snap = fs.one_pass(agg, str(st), str(rec), None, now=now.timestamp())
    assert snap["session"]["trades"] == 120 and snap["live_legal"] is False and snap["size"] == 0
    assert snap["basis"]["label"] == "bid/ask" and snap["recorder"]["state"] == "recording"
    assert os.path.exists(st / "flow-latest.json") and any(n.startswith("flow-history-") for n in os.listdir(st))
    # appending the rest of the line later is picked up exactly once
    with open(p, "a") as f: f.write(",,,,,,,\n")
    fs.read_new_rows(str(p), agg); assert agg.n == 120
    # no private fields anywhere in the snapshot
    blob = json.dumps(snap).lower()
    for bad in ("pnl", "p&l", "account", "position", "equity", "balance"):
        assert bad not in blob, bad


def test_day_rollover_resets():
    agg = fs.Aggregator(); agg.ingest(mk_rows(dt.datetime(2026, 10, 27, 4, 0, tzinfo=UTC), [7700])[0])
    assert agg.n == 1
    agg.reset(); assert agg.n == 0 and not agg.bars


# ----------------------------------------------------------------------------- CVD gate retune (z30)
def _cvd_bars(deltas_per_min, start=0):
    """One bar per minute; deltas_per_min = signed lots per minute. CVD starts at 0 (daily reset)."""
    bars, cvd = [], 0
    for i, d in enumerate(deltas_per_min):
        cvd += d
        bars.append(dict(t=start + 60 * i, o=1, h=1, l=1, c=1, vol=abs(d), delta=d, n=1, cvd=cvd))
    return bars


def test_z30_is_origin_free_and_decisive():
    import random
    rnd = random.Random(7)
    quiet = [rnd.choice([-3, -2, -1, 1, 2, 3]) for _ in range(150)]
    burst = quiet + [40] * 30                                  # 30 minutes of heavy buying at the end
    b = _cvd_bars(burst)
    g = fs.cvd_gate_z30(b, b[-1]["cvd"])
    assert g["state"] == "ok" and g["side"] == "above" and g["lean"] == "up" and g["z"] >= 1.0, g
    assert g["dist"] == b[-1]["cvd"] - b[-31]["cvd"] and g["level"] == b[-31]["cvd"]
    # shifting the whole CVD by a constant origin (what a reset does) changes nothing
    shifted = [dict(x, cvd=x["cvd"] + 5000) for x in b]
    g2 = fs.cvd_gate_z30(shifted, shifted[-1]["cvd"])
    assert (g2["side"], g2["z"], g2["dist"]) == (g["side"], g["z"], g["dist"])
    # mirror image -> below
    m = _cvd_bars([-x for x in burst]); gm = fs.cvd_gate_z30(m, m[-1]["cvd"])
    assert gm["side"] == "below" and gm["lean"] == "down" and gm["z"] == -g["z"]
    # fixed gate at 540 on the same series is simply a different, origin-dependent answer
    assert fs.cvd_gate_state(b, 540, b[-1]["cvd"], dict(mode="fixed"))["mode"] == "fixed"


def test_z30_warming_and_flat():
    b = _cvd_bars([5] * 20)
    g = fs.cvd_gate_z30(b, b[-1]["cvd"])
    assert g["state"] == "warming" and g["side"] == "at" and g["z"] is None and g["lean"] is None
    flat = _cvd_bars([0] * 200); g = fs.cvd_gate_z30(flat, 0)
    assert g["state"] == "warming" and g["side"] == "at"        # zero scale never divides
    assert fs.cvd_gate_z30([], 0) is None


def test_z30_gaps_are_forward_filled_and_bias_vote():
    bars = _cvd_bars([2] * 100)
    bars = [x for i, x in enumerate(bars) if i % 4 != 3]        # missing minutes
    g = fs.cvd_gate_z30(bars, bars[-1]["cvd"], min_samples=10)
    assert g["state"] == "ok" and g["n"] >= 10
    nq = dict(windows={"30m": dict(rs=0.1)})
    b = fs.bias_rule(dict(side="at", lean=None, mode="z30"), 7739.0, 7730.0, nq)
    assert [v["name"] for v in b["votes"]] == ["px>vwap", "nq_rs30>0"] and b["label"] == "BULL"
    b = fs.bias_rule(dict(side="below", lean="down", mode="z30"), 7739.0, 7730.0, nq)
    assert b["label"] == "MIXED" and b["votes"][0]["name"] == "cvd30>0"


def test_config_deep_merges_gate_defaults(tmp_path):
    (tmp_path / "tape-config.json").write_text(json.dumps(dict(cvd_gate=dict(level=540, label="old"))))
    cfg = fs.load_config(str(tmp_path))
    assert cfg["cvd_gate"]["mode"] == "z30" and cfg["cvd_gate"]["level"] == 540 and cfg["cvd_gate"]["label"] == "old"
    assert cfg["depth"]["levels"] == 10


# ----------------------------------------------------------------------------- depth
def write_depth(path, snaps):
    """snaps: list of (epoch, bids[(px,sz)], asks[(px,sz)])"""
    fields = ["ts_utc", "nb", "na"] + [f"{k}{i}" for k in ("bp", "bs", "ap", "as") for i in range(1, 11)]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fields); w.writeheader()
        for t, bids, asks in snaps:
            r = dict(ts_utc=dt.datetime.fromtimestamp(t, UTC).isoformat(timespec="milliseconds"), nb=len(bids), na=len(asks))
            for i in range(10):
                b = bids[i] if i < len(bids) else ("", ""); a = asks[i] if i < len(asks) else ("", "")
                r[f"bp{i+1}"], r[f"bs{i+1}"], r[f"ap{i+1}"], r[f"as{i+1}"] = b[0], b[1], a[0], a[1]
            w.writerow(r)


def test_depth_imbalance_and_big_resting_orders(tmp_path):
    now = dt.datetime(2026, 10, 27, 15, 0, tzinfo=UTC).timestamp()
    bids = [(7700.0 - 0.25 * i, 20) for i in range(10)]; bids[3] = (bids[3][0], 400)       # 400-lot wall on the bid
    asks = [(7700.25 + 0.25 * i, 10) for i in range(10)]
    snaps = [(now - 59 + i, bids, asks) for i in range(60)]
    path = tmp_path / "ESZ6_depth_20261027.csv"; write_depth(path, snaps)
    day = dt.date(2026, 10, 27)
    d = fs.depth_snapshot(str(tmp_path), "ESZ6", day, fs.DEFAULT_CONFIG, now)
    assert d["status"] == "ok" and d["levels"] == 10 and d["spread"] == 0.25
    assert d["imb_top"] == round((20 - 10) / 30, 3) and d["imb_10"] > 0.3 and d["imb_avg"] > 0.3
    assert len(d["big"]) == 1 and d["big"][0]["side"] == "bid" and d["big"][0]["lots"] == 400 and d["big"][0]["seen_s"] == 60
    assert d["big"][0]["mult"] == 20.0
    # stale data is flagged, not hidden
    d = fs.depth_snapshot(str(tmp_path), "ESZ6", day, fs.DEFAULT_CONFIG, now + 120)
    assert d["status"] == "stale"


def test_depth_off_and_no_permission(tmp_path):
    day = dt.date(2026, 10, 27); now = 1_790_000_000.0
    assert fs.depth_snapshot(str(tmp_path), "ESZ6", day, fs.DEFAULT_CONFIG, now)["status"] == "off"
    (tmp_path / "depth-status.json").write_text(json.dumps(dict(state="no_permission", reason="IB refused depth (market data permission or request limit)")))
    d = fs.depth_snapshot(str(tmp_path), "ESZ6", day, fs.DEFAULT_CONFIG, now)
    assert d["status"] == "no_permission" and "refused" in d["note"] and d["bids"] == []


def test_snapshot_carries_depth_without_private_words(tmp_path):
    rec = tmp_path / "rec"; st = tmp_path / "state"; rec.mkdir()
    now = dt.datetime(2026, 10, 27, 4, 20, tzinfo=UTC)
    write_csv(rec / "ESZ6_20261027.csv", mk_rows(now - dt.timedelta(minutes=120), [7720 + (i % 6) for i in range(480)]))
    bids = [(7720.0 - 0.25 * i, 15) for i in range(10)]; asks = [(7720.25 + 0.25 * i, 15) for i in range(10)]
    write_depth(rec / "ESZ6_depth_20261027.csv", [(now.timestamp() - 5 + i, bids, asks) for i in range(5)])
    (rec / "heartbeat.json").write_text(json.dumps(dict(state="recording", written_utc=now.isoformat(), contract="ESZ6")))
    snap = fs.one_pass(fs.Aggregator(), str(st), str(rec), None, now=now.timestamp())
    assert snap["depth"]["status"] == "ok" and snap["depth"]["imb_top"] == 0.0
    assert snap["gate_cvd"]["mode"] == "z30" and snap["gate_cvd"]["state"] == "ok"
    blob = json.dumps(snap).lower()
    for bad in ("pnl", "p&l", "account", "position", "equity", "balance", "fill", "cash", "margin", "holding"):
        assert bad not in blob, bad


def test_ladder_merges_repeated_price_rows():
    row = {"bp1": "7710.25", "bs1": "10", "bp2": "7710.25", "bs2": "5", "bp3": "7710.0", "bs3": "7", "bp4": "", "bs4": ""}
    assert fs._ladder(row, "bid") == [(7710.25, 15), (7710.0, 7)]
