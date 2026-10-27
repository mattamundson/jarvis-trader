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
