"""
BT-1: Pull /MES continuous futures data from yfinance.
Saves OHLCV to Parquet for backtesting.

MES = Micro E-mini S&P 500 — yfinance ticker: MES=F
Note: yfinance futures data is limited to ~60 days for intraday.
For historical 1h/5m, we use ES=F (E-mini) or proxy with SPY * 5 (MES ~= ES/5).
Long-term hourly: yfinance provides ES=F 1h up to ~730 days via period='730d'.
Daily: ES=F available 2010+.
"""
import yfinance as yf
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent.parent / "backtest" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

def pull(ticker, interval, start, end, label):
    print(f"  Pulling {label} ({ticker}, {interval}) {start} → {end}...", end=" ", flush=True)
    try:
        df = yf.download(ticker, start=start, end=end, interval=interval,
                         progress=False, auto_adjust=True)
        if df.empty:
            print("EMPTY")
            return None
        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[['Open','High','Low','Close','Volume']].dropna()
        out = DATA_DIR / f"{label}.parquet"
        df.to_parquet(out)
        print(f"OK — {len(df)} bars → {out.name}")
        return df
    except Exception as e:
        print(f"ERROR: {e}")
        return None

# ES=F is the standard proxy for MES (MES = ES × 0.1 for price, × 5 for contracts)
# yfinance doesn't support MES=F history reliably; ES=F is the standard proxy.
TICKER = "ES=F"

print("=== BT-1: Pulling MES/ES futures data ===\n")

# Daily — 2022-01-01 to present (4.4 years, plenty of history)
daily = pull(TICKER, "1d", "2022-01-01", "2026-06-01", "MES_1d")

# 1-hour — yfinance caps at ~730 days for intraday; pull in 2 chunks
h1_a = pull(TICKER, "1h", "2024-01-01", "2026-06-01", "MES_1h_2024_2026")
h1_b = pull(TICKER, "1h", "2022-01-01", "2023-12-31", "MES_1h_2022_2023")

# 5-minute — yfinance caps at 60 days for 5m; pull most recent
m5 = pull(TICKER, "5m", "2026-04-01", "2026-06-01", "MES_5m_recent")

# Combine 1h chunks
print("\nCombining 1h chunks...", end=" ")
if h1_a is not None and h1_b is not None:
    h1 = pd.concat([h1_b, h1_a]).sort_index()
    h1 = h1[~h1.index.duplicated()]
    h1.to_parquet(DATA_DIR / "MES_1h.parquet")
    print(f"MES_1h.parquet — {len(h1)} bars ({h1.index[0].date()} → {h1.index[-1].date()})")
elif h1_a is not None:
    h1_a.to_parquet(DATA_DIR / "MES_1h.parquet")
    h1 = h1_a
    print(f"MES_1h.parquet — {len(h1)} bars (single chunk)")
else:
    h1 = None
    print("FAILED — no 1h data")

# Also pull SPY as correlation reference + TRIN
print()
pull("SPY", "1d", "2022-01-01", "2026-06-01", "SPY_1d")
pull("^VIX", "1d", "2022-01-01", "2026-06-01", "VIX_1d")
pull("^TRIN", "1d", "2022-01-01", "2026-06-01", "TRIN_1d")

print("\n=== Summary ===")
for f in sorted(DATA_DIR.glob("*.parquet")):
    df = pd.read_parquet(f)
    print(f"  {f.name:<35} {len(df):>6} bars  "
          f"{df.index[0].date()} → {df.index[-1].date()}")

print("\nBT-1 complete.")
