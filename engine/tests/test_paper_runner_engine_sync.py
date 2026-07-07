"""
Guard: paper_runner optional A→B sync must target the same route as portfolio_router.

Ops: set JARVIS_ENGINE_URL and JARVIS_API_KEY so opens/closes POST to the engine.
"""

from __future__ import annotations

from pathlib import Path


def test_paper_runner_posts_to_portfolio_paper_trade() -> None:
    root = Path(__file__).resolve().parents[1]
    src = (root / "backtest" / "paper_runner.py").read_text(encoding="utf-8")
    assert "/portfolio/paper/trade" in src
    assert "JARVIS_ENGINE_URL" in src
    assert "JARVIS_API_KEY" in src or "X_API_KEY" in src
