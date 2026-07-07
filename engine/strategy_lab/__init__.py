"""
Strategy Lab: LLM autonomous strategy improvement loop.

Inspired by: github.com/rv64m/autotrade

Generates STC+ATR strategy parameter variants using Claude,
backtests each variant, applies dual-gate validation (risk + profit),
and accumulates ELIGIBLE winners in results files.

Usage:
    python -m strategy_lab.strategy_loop --symbol MES --max_iterations 20

API:
    POST /strategy-lab/run?symbol=MES&max_iterations=20
    GET  /strategy-lab/results
"""
