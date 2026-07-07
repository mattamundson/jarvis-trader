"""
JARVIS TRADER — Regime Analysis CLI

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_regime_analysis.py \
        --results-file results/MCL_1h_2024-06-01_2026-03-27.json \
        --data-file cache/MCL_1h_730d.csv

    Outputs:
      - regime_analysis.json (metrics per regime)
      - regime_analysis.html (visualization)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd


def main():
    parser = argparse.ArgumentParser(
        description="JARVIS TRADER Regime Analysis",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--results-file", required=True, help="Path to backtest results JSON")
    parser.add_argument(
        "--data-file",
        default=None,
        help="Path to OHLCV CSV (optional; uses embedded regime if not provided)",
    )
    parser.add_argument("--output-dir", default=None, help="Output directory (default: results/)")
    args = parser.parse_args()

    # Resolve paths
    results_path = Path(args.results_file)

    if not results_path.exists():
        print(f"[ERROR] Results file not found: {results_path}")
        sys.exit(1)

    print("JARVIS TRADER — Regime Analysis")
    print(f"Results: {results_path}")
    if args.data_file:
        print(f"Data:    {args.data_file}")
    else:
        print("Data:    Using embedded regime data from trades")
    print("-" * 60)

    # Load backtest results
    print("Loading backtest results...")
    with open(results_path, "r") as f:
        results = json.load(f)

    # Prefer full_metrics trades which have regime data; fall back to trades_list
    if "full_metrics" in results and "trades" in results["full_metrics"]:
        trades = results["full_metrics"]["trades"]
    else:
        trades = results.get("trades_list", [])

    symbol = results.get("symbol", "UNKNOWN")
    interval = results.get("interval", "1h")

    if not trades:
        print("[ERROR] No trades found in results file")
        sys.exit(1)

    print(f"Loaded {len(trades)} trades from {symbol} {interval}")

    # Load OHLCV data (optional)
    df = None
    if args.data_file:
        print("Loading OHLCV data...")
        data_path = Path(args.data_file)
        if not data_path.exists():
            print(f"[WARNING] Data file not found: {data_path}; using embedded regime data instead")
        else:
            try:
                df = pd.read_csv(data_path)
                # Try to parse timestamp column
                if "timestamp" in df.columns:
                    df["timestamp"] = pd.to_datetime(df["timestamp"])
                    df.set_index("timestamp", inplace=True)
                elif "datetime" in df.columns:
                    df["datetime"] = pd.to_datetime(df["datetime"])
                    df.set_index("datetime", inplace=True)
                else:
                    # Try to parse index
                    df.index = pd.to_datetime(df.index)

                print(f"Loaded {len(df)} bars from {data_path.name}")
            except Exception as e:
                print(f"[WARNING] Failed to load data: {e}; using embedded regime data instead")

    # Import and run analysis
    try:
        from backtest.regime_analysis import RegimeAnalyzer
    except ImportError as e:
        print(f"[ERROR] Failed to import RegimeAnalyzer: {e}")
        print("Make sure you're running from the engine/ directory.")
        sys.exit(1)

    print("Analyzing regimes...")
    analyzer = RegimeAnalyzer(df)
    # Use embedded regime data if available (from full_metrics.trades)
    analyzer.analyze_trades(trades, regime_column="regime")

    print(analyzer.summary())

    # Identify edge sources
    sources = analyzer.identify_edge_sources()
    print("\n=== EDGE SOURCES ===")
    print(f"Profitable regimes: {', '.join(sources.get('profitable_regimes', []))}")
    print(f"Unprofitable regimes: {', '.join(sources.get('unprofitable_regimes', []))}")
    print(f"Best regime: {sources.get('best_regime')} (PF {sources.get('best_pf')})")
    print(f"Worst regime: {sources.get('worst_regime')} (PF {sources.get('worst_pf')})")
    print("\nRegime distribution:")
    for regime, pct in sources.get("regime_distribution", {}).items():
        print(f"  {regime}: {pct:.1%}")

    # Determine output paths
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = results_path.parent

    output_dir.mkdir(parents=True, exist_ok=True)

    # Save JSON results
    json_filename = f"{symbol}_{interval}_regime_analysis.json"
    json_path = output_dir / json_filename

    json_data = {
        "symbol": symbol,
        "interval": interval,
        "analysis_date": datetime.now().isoformat(),
        "regime_metrics": analyzer.to_dict(),
        "edge_sources": sources,
    }

    with open(json_path, "w") as f:
        json.dump(json_data, f, indent=2)

    print(f"\nJSON results saved to: {json_path}")

    # Create HTML visualization
    html_filename = f"{symbol}_{interval}_regime_analysis.html"
    html_path = output_dir / html_filename

    html_content = _generate_html(symbol, interval, analyzer, sources)
    with open(html_path, "w") as f:
        f.write(html_content)

    print(f"HTML visualization saved to: {html_path}")
    print("\nAnalysis complete!")


def _generate_html(symbol: str, interval: str, analyzer, sources: dict) -> str:
    """Generate HTML visualization of regime analysis."""
    regimes = list(analyzer.regime_stats.keys())
    regimes_sorted = [
        "TRENDING_UP",
        "TRENDING_DOWN",
        "RANGE_BOUND",
        "HIGH_VOLATILITY",
        "TRANSITION",
    ]
    regimes = [r for r in regimes_sorted if r in analyzer.regime_stats]

    # Extract data for charts
    trade_counts = [analyzer.regime_stats[r].trade_count for r in regimes]
    win_rates = [analyzer.regime_stats[r].win_rate * 100 for r in regimes]
    pfs = [analyzer.regime_stats[r].profit_factor for r in regimes]
    pnls = [analyzer.regime_stats[r].total_pnl for r in regimes]

    # Color scheme
    colors = {
        "TRENDING_UP": "#2ecc71",
        "TRENDING_DOWN": "#e74c3c",
        "RANGE_BOUND": "#f39c12",
        "HIGH_VOLATILITY": "#9b59b6",
        "TRANSITION": "#95a5a6",
    }
    regime_colors = [colors.get(r, "#95a5a6") for r in regimes]

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>{symbol} {interval} - Regime Analysis</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }}
        .header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
        }}
        .header p {{
            font-size: 1.1em;
            opacity: 0.9;
        }}
        .content {{
            padding: 40px;
        }}
        .grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 30px;
            margin-bottom: 40px;
        }}
        .grid.full {{
            grid-template-columns: 1fr;
        }}
        .card {{
            background: #f8f9fa;
            border-radius: 8px;
            padding: 20px;
            border-left: 4px solid #667eea;
        }}
        .card h2 {{
            font-size: 1.3em;
            margin-bottom: 15px;
            color: #333;
        }}
        .chart-container {{
            position: relative;
            height: 300px;
            margin-bottom: 20px;
        }}
        .table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
            font-size: 0.95em;
        }}
        .table th {{
            background: #667eea;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: 600;
        }}
        .table td {{
            padding: 12px;
            border-bottom: 1px solid #e0e0e0;
        }}
        .table tr:hover {{
            background: #f5f5f5;
        }}
        .metric {{
            margin: 10px 0;
            padding: 10px;
            background: white;
            border-radius: 4px;
        }}
        .metric-label {{
            font-weight: 600;
            color: #666;
            font-size: 0.9em;
        }}
        .metric-value {{
            font-size: 1.4em;
            color: #333;
            font-weight: 700;
        }}
        .positive {{
            color: #2ecc71;
        }}
        .negative {{
            color: #e74c3c;
        }}
        .neutral {{
            color: #f39c12;
        }}
        .footer {{
            background: #f8f9fa;
            padding: 20px;
            text-align: center;
            color: #666;
            font-size: 0.9em;
            border-top: 1px solid #e0e0e0;
        }}
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin-bottom: 30px;
        }}
        .summary-card {{
            background: white;
            border: 2px solid #667eea;
            border-radius: 8px;
            padding: 20px;
            text-align: center;
        }}
        .summary-card h3 {{
            font-size: 0.9em;
            color: #666;
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .summary-card .value {{
            font-size: 2em;
            font-weight: 700;
            color: #667eea;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{symbol} {interval}</h1>
            <p>Regime-Specific Performance Analysis</p>
        </div>

        <div class="content">
            <div class="summary-grid">
                <div class="summary-card">
                    <h3>Best Regime</h3>
                    <div class="value">{sources.get("best_regime", "N/A")}</div>
                    <p style="color: #2ecc71; margin-top: 10px;">PF {sources.get("best_pf", 0)}</p>
                </div>
                <div class="summary-card">
                    <h3>Worst Regime</h3>
                    <div class="value">{sources.get("worst_regime", "N/A")}</div>
                    <p style="color: #e74c3c; margin-top: 10px;">PF {sources.get("worst_pf", 0)}</p>
                </div>
                <div class="summary-card">
                    <h3>Total Trades</h3>
                    <div class="value">{sum(analyzer.regime_stats[r].trade_count for r in analyzer.regime_stats)}</div>
                </div>
            </div>

            <div class="grid">
                <div class="card">
                    <h2>Profit Factor by Regime</h2>
                    <div class="chart-container">
                        <canvas id="pfChart"></canvas>
                    </div>
                </div>
                <div class="card">
                    <h2>Trade Count by Regime</h2>
                    <div class="chart-container">
                        <canvas id="countChart"></canvas>
                    </div>
                </div>
            </div>

            <div class="grid">
                <div class="card">
                    <h2>Win Rate by Regime</h2>
                    <div class="chart-container">
                        <canvas id="wrChart"></canvas>
                    </div>
                </div>
                <div class="card">
                    <h2>Total P&L by Regime</h2>
                    <div class="chart-container">
                        <canvas id="pnlChart"></canvas>
                    </div>
                </div>
            </div>

            <div class="grid full">
                <div class="card">
                    <h2>Detailed Metrics Table</h2>
                    <table class="table">
                        <thead>
                            <tr>
                                <th>Regime</th>
                                <th>Trades</th>
                                <th>W / L</th>
                                <th>Win Rate</th>
                                <th>Profit Factor</th>
                                <th>Total P&L</th>
                                <th>Avg Win</th>
                                <th>Avg Loss</th>
                                <th>Sharpe</th>
                            </tr>
                        </thead>
                        <tbody>
"""

    for regime in regimes:
        m = analyzer.regime_stats[regime]
        pf_class = "positive" if m.profit_factor > 1.0 else "negative"
        pnl_class = "positive" if m.total_pnl > 0 else "negative"

        html += f"""
                            <tr>
                                <td><strong>{regime}</strong></td>
                                <td>{m.trade_count}</td>
                                <td>{m.winning_trades} / {m.losing_trades}</td>
                                <td>{m.win_rate:.1%}</td>
                                <td><span class="{pf_class}">{m.profit_factor:.3f}</span></td>
                                <td><span class="{pnl_class}">${m.total_pnl:,.0f}</span></td>
                                <td>${m.avg_win:,.0f}</td>
                                <td>${m.avg_loss:,.0f}</td>
                                <td>{m.sharpe_ratio:.2f}</td>
                            </tr>
"""

    html += (
        """
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <div class="footer">
            Generated by JARVIS TRADER Regime Analysis
        </div>
    </div>

    <script>
        const regimes = """
        + json.dumps(regimes)
        + """;
        const tradeCounts = """
        + json.dumps(trade_counts)
        + """;
        const winRates = """
        + json.dumps(win_rates)
        + """;
        const pfs = """
        + json.dumps(pfs)
        + """;
        const pnls = """
        + json.dumps(pnls)
        + """;
        const colors = """
        + json.dumps(regime_colors)
        + """;

        // Profit Factor Chart
        new Chart(document.getElementById('pfChart'), {
            type: 'bar',
            data: {
                labels: regimes,
                datasets: [{
                    label: 'Profit Factor',
                    data: pfs,
                    backgroundColor: colors,
                    borderColor: colors,
                    borderWidth: 2,
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        ticks: {
                            callback: function(value) { return value.toFixed(2); }
                        }
                    }
                }
            }
        });

        // Trade Count Chart
        new Chart(document.getElementById('countChart'), {
            type: 'doughnut',
            data: {
                labels: regimes,
                datasets: [{
                    data: tradeCounts,
                    backgroundColor: colors,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'bottom' },
                }
            }
        });

        // Win Rate Chart
        new Chart(document.getElementById('wrChart'), {
            type: 'bar',
            data: {
                labels: regimes,
                datasets: [{
                    label: 'Win Rate (%)',
                    data: winRates,
                    backgroundColor: colors,
                    borderColor: colors,
                    borderWidth: 2,
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: {
                        beginAtZero: true,
                        max: 100,
                        ticks: {
                            callback: function(value) { return value.toFixed(0) + '%'; }
                        }
                    }
                }
            }
        });

        // P&L Chart
        new Chart(document.getElementById('pnlChart'), {
            type: 'bar',
            data: {
                labels: regimes,
                datasets: [{
                    label: 'Total P&L ($)',
                    data: pnls,
                    backgroundColor: pnls.map(v => v > 0 ? '#2ecc71' : '#e74c3c'),
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
            }
        });
    </script>
</body>
</html>
"""
    )

    return html


if __name__ == "__main__":
    main()
