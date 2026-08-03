"""
mes_monitor_cli.py

CLI entrypoint for the MES 24x7 monitor.
Loads config, prints status, and can run the orchestrator.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

from engine.monitors.mes_level_monitor import Candle, LevelMonitorConfig, MesLevelMonitor
from engine.monitors.mes_monitor_orchestrator import MesMonitorOrchestrator
from engine.monitors.mes_regime_filter import RegimeConfig, RegimeInputs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_level_config(raw: dict) -> LevelMonitorConfig:
    levels = raw.get("levels", {})
    return LevelMonitorConfig(
        symbol=raw.get("symbol", "MES"),
        pullback_low=float(levels.get("pullback_long_zone", {}).get("low", 7615)),
        pullback_high=float(levels.get("pullback_long_zone", {}).get("high", 7625)),
        breakout_level=float(levels.get("breakout_long_level", 7635)),
        chop_threshold=float(levels.get("no_trade_chop_threshold", 3.5)),
    )


def build_regime_config(raw: dict) -> RegimeConfig:
    regime = raw.get("regime", {})
    return RegimeConfig(
        vix_hard_stop=float(regime.get("vix_hard_stop", 18.0)),
        vix_ideal_max=float(regime.get("vix_ideal_max", 15.0)),
        news_blackout_minutes=int(regime.get("news_blackout_minutes", 60)),
        max_risk_per_trade=float(regime.get("max_risk_per_trade", 125.0)),
        daily_loss_limit=float(regime.get("daily_loss_limit", 375.0)),
    )


def cmd_status(args: argparse.Namespace) -> int:
    raw = load_config(Path(args.config))
    level_cfg = build_level_config(raw)
    regime_cfg = build_regime_config(raw)
    print(f"symbol={level_cfg.symbol}")
    print(f"pullback_zone={level_cfg.pullback_low}-{level_cfg.pullback_high}")
    print(f"breakout_level={level_cfg.breakout_level}")
    print(f"chop_threshold={level_cfg.chop_threshold}")
    print(f"vix_hard_stop={regime_cfg.vix_hard_stop}")
    print(f"daily_loss_limit={regime_cfg.daily_loss_limit}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    raw = load_config(Path(args.config))
    level_cfg = build_level_config(raw)
    regime_cfg = build_regime_config(raw)
    orch = MesMonitorOrchestrator(level_config=level_cfg, regime_config=regime_cfg)

    # Placeholder input set; replace with live data ingestion.
    candles = [Candle(symbol=level_cfg.symbol, timeframe="5min", open_=7618, high=7628, low=7612, close_=7620, volume=1000)]
    verdict = orch.run(candles, RegimeInputs(vix=14.0))
    print(f"should_alert={verdict.should_alert}")
    print(f"direction={verdict.direction}")
    print(f"confidence={verdict.confidence:.2f}")
    print(f"price={verdict.price:.2f}")
    print(f"reason={verdict.reason}")
    print(f"regime_reason={verdict.regime_reason}")
    print(f"risk_scale={verdict.risk_scale:.2f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MES 24x7 monitor CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Run monitor once")
    run_parser.add_argument("--config", default="engine/config/mes_monitor_config.yaml")
    run_parser.set_defaults(func=cmd_run)

    status_parser = sub.add_parser("status", help="Print loaded monitor config")
    status_parser.add_argument("--config", default="engine/config/mes_monitor_config.yaml")
    status_parser.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
