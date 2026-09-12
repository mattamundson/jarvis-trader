"""One-shot starter data pull. Run once to populate research/data/*.parquet.
Symbols mirror Amo's live trading focus: ES (=MES family), GC (=MGC family),
plus SPY/QQQ for equity-side reference. Daily bars, 2y history.
"""
from pathlib import Path
import yfinance as yf

OUT = Path(__file__).resolve().parent / "data"
OUT.mkdir(parents=True, exist_ok=True)

SYMBOLS = {
    "ES_F": "ES=F",   # E-mini S&P front-month continuous (proxy for MES)
    "GC_F": "GC=F",   # Gold front-month continuous (proxy for MGC)
    "NQ_F": "NQ=F",   # Nasdaq front-month continuous (proxy for MNQ)
    "SPY":  "SPY",
    "QQQ":  "QQQ",
}

for label, ticker in SYMBOLS.items():
    df = yf.download(ticker, period="2y", interval="1d", auto_adjust=False, progress=False)
    if df.empty:
        print(f"  [warn] {ticker}: empty result")
        continue
    path = OUT / f"{label}_1d.parquet"
    df.to_parquet(path)
    print(f"  {ticker:6s} -> {path.name}  ({len(df)} rows, {df.index.min().date()} -> {df.index.max().date()})")

print("\nDone.")
