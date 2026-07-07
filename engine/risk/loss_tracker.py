"""
JARVIS TRADER — Consecutive Loss Tracker
============================================
Tracks consecutive losing trades per symbol and globally.
Implements position sizing reduction based on loss streaks.

Persistence: State stored in engine/data/loss_tracker.json
This allows loss tracking to survive application restarts.

Design principle: Non-LLM deterministic rules. All position size
reductions are hardcoded based on consecutive loss count.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── Data classes ───────────────────────────────────────────────────────────


@dataclass
class LossTrackerState:
    """
    Persisted state for loss tracking.

    Fields:
        global_consecutive_losses: Total consecutive losing trades (all symbols)
        symbol_losses: Dict[symbol] -> count of consecutive losses for that symbol
        last_trade_symbol: Which symbol was the last trade on
        last_trade_timestamp: When the last trade was executed
        halt_until: Timestamp when trading can resume (if halted)
    """

    global_consecutive_losses: int = 0
    symbol_losses: dict[str, int] = field(default_factory=dict)
    last_trade_symbol: Optional[str] = None
    last_trade_timestamp: Optional[str] = None
    halt_until: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> LossTrackerState:
        return LossTrackerState(**data)


class ConsecutiveLossTracker:
    """
    Tracks consecutive losing trades and modulates position size.

    Public API:
        record_trade(symbol, pnl) -> bool : Records a trade, returns True if winning
        get_consecutive_losses(symbol=None) -> int : Get loss count (None = global)
        get_position_size_multiplier() -> float : 1.0 / 0.5 / 0.25 / 0.0
        reset(symbol=None) -> None : Reset loss counter
        is_halted() -> bool : Check if trading is paused
        get_halt_reason() -> str : Human-readable halt reason
    """

    # Module-relative default: engine/risk/loss_tracker.py -> engine/data.
    # Resolving from __file__ keeps the fallback correct regardless of the
    # process cwd (production passes data_dir="data" explicitly via main.py).
    _DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

    def __init__(
        self,
        data_dir: str | Path | None = None,
        consecutive_loss_half_size: int = 3,
        consecutive_loss_quarter_size: int = 5,
        consecutive_loss_halt: int = 7,
        consecutive_loss_halt_hours: int = 24,
    ):
        """
        Parameters
        ----------
        data_dir : str | Path | None
            Directory for persisting loss_tracker.json. None -> engine/data
            (resolved relative to this module).
        consecutive_loss_half_size : int
            Number of consecutive losses before position size → 0.5x
        consecutive_loss_quarter_size : int
            Number of consecutive losses before position size → 0.25x
        consecutive_loss_halt : int
            Number of consecutive losses before trading is halted
        consecutive_loss_halt_hours : int
            Duration (hours) to halt trading
        """
        self._data_dir = Path(data_dir) if data_dir is not None else self._DEFAULT_DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._state_file = self._data_dir / "loss_tracker.json"

        self._config = {
            "consecutive_loss_half_size": consecutive_loss_half_size,
            "consecutive_loss_quarter_size": consecutive_loss_quarter_size,
            "consecutive_loss_halt": consecutive_loss_halt,
            "consecutive_loss_halt_hours": consecutive_loss_halt_hours,
        }

        # Load or initialize state
        self._state = self._load_state()

    # ── State Management ───────────────────────────────────────────────────

    def _load_state(self) -> LossTrackerState:
        """Load state from JSON file, or initialize empty state."""
        if self._state_file.exists():
            try:
                with open(self._state_file, "r") as f:
                    data = json.load(f)
                logger.info(f"Loaded loss tracker state from {self._state_file}")
                return LossTrackerState.from_dict(data)
            except Exception as e:
                logger.error(f"Failed to load loss tracker state: {e}. Initializing empty.")
                return LossTrackerState()
        return LossTrackerState()

    def _save_state(self) -> None:
        """Persist state to JSON file."""
        try:
            with open(self._state_file, "w") as f:
                json.dump(self._state.to_dict(), f, indent=2, default=str)
            logger.debug(f"Saved loss tracker state to {self._state_file}")
        except Exception as e:
            logger.error(f"Failed to save loss tracker state: {e}")

    # ── Trade Recording ───────────────────────────────────────────────────

    def record_trade(self, symbol: str, pnl: float) -> bool:
        """
        Record a trade result and update loss counters.

        Parameters
        ----------
        symbol : str
            Trading symbol (e.g., "MES", "AAPL")
        pnl : float
            Profit/loss in dollars. Positive = win, negative = loss

        Returns
        -------
        bool
            True if this was a winning trade, False if losing
        """
        is_win = pnl >= 0.0
        now = datetime.now(timezone.utc).isoformat()

        if is_win:
            # Winner resets global counter
            old_global = self._state.global_consecutive_losses
            self._state.global_consecutive_losses = 0
            self._state.halt_until = None  # Also clear halt if resetting

            # Winner resets symbol counter
            if symbol in self._state.symbol_losses:
                old_symbol = self._state.symbol_losses[symbol]
                self._state.symbol_losses[symbol] = 0
                logger.info(
                    f"Trade WINNER: {symbol} PnL=${pnl:.2f} | "
                    f"Reset global {old_global}→0, symbol {old_symbol}→0"
                )
            else:
                logger.info(f"Trade WINNER: {symbol} PnL=${pnl:.2f} | Reset global {old_global}→0")
        else:
            # Loser increments both counters
            self._state.global_consecutive_losses += 1
            symbol_count = self._state.symbol_losses.get(symbol, 0) + 1
            self._state.symbol_losses[symbol] = symbol_count

            # Check if halt threshold reached
            if self._state.global_consecutive_losses >= self._config["consecutive_loss_halt"]:
                self._activate_halt()

            logger.warning(
                f"Trade LOSER: {symbol} PnL=${pnl:.2f} | "
                f"Consecutive losses: global={self._state.global_consecutive_losses}, "
                f"symbol={symbol_count}"
            )

        self._state.last_trade_symbol = symbol
        self._state.last_trade_timestamp = now
        self._save_state()

        return is_win

    # ── Loss Query ─────────────────────────────────────────────────────────

    def get_consecutive_losses(self, symbol: Optional[str] = None) -> int:
        """
        Get consecutive loss count.

        Parameters
        ----------
        symbol : str | None
            If None, return global count. Otherwise return count for this symbol.

        Returns
        -------
        int
            Number of consecutive losses
        """
        if symbol is None:
            return self._state.global_consecutive_losses
        return self._state.symbol_losses.get(symbol, 0)

    # ── Position Size Multiplier ───────────────────────────────────────────

    def get_position_size_multiplier(self) -> float:
        """
        Return position size multiplier based on consecutive losses.

        Rules (global losses):
            0-2 losses: 1.0x (normal)
            3 losses: 0.5x (half size)
            5 losses: 0.25x (quarter size)
            7+ losses: 0.0x (HALT — 24 hours)

        Returns
        -------
        float
            Multiplier: 1.0, 0.5, 0.25, or 0.0
        """
        # Check if halt is currently active
        if self.is_halted():
            return 0.0

        losses = self._state.global_consecutive_losses
        halt_threshold = self._config["consecutive_loss_halt"]
        quarter_threshold = self._config["consecutive_loss_quarter_size"]
        half_threshold = self._config["consecutive_loss_half_size"]

        if losses >= halt_threshold:
            return 0.0
        elif losses >= quarter_threshold:
            return 0.25
        elif losses >= half_threshold:
            return 0.5
        else:
            return 1.0

    # ── Trading Halt ───────────────────────────────────────────────────────

    def _activate_halt(self) -> None:
        """Activate trading halt for the configured duration."""
        halt_hours = self._config["consecutive_loss_halt_hours"]
        halt_until = datetime.now(timezone.utc) + timedelta(hours=halt_hours)
        self._state.halt_until = halt_until.isoformat()
        self._save_state()
        logger.critical(
            f"TRADING HALTED for {halt_hours} hours due to {self._state.global_consecutive_losses} "
            f"consecutive losses. Resume trading at {self._state.halt_until}"
        )

    def is_halted(self) -> bool:
        """Check if trading halt is currently active."""
        if self._state.halt_until is None:
            return False

        halt_until = datetime.fromisoformat(self._state.halt_until)
        now = datetime.now(timezone.utc)

        if now >= halt_until:
            # Halt period expired, auto-clear it
            self._state.halt_until = None
            self._save_state()
            logger.info("Trading halt period expired, resuming normal operations")
            return False

        return True

    def get_halt_reason(self) -> str:
        """Return human-readable halt reason."""
        if not self.is_halted():
            return ""

        losses = self._state.global_consecutive_losses
        halt_until = self._state.halt_until
        return (
            f"Consecutive loss limit reached ({losses} losses) — trading paused until {halt_until}"
        )

    # ── Reset API ──────────────────────────────────────────────────────────

    def reset(self, symbol: Optional[str] = None) -> None:
        """
        Manually reset loss counter (for human review/intervention).

        Parameters
        ----------
        symbol : str | None
            If None, reset global counter and all symbols. Otherwise reset for this symbol only.
        """
        if symbol is None:
            old_global = self._state.global_consecutive_losses
            self._state.global_consecutive_losses = 0
            self._state.symbol_losses = {}  # Clear all symbol losses
            self._state.halt_until = None  # Also clear halt
            self._save_state()
            logger.warning(
                f"[MANUAL RESET] Global consecutive losses: {old_global} → 0 (all symbols reset)"
            )
        else:
            old_symbol = self._state.symbol_losses.get(symbol, 0)
            self._state.symbol_losses[symbol] = 0
            self._save_state()
            logger.warning(f"[MANUAL RESET] Symbol {symbol} consecutive losses: {old_symbol} → 0")

    # ── Status Report ──────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """
        Return comprehensive status report.

        Returns
        -------
        dict with keys:
            global_consecutive_losses: int
            symbol_losses: dict[str, int]
            position_size_multiplier: float
            is_halted: bool
            halt_until: str | None
            last_trade_symbol: str | None
            last_trade_timestamp: str | None
            config: dict
        """
        return {
            "global_consecutive_losses": self._state.global_consecutive_losses,
            "symbol_losses": self._state.symbol_losses,
            "position_size_multiplier": self.get_position_size_multiplier(),
            "is_halted": self.is_halted(),
            "halt_until": self._state.halt_until,
            "last_trade_symbol": self._state.last_trade_symbol,
            "last_trade_timestamp": self._state.last_trade_timestamp,
            "config": self._config,
        }
