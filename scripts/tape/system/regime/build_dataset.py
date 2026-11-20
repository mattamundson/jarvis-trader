#!/usr/bin/env python3
"""Build labeled ES RTH sessions with pre-open predictors.

Reads (read-only outside this folder):
  /workspace/tape/ovn/es_1m_dbn.parquet
  /workspace/tape/system/data/es_yahoo_7d_1m.json
  /workspace/tape/system/data/event_calendar.json
  regime/data/vix_daily_yahoo.json
  regime/data/vix9d_daily_yahoo.json
  optional short GEX history under /workspace/tape/state/gex-history-*.jsonl

Writes only under /workspace/tape/system/regime/.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REGIME = Path(__file__).resolve().parent
ROOT = REGIME.parent
sys.path.insert(0, str(ROOT))
from lib.timeutil import CT  # noqa: E402

from labels import LabelParams, VARIANTS, label_session  # noqa: E402
from features_extra import (  # noqa: E402
    dalton_open_type,
    one_timeframing_count,
    is_inside_day,
    is_nr_n,
)

import os as _os  # noqa: E402
# Box layout mirrors /workspace/tape; override with TAPE_ROOT. Defaults to scripts/tape in the repo.
TAPE_ROOT = Path(_os.environ.get("TAPE_ROOT") or Path(__file__).resolve().parents[2])

PARQUET = (TAPE_ROOT / "ovn/es_1m_dbn.parquet")
YAHOO = ROOT / "data" / "es_yahoo_7d_1m.json"
EVENTS = REGIME / "data" / "event_calendar.json"
EVENTS_FALLBACK = ROOT / "data" / "event_calendar.json"
VIX = REGIME / "data" / "vix_daily_yahoo.json"
VIX9D = REGIME / "data" / "vix9d_daily_yahoo.json"
GEX_GLOB = (TAPE_ROOT / "state")
OUT_CSV = REGIME / "data" / "sessions_labeled.csv"
OUT_META = REGIME / "data" / "sessions_meta.json"


def _load_bars() -> pd.DataFrame:
    frames = []
    if PARQUET.exists():
        df = pd.read_parquet(PARQUET)
        if not isinstance(df.index, pd.DatetimeIndex):
            if "ts_event" in df.columns:
                df = df.set_index("ts_event")
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert(CT)
        frames.append(df[["open", "high", "low", "close"]].copy())
    if YAHOO.exists():
        rows = json.loads(YAHOO.read_text(encoding="utf-8"))["bars"]
        idx = pd.to_datetime([r[0] for r in rows], utc=True).tz_convert(CT)
        y = pd.DataFrame(
            {
                "open": [r[1] for r in rows],
                "high": [r[2] for r in rows],
                "low": [r[3] for r in rows],
                "close": [r[4] for r in rows],
            },
            index=idx,
        )
        frames.append(y)
    if not frames:
        raise FileNotFoundError("no ES 1m bars found")
    df = pd.concat(frames)
    return df[~df.index.duplicated(keep="last")].sort_index()


def _load_vix_map(path: Path) -> Dict[str, float]:
    if not path.exists():
        return {}
    bars = json.loads(path.read_text(encoding="utf-8")).get("bars_daily") or []
    out = {}
    for b in bars:
        if b[4] is None:
            continue
        out[b[0]] = float(b[4])
    return out


def _prior_close(vix: Dict[str, float], d: date, lookback: int = 7) -> Optional[float]:
    for back in range(1, lookback + 1):
        key = (d - timedelta(days=back)).isoformat()
        if key in vix:
            return vix[key]
    return None


def _event_map() -> Dict[str, str]:
    path = EVENTS if EVENTS.exists() else EVENTS_FALLBACK
    if not path.exists():
        return {}
    return {e["date"]: e["name"] for e in json.loads(path.read_text(encoding="utf-8")).get("events", [])}


def _opex_flag(d: date) -> int:
    """Monthly equity OPEX = third Friday."""
    if d.weekday() != 4:
        return 0
    # third Friday: day in 15..21
    return 1 if 15 <= d.day <= 21 else 0


def _parse_net_gex(s: str) -> Optional[float]:
    """Parse '+8.45B' / '-14.06B' / '-742.37M' → billions."""
    if s is None:
        return None
    m = re.match(r"([+-]?\d+(?:\.\d+)?)([BMK])?", str(s).strip(), re.I)
    if not m:
        return None
    val = float(m.group(1))
    unit = (m.group(2) or "B").upper()
    mult = {"B": 1.0, "M": 1e-3, "K": 1e-6}.get(unit, 1.0)
    return val * mult


def _gex_by_date() -> Dict[str, dict]:
    """Latest snapshot at/before 08:30 CT on session date (or prior evening).

    Coverage is short (~2 weeks of jsonl). Also maps prior-day late snapshots
    onto next session as stale carry (age_min from 08:30).
    """
    snaps: List[Tuple[datetime, dict]] = []
    if not GEX_GLOB.exists():
        return {}
    for path in sorted(GEX_GLOB.glob("gex-history-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            asof = row.get("asof_ct") or ""
            try:
                dt = datetime.strptime(asof[:16], "%Y-%m-%d %H:%M").replace(tzinfo=CT)
            except ValueError:
                continue
            net = _parse_net_gex(row.get("net_gex"))
            snaps.append((dt, {
                "net_gex_b": net,
                "asof_ct": asof,
                "sign": (1 if net and net > 0 else -1 if net and net < 0 else 0),
            }))
    snaps.sort(key=lambda x: x[0])
    out: Dict[str, dict] = {}
    # Build per calendar-date last snapshot. For session D, use latest snap with
    # dt <= D 08:30 (typically prior RTH 14:59 close → overnight carry, age ~17h).
    if not snaps:
        return out
    # session dates spanning snap range + 1 business day
    d0 = snaps[0][0].date()
    d1 = snaps[-1][0].date()
    d = d0
    while d <= d1 + timedelta(days=1):
        if d.weekday() < 5:
            cutoff = datetime(d.year, d.month, d.day, 8, 30, tzinfo=CT)
            eligible = [(dt, s) for dt, s in snaps if dt <= cutoff]
            if eligible:
                dt, s = eligible[-1]
                age_min = int((cutoff - dt).total_seconds() // 60)
                # only keep if age within 48h (else too stale to be meaningful)
                if age_min <= 48 * 60:
                    cand = dict(s)
                    cand["age_min"] = age_min
                    out[d.isoformat()] = cand
        d += timedelta(days=1)
    return out


def build_sessions(max_sessions: Optional[int] = None) -> pd.DataFrame:
    df = _load_bars()
    vix = _load_vix_map(VIX)
    vix9 = _load_vix_map(VIX9D)
    events = _event_map()
    gex = _gex_by_date()

    first = df.index[0].date()
    last = df.index[-1].date()
    rows: List[dict] = []
    d = first
    while d <= last:
        if d.weekday() >= 5:
            d += timedelta(days=1)
            continue
        rth_start = pd.Timestamp(datetime(d.year, d.month, d.day, 8, 30, tzinfo=CT))
        rth_end = pd.Timestamp(datetime(d.year, d.month, d.day, 15, 0, tzinfo=CT))
        rth = df[(df.index >= rth_start) & (df.index < rth_end)]
        if len(rth) < 200:
            d += timedelta(days=1)
            continue

        ovn_start = pd.Timestamp(
            datetime(d.year, d.month, d.day, 17, 0, tzinfo=CT) - timedelta(days=1)
        )
        ovn = df[(df.index >= ovn_start) & (df.index < rth_start)]
        ib = rth[rth.index < rth_start + timedelta(hours=1)]
        f30 = rth[rth.index < rth_start + timedelta(minutes=30)]

        rth_h = float(rth["high"].max())
        rth_l = float(rth["low"].min())
        rth_o = float(rth["open"].iloc[0])
        rth_c = float(rth["close"].iloc[-1])
        rth_rng = rth_h - rth_l

        ib_h = float(ib["high"].max()) if len(ib) else None
        ib_l = float(ib["low"].min()) if len(ib) else None
        ib_rng = (ib_h - ib_l) if ib_h is not None and ib_l is not None else None

        ovn_h = float(ovn["high"].max()) if len(ovn) >= 30 else None
        ovn_l = float(ovn["low"].min()) if len(ovn) >= 30 else None
        ovn_rng = (ovn_h - ovn_l) if ovn_h is not None and ovn_l is not None else None

        # prior RTH for gap / value-area proxy (prior H/L/C)
        prior = None
        if rows:
            prior = rows[-1]

        # VIX: use prior session close (known before open)
        vix_prior = _prior_close(vix, d)
        vix_2d = _prior_close(vix, d - timedelta(days=1)) if vix_prior is not None else None
        # Actually _prior_close(d) already skips weekends via lookback; for day-over-day use two prior closes
        vix_closes = []
        for back in range(1, 10):
            key = (d - timedelta(days=back)).isoformat()
            if key in vix:
                vix_closes.append(vix[key])
            if len(vix_closes) >= 2:
                break
        vix_chg = (vix_closes[0] - vix_closes[1]) if len(vix_closes) >= 2 else None

        vix9_prior = _prior_close(vix9, d)
        vix9_ratio = (vix9_prior / vix_prior) if (vix9_prior and vix_prior) else None

        ev_name = events.get(d.isoformat())
        g = gex.get(d.isoformat())

        # first 30m (known at ~09:00 CT — second-stage)
        f30_rng = float(f30["high"].max() - f30["low"].min()) if len(f30) else None
        f30_drive = (
            float(f30["close"].iloc[-1]) - float(f30["open"].iloc[0]) if len(f30) else None
        )
        open_type, open_drive_pts = dalton_open_type(rth, minutes=30)
        otf = one_timeframing_count(rth, bar_minutes=30, max_bars=6)

        row = {
            "date": d.isoformat(),
            "dow": d.weekday(),  # 0=Mon
            "opex": _opex_flag(d),
            "event": ev_name or "",
            "is_event": 1 if ev_name else 0,
            "is_nfp": 1 if ev_name == "NFP" else 0,
            "is_cpi": 1 if ev_name == "CPI" else 0,
            "is_fomc": 1 if ev_name == "FOMC" else 0,
            "rth_open": rth_o,
            "rth_high": rth_h,
            "rth_low": rth_l,
            "rth_close": rth_c,
            "rth_range": rth_rng,
            "ib_high": ib_h,
            "ib_low": ib_l,
            "ib_range": ib_rng,
            "ovn_high": ovn_h,
            "ovn_low": ovn_l,
            "ovn_range": ovn_rng,
            "vix_prior": vix_prior,
            "vix_chg": vix_chg,
            "vix9_prior": vix9_prior,
            "vix9_ratio": vix9_ratio,
            "gex_net_b": g["net_gex_b"] if g else None,
            "gex_sign": g["sign"] if g else None,
            "gex_available": 1 if g else 0,
            "f30_range": f30_rng,
            "f30_drive": f30_drive,
            "open_type": open_type,
            "open_drive_pts": open_drive_pts,
            "otf_count": otf,
            "gex_age_min": g["age_min"] if g else None,
            "prior_high": prior["rth_high"] if prior else None,
            "prior_low": prior["rth_low"] if prior else None,
            "prior_close": prior["rth_close"] if prior else None,
            "prior_range": prior["rth_range"] if prior else None,
            "prior_label": prior.get("label_primary") if prior else None,
            "nq_div": None,  # historical NQ 1m unavailable beyond ~7d; mark None
        }
        rows.append(row)
        d += timedelta(days=1)

    if max_sessions and len(rows) > max_sessions:
        rows = rows[-max_sessions:]

    # rolling 20d avg range (prior sessions only)
    for i, row in enumerate(rows):
        if i < 20:
            row["avg_range_20"] = None
            continue
        row["avg_range_20"] = float(np.mean([rows[j]["rth_range"] for j in range(i - 20, i)]))

    # derived predictors
    for i, row in enumerate(rows):
        atr = row["avg_range_20"]
        ovn_rng = row["ovn_range"]
        row["ovn_atr"] = (ovn_rng / atr) if (ovn_rng is not None and atr) else None
        row["ib_atr"] = (row["ib_range"] / atr) if (row.get("ib_range") is not None and atr) else None
        row["ib_ovn"] = (
            (row["ib_range"] / ovn_rng)
            if (row.get("ib_range") is not None and ovn_rng and ovn_rng > 0)
            else None
        )
        row["range_atr"] = (row["rth_range"] / atr) if atr else None
        rng = row["rth_high"] - row["rth_low"]
        row["close_pos"] = (
            (row["rth_close"] - row["rth_low"]) / rng if rng > 0 else None
        )
        row["open_drive_atr"] = (
            (abs(row["open_drive_pts"]) / atr)
            if (row.get("open_drive_pts") is not None and atr)
            else None
        )

        # gap vs prior range
        if row["prior_close"] is not None and row["prior_high"] is not None and row["prior_low"] is not None:
            o = row["rth_open"]
            row["gap_pts"] = o - row["prior_close"]
            row["gap_in_range"] = 1 if row["prior_low"] <= o <= row["prior_high"] else 0
            pr = row["prior_high"] - row["prior_low"]
            row["open_loc_prior"] = ((o - row["prior_low"]) / pr) if pr > 0 else None
            row["gap_prior_range"] = (abs(row["gap_pts"]) / pr) if pr > 0 else None
            row["prior_close_pos"] = (
                (row["prior_close"] - row["prior_low"]) / pr if pr > 0 else None
            )
        else:
            row["gap_pts"] = None
            row["gap_in_range"] = None
            row["open_loc_prior"] = None
            row["gap_prior_range"] = None
            row["prior_close_pos"] = None

        row["prior_range_atr"] = (
            (row["prior_range"] / atr) if (row.get("prior_range") is not None and atr) else None
        )

        # prior NR4 / NR7 / inside day
        if i >= 1:
            ranges_to_prior = [rows[j]["rth_range"] for j in range(max(0, i - 7), i)]
            row["prior_nr4"] = is_nr_n(ranges_to_prior, 4) if len(ranges_to_prior) >= 4 else None
            row["prior_nr7"] = is_nr_n(ranges_to_prior, 7) if len(ranges_to_prior) >= 7 else None
            if i >= 2:
                row["prior_inside"] = is_inside_day(
                    rows[i - 2]["rth_high"], rows[i - 2]["rth_low"],
                    rows[i - 1]["rth_high"], rows[i - 1]["rth_low"],
                )
            else:
                row["prior_inside"] = None
        else:
            row["prior_nr4"] = None
            row["prior_nr7"] = None
            row["prior_inside"] = None

        # open-type one-hots (stage-2 / 09:00)
        ot = row.get("open_type")
        for name in ("open_drive", "open_test_drive", "open_rejection_reverse", "open_auction"):
            row[f"is_{name}"] = 1 if ot == name else (0 if ot else None)

        # prior day type one-hot-ish
        pl = row.get("prior_label")
        row["prior_was_trend"] = 1 if pl == "trend" else 0 if pl else None
        row["prior_was_balance"] = 1 if pl == "balance" else 0 if pl else None

        # labels for all variants (need avg_range_20)
        if atr is None:
            for p in VARIANTS:
                row[f"label_{p.name}"] = None
            row["label_primary"] = None
            continue
        for p in VARIANTS:
            lab = label_session(
                rth_low=row["rth_low"],
                rth_high=row["rth_high"],
                rth_close=row["rth_close"],
                avg_range_20=atr,
                ib_low=row["ib_low"],
                ib_high=row["ib_high"],
                params=p,
            )
            row[f"label_{p.name}"] = lab
        # label_primary set via VARIANTS loop (name="primary")

    # second pass: prior_label now filled — recompute prior_was_* 
    # (first pass used prior before labels; fix chronologically)
    for i, row in enumerate(rows):
        if i == 0:
            row["prior_label"] = None
            row["prior_was_trend"] = None
            row["prior_was_balance"] = None
            continue
        pl = rows[i - 1].get("label_primary")
        row["prior_label"] = pl
        row["prior_was_trend"] = 1 if pl == "trend" else 0 if pl is not None else None
        row["prior_was_balance"] = 1 if pl == "balance" else 0 if pl is not None else None

    out = pd.DataFrame(rows)
    # drop rows without ATR / label
    out = out[out["label_primary"].notna()].reset_index(drop=True)
    return out


def main():
    df = build_sessions()
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    counts = df["label_primary"].value_counts().to_dict()
    meta = {
        "n": int(len(df)),
        "first": df["date"].iloc[0],
        "last": df["date"].iloc[-1],
        "label_counts": {k: int(v) for k, v in counts.items()},
        "trend_rate": float((df["label_primary"] == "trend").mean()),
        "balance_rate": float((df["label_primary"] == "balance").mean()),
        "gex_coverage_n": int(df["gex_available"].sum()),
        "vix_coverage_n": int(df["vix_prior"].notna().sum()),
        "unavailable": [
            "historical implied move (straddle) — not on disk; ovn_atr used as overnight-stress proxy",
            "NQ vs ES divergence — NQ 1m history only ~7d on disk",
            f"GEX sign/size/age — only {int(df['gex_available'].sum())} sessions have usable pre-08:30 snapshots",
            "VIX1D series — not on disk; VIX9D/VIX used as front-vol proxy",
            "0DTE option quotes — day-type score only; Vilkov warns gross IC edge may not survive costs",
        ],
        "sources": {
            "es_1m": str(PARQUET),
            "es_yahoo": str(YAHOO),
            "vix": str(VIX),
            "vix9d": str(VIX9D),
            "events": str(EVENTS),
        },
    }
    OUT_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
