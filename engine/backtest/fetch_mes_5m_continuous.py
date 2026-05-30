"""Build a continuous 5m MES series by stitching prior front-month contracts.

The single-contract pull (MESM6) gave dense data only Oct 2025 -> May 2026 (a
June-2026 contract is thin before then). To reach ~18 months for a proper
6/3/3 WFO, pull the prior quarterly contracts and stitch by the standard roll:
at each timestamp keep the bar from the NEAREST UNEXPIRED contract (the front
month at that time). Reuses the existing MESM6 csv (tagged expiry 2026-06-19).
Writes engine/backtest/cache/MES_<start>_<end>_5m_cont.csv.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ENGINE = r"C:\Users\mattm\ThinkorSwim\jarvis-trader\engine"
sys.path.insert(0, ENGINE)
import pandas as pd  # noqa: E402

from data.market_data import IBKRDataConnector  # noqa: E402

# Quarterly contracts to ADD (expiry = 3rd Friday). MESM6 reused from disk.
CONTRACTS = [
    ("MESZ5", "20251219"),
    ("MESU5", "20250919"),
    ("MESM5", "20250620"),
    ("MESH5", "20250321"),
]
EXISTING_CSV = "MES_2025-04-09_2026-05-29_5m.csv"
EXISTING_EXPIRY = pd.Timestamp("2026-06-19", tz="UTC")
CHUNKS_PER_CONTRACT = 6
PACE_SEC = 2.0


async def pull_contract(ib, symbol, expiry):
    from ib_async import Future

    q = await ib.qualifyContractsAsync(
        Future(
            "MES",
            exchange="CME",
            currency="USD",
            lastTradeDateOrContractMonth=expiry,
            includeExpired=True,
        )
    )
    if not q:
        print(f"  {symbol}: qualify FAILED")
        return None
    contract = q[0]
    frames, end, empty = [], datetime.now(timezone.utc), 0
    # start near the contract's expiry (no point requesting after it expired)
    exp_dt = datetime.strptime(expiry, "%Y%m%d").replace(
        tzinfo=timezone.utc
    ) + timedelta(days=2)
    if exp_dt < end:
        end = exp_dt
    for i in range(CHUNKS_PER_CONTRACT):
        try:
            bars = await ib.reqHistoricalDataAsync(
                contract,
                endDateTime=end,
                durationStr="1 M",
                barSizeSetting="5 mins",
                whatToShow="TRADES",
                useRTH=False,
            )
        except Exception as e:
            print(f"  {symbol} chunk {i} ERROR {e}")
            break
        if not bars:
            empty += 1
            if empty >= 2:
                break
            end = end - timedelta(days=30)
            await asyncio.sleep(PACE_SEC)
            continue
        empty = 0
        df = pd.DataFrame(
            [
                {
                    "timestamp": b.date,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                }
                for b in bars
            ]
        )
        frames.append(df)
        earliest = pd.to_datetime(df["timestamp"], utc=True).min()
        print(
            f"  {symbol} chunk {i} end={end:%Y-%m-%d} bars={len(df)} earliest={earliest:%Y-%m-%d}"
        )
        nxt = earliest.to_pydatetime()
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=timezone.utc)
        if nxt >= end:
            break
        end = nxt
        await asyncio.sleep(PACE_SEC)
    if not frames:
        return None
    out = pd.concat(frames, ignore_index=True)
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    out["expiry"] = pd.Timestamp(datetime.strptime(expiry, "%Y%m%d"), tz="UTC")
    return out


async def main():
    conn = IBKRDataConnector(port=4002, client_id=25, connect_timeout=15.0)
    if not await conn.connect():
        print("CONNECT FAILED")
        return
    ib = conn._ib

    parts = []
    existing = pd.read_csv(Path(ENGINE) / "backtest" / "cache" / EXISTING_CSV)
    existing["timestamp"] = pd.to_datetime(existing["timestamp"], utc=True)
    existing["expiry"] = EXISTING_EXPIRY
    parts.append(
        existing[["timestamp", "open", "high", "low", "close", "volume", "expiry"]]
    )
    print(f"loaded existing MESM6: {len(existing)} rows")

    for sym, exp in CONTRACTS:
        print(f"pulling {sym} (exp {exp})...")
        df = await pull_contract(ib, sym, exp)
        if df is not None:
            parts.append(df)
            print(
                f"  -> {len(df)} rows {df['timestamp'].min():%Y-%m-%d} .. {df['timestamp'].max():%Y-%m-%d}"
            )
    await conn.disconnect()

    alldf = pd.concat(parts, ignore_index=True)
    # Roll: at each timestamp keep the bar from the nearest UNEXPIRED contract
    # (front month). expiry >= timestamp, then smallest expiry wins.
    alldf = alldf[alldf["expiry"] >= alldf["timestamp"]]
    alldf = alldf.sort_values(["timestamp", "expiry"])
    cont = (
        alldf.drop_duplicates("timestamp", keep="first")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    cont = cont[["timestamp", "open", "high", "low", "close", "volume"]]
    start = cont["timestamp"].min().strftime("%Y-%m-%d")
    endd = cont["timestamp"].max().strftime("%Y-%m-%d")
    out = Path(ENGINE) / "backtest" / "cache" / f"MES_{start}_{endd}_5m_cont.csv"
    cont.to_csv(out, index=False)
    print(f"WROTE {out}")
    print(f"rows={len(cont)} span {start} -> {endd}")
    bpm = cont.groupby(cont["timestamp"].dt.to_period("M")).size()
    print("bars/month:", {str(k): int(v) for k, v in bpm.items()})


asyncio.run(main())
