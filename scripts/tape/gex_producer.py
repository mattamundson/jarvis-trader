"""ZeroGEX ES gamma-levels producer for the /tape GEX panel (stdlib only).

Fetches the public free page https://zerogex.io/es-gamma-levels (delayed ~15 min by the vendor),
reads the levels object embedded in the page payload and writes <tape state>/gex-latest.json.

  python gex_producer.py --once            one fetch, then exit (what the scheduled task runs)
  python gex_producer.py --loop 600        keep fetching every 600 s
  python gex_producer.py --selftest

as-of is the vendor snapshot time, never our pull time. The file carries levels and gate numbers only.
If a fetch fails the last good levels are kept and fetch_ok=false, age and stale keep ticking.
`pin` is not published in the page payload, so it is written as null rather than invented.
"""
from __future__ import annotations
import argparse, json, os, re, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")
URL = "https://zerogex.io/es-gamma-levels"
SOURCE = "ZeroGEX ES free (~15m delayed)"
STALE_MIN = 35          # vendor snapshot older than this = stale (15m delay + one missed refresh + slack)
HIST_KEEP = 24
VEL_WINDOW_MIN = 120


def state_dir() -> Path:
    return Path(os.environ.get("TAPE_STATE_DIR") or (Path.home() / "tape" / "state"))


def fetch(url: str = URL, timeout: float = 20.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (tape-gex-producer)", "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _num(m):
    return float(m.group(1)) if m else None


def parse(html: str) -> dict | None:
    """Pull levels out of the page's embedded payload. Returns None when the page has no levels."""
    s = html.replace('\\"', '"')
    m = re.search(r'"levels":\{"symbol":"ES","gammaFlip":(-?[\d.]+),"callWall":(-?[\d.]+),"putWall":(-?[\d.]+),"maxPain":(-?[\d.]+),"asOf":"([^"]+)"', s)
    if not m:
        return None
    flip, cw, pw, mp = (float(m.group(i)) for i in range(1, 5))
    asof = datetime.fromisoformat(m.group(5)).astimezone(CT)
    net = _num(re.search(r'"netGexAtSpot":(-?[\d.eE+]+)', s))
    spot = _num(re.search(r'"quote":\{"close":(-?[\d.]+)', s))
    return dict(asof=asof, flip=flip, call_wall=cw, put_wall=pw, max_pain=mp, net_gex=net, spot=spot)


def fmt_net(v: float | None) -> str | None:
    if v is None:
        return None
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1e9:
        return f"{sign}{a / 1e9:.2f}B"
    if a >= 1e6:
        return f"{sign}{a / 1e6:.2f}M"
    return f"{sign}{a:.0f}"


def _wall(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def _parse_wall(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=CT)


def build(prev: dict | None, got: dict | None, now: datetime) -> dict:
    prev = prev or {}
    if got is None:  # keep last good levels, flag the failure
        out = dict(prev)
        out["fetch_ok"] = False
    else:
        out = dict(
            asof_ct=_wall(got["asof"]), spot=got["spot"], call_wall=got["call_wall"], put_wall=got["put_wall"],
            flip=got["flip"], max_pain=got["max_pain"], pin=None, net_gex=fmt_net(got["net_gex"]),
            source=SOURCE, fetch_ok=True,
        )
        hist = [h for h in (prev.get("history_today") or []) if str(h.get("asof_ct", ""))[:10] == out["asof_ct"][:10]]
        if not hist or hist[-1].get("asof_ct") != out["asof_ct"]:
            hist.append(dict(asof_ct=out["asof_ct"], flip=out["flip"], pin=out["pin"], put_wall=out["put_wall"]))
        out["history_today"] = hist[-HIST_KEEP:]
    out["pulled_ct"] = _wall(now)
    asof = out.get("asof_ct")
    if asof:
        age = max(0, int((now - _parse_wall(asof)).total_seconds() // 60))
        out["age_min"] = age
        out["stale"] = age > STALE_MIN
        # flip velocity: oldest sample inside the window vs the newest, per hour
        hist = out.get("history_today") or []
        cur = _parse_wall(asof)
        ref = None
        for h in hist:
            if h.get("flip") is None:
                continue
            dm = (cur - _parse_wall(h["asof_ct"])).total_seconds() / 60
            if 20 <= dm <= VEL_WINDOW_MIN:
                ref = (h, dm)
                break
        if ref:
            out["flip_vel_pts_hr"] = round((out["flip"] - ref[0]["flip"]) / (ref[1] / 60), 1)
            out["flip_vel_since"] = ref[0]["asof_ct"][11:16]
        else:
            out["flip_vel_pts_hr"] = None
            out["flip_vel_since"] = None
    return out


def write_atomic(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def run_once(sd: Path | None = None, html: str | None = None) -> dict:
    sd = sd or state_dir()
    path = sd / "gex-latest.json"
    prev = None
    try:
        prev = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    got = None
    try:
        got = parse(html if html is not None else fetch())
    except Exception as e:  # network / parse trouble: keep last good
        print(f"gex fetch failed: {type(e).__name__}", file=sys.stderr)
    out = build(prev, got, datetime.now(CT))
    if out.get("asof_ct"):
        write_atomic(path, out)
    return out


SAMPLE = ('x\\"levels\\":{\\"symbol\\":\\"ES\\",\\"gammaFlip\\":7776,\\"callWall\\":8038.5,\\"putWall\\":7686.75,'
          '\\"maxPain\\":7716.75,\\"asOf\\":\\"2026-10-26T19:59:00+00:00\\"}} y \\"quote\\":{\\"close\\":7721.75,\\"s\\":1}'
          ' \\"netGexAtSpot\\":-34601389733.3049')


def selftest() -> int:
    g = parse(SAMPLE)
    assert g and g["flip"] == 7776 and g["call_wall"] == 8038.5 and g["spot"] == 7721.75, g
    assert _wall(g["asof"]) == "2026-10-26 14:59", _wall(g["asof"])
    assert fmt_net(g["net_gex"]) == "-34.60B"
    now = datetime(2026, 10, 26, 15, 10, tzinfo=CT)
    o1 = build(None, g, now)
    assert o1["age_min"] == 11 and o1["stale"] is False and o1["flip_vel_pts_hr"] is None and "$" not in json.dumps(o1)
    prev = dict(o1, history_today=[dict(asof_ct="2026-10-26 13:59", flip=7772.0, pin=None, put_wall=7686.75)])
    o2 = build(prev, g, now)
    assert o2["flip_vel_pts_hr"] == 4.0 and o2["flip_vel_since"] == "13:59", o2
    o3 = build(o2, None, datetime(2026, 10, 26, 16, 5, tzinfo=CT))
    assert o3["fetch_ok"] is False and o3["stale"] is True and o3["age_min"] == 66
    assert parse("<html>nothing</html>") is None
    print("selftest ok")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", type=int, default=0)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    while True:
        o = run_once()
        print(f"gex {o.get('asof_ct')} flip={o.get('flip')} ok={o.get('fetch_ok')} age={o.get('age_min')}m", flush=True)
        if not a.loop:
            break
        time.sleep(a.loop)
