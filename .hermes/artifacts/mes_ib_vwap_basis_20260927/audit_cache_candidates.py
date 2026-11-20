"""Read-only audit of candidate MES intraday caches."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

CANDIDATES = [
    Path(r"C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\backtest\cache\MES_2024-09-22_2026-05-29_5m_cont.csv"),
    Path(r"C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\backtest\cache\MES_2025-04-09_2026-06-29_5m.csv"),
    Path(r"C:\Users\mattm\master-jarvis\backtest\cache\MES_2025-07-24_2026-07-27_5m_cont.csv"),
    Path(r"C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\backtest\cache\MES_2024-09-22_2026-06-29_15m.csv"),
]
OUTPUT = Path(__file__).with_name("cache_candidate_audit.json")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    ts_col = next((c for c in df.columns if c.lower() in {"timestamp", "datetime", "date", "time"}), df.columns[0])
    idx = pd.to_datetime(df.pop(ts_col), utc=True, errors="coerce")
    df.index = idx
    df.index.name = "timestamp"
    df.columns = [str(c).lower() for c in df.columns]
    return df.sort_index()


def audit(path: Path, df: pd.DataFrame) -> dict:
    ohlc = [c for c in ("open", "high", "low", "close") if c in df.columns]
    interval = df.index.to_series().diff().dropna().dt.total_seconds()
    nonpositive = 0
    if len(ohlc) == 4:
        nonpositive = int((df[ohlc] <= 0).any(axis=1).sum())
    violations = 0
    if len(ohlc) == 4:
        violations = int(
            (
                (df["high"] < df[["open", "close", "low"]].max(axis=1))
                | (df["low"] > df[["open", "close", "high"]].min(axis=1))
            ).sum()
        )
    ct = df.index.tz_convert("America/Chicago")
    rth = ((ct.hour > 8) | ((ct.hour == 8) & (ct.minute >= 30))) & (ct.hour < 15)
    rth_dates = pd.Index(ct[rth].date)
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "columns": list(df.columns),
        "rows": int(len(df)),
        "first_utc": df.index.min().isoformat(),
        "last_utc": df.index.max().isoformat(),
        "span_years": round((df.index.max() - df.index.min()).total_seconds() / (365.25 * 86400), 6),
        "duplicate_timestamps": int(df.index.duplicated().sum()),
        "nat_timestamps": int(df.index.isna().sum()),
        "nan_by_column": {c: int(v) for c, v in df.isna().sum().items()},
        "nonpositive_ohlc_rows": nonpositive,
        "ohlc_invariant_violations": violations,
        "median_interval_seconds": float(interval.median()),
        "mode_interval_seconds": float(interval.mode().iloc[0]),
        "large_gap_count_gt_6h": int((interval > 6 * 3600).sum()),
        "rth_rows": int(rth.sum()),
        "rth_sessions": int(rth_dates.nunique()),
        "rth_first_date": str(rth_dates.min()),
        "rth_last_date": str(rth_dates.max()),
    }


def compare(a_path: Path, a: pd.DataFrame, b_path: Path, b: pd.DataFrame) -> dict:
    cols = [c for c in ("open", "high", "low", "close", "volume") if c in a.columns and c in b.columns]
    ix = a.index.intersection(b.index)
    out = {
        "a": str(a_path),
        "b": str(b_path),
        "overlap_rows": int(len(ix)),
        "overlap_first": ix.min().isoformat() if len(ix) else None,
        "overlap_last": ix.max().isoformat() if len(ix) else None,
        "columns_compared": cols,
    }
    if not len(ix):
        return out
    for c in cols:
        av = pd.to_numeric(a.loc[ix, c], errors="coerce").to_numpy(float)
        bv = pd.to_numeric(b.loc[ix, c], errors="coerce").to_numpy(float)
        d = np.abs(av - bv)
        out[c] = {
            "exact_matches": int(np.isclose(d, 0.0, atol=1e-12, rtol=0).sum()),
            "mismatches": int((~np.isclose(d, 0.0, atol=1e-12, rtol=0)).sum()),
            "max_abs_diff": float(np.nanmax(d)),
            "median_abs_diff": float(np.nanmedian(d)),
        }
    return out


def main() -> None:
    frames = {p: load(p) for p in CANDIDATES}
    payload = {
        "candidates": [audit(p, frames[p]) for p in CANDIDATES],
        "pairwise_overlap": [
            compare(CANDIDATES[i], frames[CANDIDATES[i]], CANDIDATES[j], frames[CANDIDATES[j]])
            for i in range(len(CANDIDATES))
            for j in range(i + 1, len(CANDIDATES))
            if "5m" in CANDIDATES[i].name and "5m" in CANDIDATES[j].name
        ],
    }
    OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
