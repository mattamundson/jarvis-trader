"""
Session Memory — US-014
Records and retrieves trading lessons learned each session.
Stores to JSON file in data/ directory.
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
SESSION_MEMORY_FILE = DATA_DIR / "session_memory.json"


@dataclass
class Lesson:
    """A lesson learned from a trading session."""

    date: str
    condition: str
    lesson_text: str
    trades_affected: list[str] = field(default_factory=list)
    outcome: str = "neutral"


class SessionMemory:
    """
    Records trading lessons from each session to JSON.
    Retrieves relevant past lessons based on market condition.
    """

    def __init__(self):
        """Initialize session memory."""
        self._ensure_data_dir()
        self.lessons: list[Lesson] = self._load_lessons()
        logger.info(f"SessionMemory initialized with {len(self.lessons)} past lessons")

    def _ensure_data_dir(self) -> None:
        """Ensure data directory exists."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create data directory: {e}")

    def record_session(
        self,
        date: str,
        trades: list[dict],
        market_conditions: dict,
        lessons: list[str],
    ) -> bool:
        """
        Record a trading session's lessons.

        Args:
            date: Session date (ISO format string)
            trades: List of trades executed
            market_conditions: Dict with regime, volatility, etc.
            lessons: List of lesson text strings learned

        Returns:
            True if successfully recorded, False otherwise.
        """
        try:
            condition = market_conditions.get("regime", "unknown")
            trade_ids = [t.get("id", "") for t in trades if t.get("id")]

            win_count = sum(1 for t in trades if t.get("won"))
            loss_count = len(trades) - win_count
            if win_count > loss_count:
                outcome = "positive"
            elif win_count == loss_count:
                outcome = "neutral"
            else:
                outcome = "negative"

            for lesson_text in lessons:
                lesson = Lesson(
                    date=date,
                    condition=condition,
                    lesson_text=lesson_text,
                    trades_affected=trade_ids,
                    outcome=outcome,
                )
                self.lessons.append(lesson)

            self._save_lessons()
            num_lessons = len(lessons)
            num_trades = len(trade_ids)
            logger.info(
                f"Recorded session {date}: {num_lessons} lessons, {num_trades} trades, "
                f"outcome={outcome}"
            )
            return True

        except Exception as e:
            logger.exception(f"Error recording session: {e}")
            return False

    def get_lessons(self, market_condition: str) -> list[Lesson]:
        """
        Retrieve lessons relevant to a market condition.

        Args:
            market_condition: Market regime (e.g., "TRENDING", "CHOPPY")

        Returns:
            List of Lesson objects matching the condition.
        """
        try:
            relevant = [lesson for lesson in self.lessons if lesson.condition == market_condition]
            logger.debug(f"Retrieved {len(relevant)} lessons for condition '{market_condition}'")
            return relevant
        except Exception as e:
            logger.exception(f"Error retrieving lessons: {e}")
            return []

    def get_all_lessons(self) -> list[Lesson]:
        """Get all recorded lessons."""
        return self.lessons.copy()

    def _save_lessons(self) -> None:
        """Save lessons to JSON file."""
        try:
            data = {
                "version": "1.0",
                "last_updated": datetime.utcnow().isoformat(),
                "lessons": [asdict(lesson) for lesson in self.lessons],
            }

            with open(SESSION_MEMORY_FILE, "w") as f:
                json.dump(data, f, indent=2)

            logger.debug(f"Saved {len(self.lessons)} lessons to {SESSION_MEMORY_FILE}")
        except Exception as e:
            logger.exception(f"Error saving lessons: {e}")

    def _load_lessons(self) -> list[Lesson]:
        """Load lessons from JSON file."""
        if not SESSION_MEMORY_FILE.exists():
            logger.debug(f"No existing session memory file at {SESSION_MEMORY_FILE}")
            return []

        try:
            with open(SESSION_MEMORY_FILE, "r") as f:
                data = json.load(f)

            lessons = [Lesson(**lesson) for lesson in data.get("lessons", [])]
            logger.debug(f"Loaded {len(lessons)} lessons from file")
            return lessons

        except json.JSONDecodeError as e:
            logger.warning(f"Corrupted session memory file: {e}")
            return []
        except Exception as e:
            logger.exception(f"Error loading lessons: {e}")
            return []

    def clear_lessons(self) -> None:
        """Clear all lessons (for testing only)."""
        self.lessons = []
        self._save_lessons()
        logger.warning("Session memory cleared")
