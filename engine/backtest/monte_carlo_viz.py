"""
JARVIS TRADER — Monte Carlo Visualization Helper
==================================================

Generates interactive HTML equity curve fan charts showing:
  - Median equity curve (solid line)
  - 25th-75th percentile band (darker shading)
  - 5th-95th percentile band (lighter shading)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import numpy as np


def generate_equity_curves_for_sims(
    trades_list: List[Dict],
    n_simulations: int,
    initial_capital: float,
    max_slippage_ticks: float = 0.0,
    symbol: str = "MES",
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate equity curves for all simulations with slippage.

    Args:
        trades_list: List of dicts with 'pnl' key from JSON
        n_simulations: Number of simulations to run
        initial_capital: Starting capital
        max_slippage_ticks: Max random slippage per trade in ticks
        symbol: Instrument symbol for tick value
        seed: Random seed

    Returns:
        Tuple of (equity_curves_array, x_axis_array)
        - equity_curves: shape (n_simulations, n_trades+1)
        - x_axis: shape (n_trades+1,) — trade indices 0..n_trades
    """
    from backtest.contract_specs import CONTRACT_SPECS

    pnls = np.array([t["pnl"] for t in trades_list], dtype=np.float64)
    n_trades = len(pnls)

    if n_trades == 0:
        return np.array([]).reshape(0, 1), np.array([0])

    # Setup RNG
    rng = np.random.default_rng(seed)

    # Build shuffled index matrix
    idx_matrix = np.tile(np.arange(n_trades), (n_simulations, 1))
    for i in range(n_simulations):
        rng.shuffle(idx_matrix[i])

    # Gather shuffled P&Ls
    shuffled_pnls = pnls[idx_matrix]  # (n_simulations, n_trades)

    # Apply slippage
    if max_slippage_ticks > 0:
        spec = CONTRACT_SPECS.get(symbol.upper())
        tick_value = spec.tick_value if spec is not None else 0.01
        slippage_ticks = rng.uniform(0, max_slippage_ticks, size=(n_simulations, n_trades))
        slippage_dollars = slippage_ticks * tick_value
        shuffled_pnls = shuffled_pnls - slippage_dollars

    # Build cumulative equity curves
    cum_pnls = np.cumsum(shuffled_pnls, axis=1)
    init_col = np.full((n_simulations, 1), initial_capital)
    equities = np.hstack([init_col, initial_capital + cum_pnls])

    # X-axis: trade numbers 0, 1, 2, ..., n_trades
    x_axis = np.arange(n_trades + 1)

    return equities, x_axis


def compute_percentile_curves(
    equity_curves: np.ndarray,
) -> Dict[str, List[float]]:
    """Compute percentile equity curves.

    Args:
        equity_curves: shape (n_simulations, n_trades+1)

    Returns:
        Dictionary with keys: p5, p25, median, p75, p95
        Each value is a list of equity values across trades
    """
    return {
        "p5": np.percentile(equity_curves, 5, axis=0).tolist(),
        "p25": np.percentile(equity_curves, 25, axis=0).tolist(),
        "median": np.percentile(equity_curves, 50, axis=0).tolist(),
        "p75": np.percentile(equity_curves, 75, axis=0).tolist(),
        "p95": np.percentile(equity_curves, 95, axis=0).tolist(),
    }


