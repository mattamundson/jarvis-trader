"""
JARVIS TRADER — Regime Classifier V2 Validation
Validates the new MarketRegime classification against historical data.
"""

from __future__ import annotations

from backtest.data_loader import BacktestDataLoader
from backtest.regime_classifier import RegimeClassifierV2


def main():
    print("=" * 80)
    print("JARVIS TRADER — Regime Classifier V2 Validation")
    print("=" * 80)

    loader = BacktestDataLoader()
    symbols = ["MES", "MNQ", "MCL", "MGC"]

    clf = RegimeClassifierV2()

    for symbol in symbols:
        print(f"\n[Validation] {symbol} 1h (2024-2026)...")
        df = loader.load(symbol, "2024-06-01", "2026-03-27", "1h")

        if df is None or df.empty:
            print(f"  [SKIP] No data found for {symbol}")
            continue

        df = clf.classify(df)

        counts = df["regime_v2"].value_counts()
        total = len(df)

        print(f"  Total bars: {total}")
        for regime_name, count in counts.items():
            pct = (count / total) * 100
            print(f"  - {regime_name:<10}: {count:>6} bars ({pct:>5.1f}%)")

        # Transitions check
        transitions = (df["regime_v2"] != df["regime_v2"].shift(1)).sum()
        print(f"  Transitions: {transitions} (Avg duration: {total/transitions:.1f} bars)")

if __name__ == "__main__":
    main()
