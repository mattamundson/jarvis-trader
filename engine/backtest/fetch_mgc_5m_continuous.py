"""Continuous 5m MGC (micro gold, COMEX) series via multi-contract stitch.

Gold rolls bi-monthly (G/J/M/Q/V/Z = Feb/Apr/Jun/Aug/Oct/Dec), so cover ~20
months with the bimonthly contracts back to 2024-08. Qualify each with
includeExpired=True, read the contract's REAL lastTradeDateOrContractMonth for
the roll tag, pull backward in 1-month 5m chunks, then stitch by the standard
roll (nearest unexpired wins). Writes MGC_<start>_<end>_5m_cont.csv.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ENGINE = r"C:\Users\mattm\ThinkorSwim\jarvis-trader\engine"
sys.path.insert(0, ENGINE)
import pandas as pd  # noqa: E402

from data.market_data import IBKRDataConnector  # noqa: E402

SYMBOL, EXCHANGE = "MGC", "COMEX"
# Bimonthly gold months, newest first, covering 2024-08 .. 2026-06.
MONTHS = [
    "202606",
    "202604",
    "202602",
    "202512",
    "202510",
    "202508",
    "202506",
    "202504",
    "202502",
    "202412",
    "202410",
    "202408",
]
CHUNKS_PER_CONTRACT = 4
PACE_SEC = 2.0


async def pull(ib, month):
    from ib_async import Future

    q = await ib.qualifyContractsAsync(
        Future(
            SYMBOL,
            exchange=EXCHANGE,
            currency="USD",
            lastTradeDateOrContractMonth=month,
            includeExpired=True,
        )
    )
    if not q:
        print(f"  {SYMBOL}{month}: qualify FAILED")
        return None
    contract = q[0]
    exp_str = contract.lastTradeDateOrContractMonth  # real expiry, e.g. 20260428
    try:
        expiry = pd.Timestamp(datetime.strptime(exp_str[:8], "%Y%m%d"), tz="UTC")
    except Exception:
        expiry = pd.Timestamp(datetime.strptime(month + "28", "%Y%m%d"), tz="UTC")
    frames, end, empty = [], datetime.now(timezone.utc), 0
    exp_dt = expiry.to_pydatetime() + timedelta(days=2)
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
            print(f"  {SYMBOL}{month} chunk {i} ERROR {e}")
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
            f"  {SYMBOL}{month} (exp {exp_str}) chunk {i} bars={len(df)} earliest={earliest:%Y-%m-%d}"
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
    out["expiry"] = expiry
    return out


async def main():
    conn = IBKRDataConnector(port=4002, client_id=26, connect_timeout=15.0)
    if not await conn.connect():
        print("CONNECT FAILED")
        return
    ib = conn._ib
    parts = []
    for mo in MONTHS:
        df = await pull(ib, mo)
        if df is not None:
            parts.append(df)
    await conn.disconnect()
    if not parts:
        print("NO DATA")
        return
    alldf = pd.concat(parts, ignore_index=True)
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
    out = Path(ENGINE) / "backtest" / "cache" / f"MGC_{start}_{endd}_5m_cont.csv"
    cont.to_csv(out, index=False)
    print(f"WROTE {out}")
    print(f"rows={len(cont)} span {start} -> {endd}")
    bpm = cont.groupby(cont["timestamp"].dt.to_period("M")).size()
    print("bars/month:", {str(k): int(v) for k, v in bpm.items()})


asyncio.run(main())
