"""Pull intraday historical bars from IBKR Gateway via ib_async (read-only).

Requires IB Gateway running on 127.0.0.1:4002 (paper). Uses clientId=99 to
avoid collision with jarvis-trader's connections (which use 1-20 range).

Read-only: only calls reqHistoricalData. Does not place orders. Safe to run
alongside live jarvis-trader strategies on the same DUP662235 paper account.

Output: parquet files in research/data/ with `_5m` suffix.

Note (P3-31): pyarrow is an explicit dep because pandas uses it as the parquet
engine.  On Windows, the first import can fail with ImportError when the
Arrow DLLs haven't been loaded yet (cold-start race).  The guard below
surfaces the failure early at startup rather than deep inside df.to_parquet().
If this fails, ensure you're running from the .venv:
    .venv\\Scripts\\python research\\_pull_ibkr_bars.py
"""

import sys
from pathlib import Path

try:
    import pyarrow  # noqa: F401 — explicit dep guard (parquet engine)
except ImportError as _pa_err:
    print(
        f"[ERROR] pyarrow not importable: {_pa_err}\n"
        "Run from the project .venv:  .venv\\Scripts\\python research\\_pull_ibkr_bars.py\n"
        f"Active Python: {sys.executable}"
    )
    sys.exit(1)

import pandas as pd
from ib_async import IB, Future, Stock

OUT = Path(__file__).resolve().parent / "data"
OUT.mkdir(parents=True, exist_ok=True)

HOST = "127.0.0.1"
PORT = 4002  # IB Gateway paper
CLIENT_ID = 99  # high to avoid jarvis-trader collision
DURATION = "30 D"  # IBKR duration string: "30 D", "1 W", "1 Y", etc.
BAR_SIZE = "5 mins"
WHAT_TO_SHOW = "TRADES"
USE_RTH = False  # False = include extended hours; better for futures

CONTRACTS = {
    "MES_5m": Future(
        symbol="MES",
        lastTradeDateOrContractMonth="202606",
        exchange="CME",
        currency="USD",
    ),
    "MGC_5m": Future(
        symbol="MGC",
        lastTradeDateOrContractMonth="202606",
        exchange="COMEX",
        currency="USD",
    ),
    "MNQ_5m": Future(
        symbol="MNQ",
        lastTradeDateOrContractMonth="202606",
        exchange="CME",
        currency="USD",
    ),
    "SPY_5m": Stock(symbol="SPY", exchange="SMART", currency="USD"),
    "QQQ_5m": Stock(symbol="QQQ", exchange="SMART", currency="USD"),
}


def main() -> int:
    ib = IB()
    try:
        print(f"Connecting to IB Gateway {HOST}:{PORT} (clientId={CLIENT_ID})...")
        ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=10)
    except Exception as e:
        print(f"CONNECTION FAILED: {e}")
        print("\nIs IB Gateway running?")
        print("  - Start it from the Start menu (IBC / IB Gateway shortcut)")
        print("  - Log in to paper account DUP662235")
        print("  - Confirm port 4002 is the paper trading socket port")
        return 1

    print(f"Connected. Server version: {ib.client.serverVersion()}")
    print(f"Managed accounts: {ib.managedAccounts()}\n")

    failures = 0
    for label, contract in CONTRACTS.items():
        print(f"  {label:8s} ", end="", flush=True)
        try:
            qualified = ib.qualifyContracts(contract)
            if not qualified:
                print("[skip] could not qualify contract")
                failures += 1
                continue

            bars = ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=DURATION,
                barSizeSetting=BAR_SIZE,
                whatToShow=WHAT_TO_SHOW,
                useRTH=USE_RTH,
                formatDate=1,
            )
            if not bars:
                print("[warn] empty bar list")
                failures += 1
                continue

            df = pd.DataFrame(
                [
                    {
                        "date": b.date,
                        "open": b.open,
                        "high": b.high,
                        "low": b.low,
                        "close": b.close,
                        "volume": b.volume,
                    }
                    for b in bars
                ]
            )
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")

            path = OUT / f"{label}.parquet"
            df.to_parquet(path)
            print(
                f"-> {path.name}  ({len(df):5d} bars, "
                f"{df.index.min()} -> {df.index.max()})"
            )
        except Exception as e:
            print(f"[error] {type(e).__name__}: {e}")
            failures += 1

    ib.disconnect()
    print(f"\nDone. {len(CONTRACTS) - failures}/{len(CONTRACTS)} succeeded.")
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