def generate_html_chart(
    percentiles: Dict[str, List[float]],
    x_axis: np.ndarray,
    initial_capital: float,
    symbol: str = "MES",
    interval: str = "1h",
    title_suffix: str = "",
) -> str:
    """Generate interactive HTML equity curve fan chart using Chart.js.

    Args:
        percentiles: Dict from compute_percentile_curves()
        x_axis: Trade indices (0, 1, 2, ...)
        initial_capital: Starting capital for baseline
        symbol: Instrument symbol (for title)
        interval: Timeframe (for title)
        title_suffix: Additional text for title

    Returns:
        HTML string with embedded Chart.js visualization
    """
    x_labels = [str(i) for i in x_axis]

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Monte Carlo Analysis - {symbol} {interval}{title_suffix}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            margin: 0;
            min-height: 100vh;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            padding: 30px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        }}
        h1 {{
            color: #333;
            text-align: center;
            margin-bottom: 10px;
            font-size: 28px;
        }}
        .subtitle {{
            color: #666;
            text-align: center;
            margin-bottom: 30px;
            font-size: 14px;
        }}
        .chart-wrapper {{
            position: relative;
            height: 500px;
            margin: 30px 0;
        }}
        .legend {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 30px 0;
            padding: 20px;
            background: #f9f9f9;
            border-radius: 6px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 13px;
        }}
        .legend-color {{
            width: 20px;
            height: 3px;
            border-radius: 2px;
        }}
        .description {{
            color: #666;
            font-size: 13px;
            line-height: 1.6;
            margin-top: 30px;
            padding: 20px;
            background: #f0f4ff;
            border-left: 4px solid #667eea;
            border-radius: 4px;
        }}
        .footer {{
            text-align: center;
            color: #999;
            font-size: 12px;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #eee;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Monte Carlo Equity Curve Analysis</h1>
        <div class="subtitle">{symbol} {interval} • Percentile Distribution of 1,000 Simulations{title_suffix}</div>

        <div class="legend">
            <div class="legend-item">
                <div class="legend-color" style="background: #667eea; height: 2px;"></div>
                <span><strong>Median</strong> (50th percentile)</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background: rgba(102, 126, 234, 0.3); height: 12px;"></div>
                <span><strong>Core Range</strong> (25th-75th percentile)</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background: rgba(102, 126, 234, 0.1); height: 12px;"></div>
                <span><strong>Confidence Interval</strong> (5th-95th percentile)</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background: #e0e0e0; height: 1px;"></div>
                <span><strong>Breakeven</strong> (starting capital)</span>
            </div>
        </div>

        <div class="chart-wrapper">
            <canvas id="fanChart"></canvas>
        </div>

        <div class="description">
            <strong>Interpretation:</strong><br>
            The fan chart shows the distribution of equity curves across 1,000 Monte Carlo simulations, each with randomly shuffled trade order.
            The wider the bands, the more variance in outcomes. A median line in the upper portion of the confidence interval suggests
            the strategy is robust to trade sequencing risk. Upward-trending percentiles (especially p95) indicate consistent profitability
            across shuffle scenarios.
        </div>

        <div class="footer">Generated by JARVIS TRADER Monte Carlo Suite</div>
    </div>

    <script>
        const ctx = document.getElementById('fanChart').getContext('2d');
        const xLabels = {json.dumps(x_labels)};
        const p5Data = {json.dumps(percentiles["p5"])};
        const p25Data = {json.dumps(percentiles["p25"])};
        const medianData = {json.dumps(percentiles["median"])};
        const p75Data = {json.dumps(percentiles["p75"])};
        const p95Data = {json.dumps(percentiles["p95"])};
        const breakeven = {initial_capital};

        const chart = new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: xLabels,
                datasets: [
                    // 5th-95th percentile band (lightest)
                    {{
                        label: '5th-95th percentile band',
                        data: p5Data,
                        borderColor: 'transparent',
                        backgroundColor: 'rgba(102, 126, 234, 0.08)',
                        pointRadius: 0,
                        borderWidth: 0,
                        fill: true,
                        order: 5,
                    }},
                    {{
                        label: '',
                        data: p95Data,
                        borderColor: 'transparent',
                        backgroundColor: 'transparent',
                        pointRadius: 0,
                        borderWidth: 0,
                        fill: '-1',
                        order: 5,
                    }},
                    // 25th-75th percentile band (darker)
                    {{
                        label: '25th-75th percentile band',
                        data: p25Data,
                        borderColor: 'transparent',
                        backgroundColor: 'rgba(102, 126, 234, 0.15)',
                        pointRadius: 0,
                        borderWidth: 0,
                        fill: true,
                        order: 4,
                    }},
                    {{
                        label: '',
                        data: p75Data,
                        borderColor: 'transparent',
                        backgroundColor: 'transparent',
                        pointRadius: 0,
                        borderWidth: 0,
                        fill: '-1',
                        order: 4,
                    }},
                    // Median line
                    {{
                        label: 'Median (50th percentile)',
                        data: medianData,
                        borderColor: '#667eea',
                        backgroundColor: 'transparent',
                        pointRadius: 0,
                        borderWidth: 2.5,
                        fill: false,
                        tension: 0.1,
                        order: 1,
                    }},
                    // Breakeven line
                    {{
                        label: 'Breakeven (starting capital)',
                        data: Array(xLabels.length).fill(breakeven),
                        borderColor: '#999',
                        backgroundColor: 'transparent',
                        pointRadius: 0,
                        borderWidth: 1,
                        borderDash: [5, 5],
                        fill: false,
                        order: 2,
                    }},
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                interaction: {{
                    mode: 'index',
                    intersect: false,
                }},
                plugins: {{
                    legend: {{
                        labels: {{
                            usePointStyle: false,
                            filter: function(item) {{
                                return item.text !== '';
                            }},
                            padding: 15,
                            font: {{
                                size: 12,
                            }},
                        }},
                    }},
                    tooltip: {{
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        padding: 12,
                        titleFont: {{ size: 13, weight: 'bold' }},
                        bodyFont: {{ size: 12 }},
                        borderColor: '#667eea',
                        borderWidth: 1,
                    }},
                }},
                scales: {{
                    x: {{
                        title: {{
                            display: true,
                            text: 'Trade Number',
                            font: {{ size: 13, weight: 'bold' }},
                        }},
                        ticks: {{
                            maxTicksLimit: 15,
                        }},
                    }},
                    y: {{
                        title: {{
                            display: true,
                            text: 'Portfolio Equity ($)',
                            font: {{ size: 13, weight: 'bold' }},
                        }},
                        ticks: {{
                            callback: function(value) {{
                                return '$' + value.toLocaleString('en-US', {{
                                    maximumFractionDigits: 0
                                }});
                            }},
                        }},
                    }},
                }},
            }},
        }});
    </script>
