#!/bin/bash
# Setup Freqtrade for jarvis-trader crypto module
# Run: bash scripts/setup_freqtrade.sh

set -e

echo "=== Setting up Freqtrade for jarvis-trader ==="

# Install Freqtrade
pip install freqtrade

# Create data directories
mkdir -p infrastructure/freqtrade/user_data/{data,logs,backtest_results,hyperopt_results}

# Download historical data for backtesting
echo "Downloading BTC/ETH historical data (Binance)..."
freqtrade download-data \
  --config infrastructure/freqtrade/config.json \
  --exchange binance \
  --pairs BTC/USDT ETH/USDT \
  --timeframes 15m 1h 4h \
  --days 365

echo ""
echo "=== Freqtrade Setup Complete ==="
echo ""
echo "To run backtests:"
echo "  freqtrade backtesting --config infrastructure/freqtrade/config.json --strategy MeanReversionStrategy --timerange 20240101-"
echo ""
echo "To start paper trading:"
echo "  freqtrade trade --config infrastructure/freqtrade/config.json"
echo ""
echo "To view results in UI:"
echo "  freqtrade webserver --config infrastructure/freqtrade/config.json"
echo "  Open: http://localhost:8080"
echo ""
echo "API docs: http://localhost:8080/api/v1/ui/"