</body>
</html>
"""
    return html


def save_fan_chart(
    results_json_path: str,
    output_html_path: str = None,
    original_json_path: str = None,
) -> str:
    """Load Monte Carlo results and generate interactive HTML fan chart.

    Args:
        results_json_path: Path to JSON results file (original backtest or Monte Carlo JSON)
        output_html_path: Output HTML path (auto-generated if None)
        original_json_path: Path to original backtest JSON if results_json_path is Monte Carlo output

    Returns:
        Path to generated HTML file
    """
    results_path = Path(results_json_path)

    # Load JSON results
    with open(results_path, "r") as f:
        data = json.load(f)

    # Extract metadata
    symbol = data.get("symbol", "MES")
    interval = data.get("interval", "1h")
    initial_capital = data.get("initial_capital", 10_000)
    max_slippage = data.get("max_slippage_ticks", 0)

    # Get trades list
    trades_list = data.get("trades_list", [])
    if not trades_list:
        # Try alternate format
        full_metrics = data.get("full_metrics", {})
        trades_list = full_metrics.get("trades", [])

    # If no trades in current file, try to load from original_json_path
    if not trades_list and original_json_path:
        with open(original_json_path, "r") as f:
            orig_data = json.load(f)
        trades_list = orig_data.get("trades_list", [])
        if not trades_list:
            orig_full = orig_data.get("full_metrics", {})
            trades_list = orig_full.get("trades", [])

    if not trades_list:
        raise ValueError(f"No trades found in {results_json_path}")

    # Determine output path
    if output_html_path is None:
        mode_tag = ""
        if max_slippage and max_slippage > 0:
            mode_tag = f"_slip{int(max_slippage)}tk"
        output_html_path = (
            results_path.parent / f"{symbol}_{interval}_monte_carlo{mode_tag}_chart.html"
        )
    else:
        output_html_path = Path(output_html_path)

    # Generate curves
    print("Generating equity curves for visualization...")
    equity_curves, x_axis = generate_equity_curves_for_sims(
        trades_list,
        n_simulations=1_000,
        initial_capital=initial_capital,
        max_slippage_ticks=max_slippage,
        symbol=symbol,
    )

    if len(equity_curves) == 0:
        raise ValueError("No equity curves generated (no trades?)")

    # Compute percentiles
    percentiles = compute_percentile_curves(equity_curves)

    # Title suffix
    title_suffix = ""
    if max_slippage and max_slippage > 0:
        title_suffix = f" • Slippage {max_slippage}t"

    # Generate HTML
    html_content = generate_html_chart(
        percentiles,
        x_axis,
        initial_capital,
        symbol=symbol,
        interval=interval,
        title_suffix=title_suffix,
    )

    # Save
    output_html_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_html_path, "w") as f:
        f.write(html_content)

    return str(output_html_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate Monte Carlo visualization")
    parser.add_argument(
        "--json", required=True, help="Path to backtest or Monte Carlo JSON results"
    )
    parser.add_argument(
        "--original",
        default=None,
        help="Path to original backtest JSON (if --json is Monte Carlo output)",
    )
    parser.add_argument(
        "--output", default=None, help="Output HTML path (auto-generated if not provided)"
    )
    args = parser.parse_args()

    html_path = save_fan_chart(args.json, args.output, args.original)
    print(f"Chart saved: {html_path}")
