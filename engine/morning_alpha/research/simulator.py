from __future__ import annotations

from datetime import datetime
from typing import Iterable, Sequence

from morning_alpha.models import InstrumentSnapshot, MarketBar, SetupCandidate
from morning_alpha.setups.base import SetupContext, SetupDetector


def bars_at_or_before(bars: Iterable[MarketBar], as_of: datetime) -> list[MarketBar]:
    """Return only information available at the historical decision timestamp."""
    return sorted((bar for bar in bars if bar.timestamp <= as_of), key=lambda b: b.timestamp)


class HistoricalSimulator:
    """Minimal event-driven harness that calls the same live detector interface."""

    def detect(
        self,
        detector: SetupDetector,
        snapshot: InstrumentSnapshot,
        context: SetupContext,
    ) -> SetupCandidate | None:
        if snapshot.as_of.tzinfo is None or snapshot.as_of.utcoffset() is None:
            raise ValueError("snapshot as_of must be timezone-aware")
        singular = getattr(context, "catalyst", None)
        plural = getattr(context, "catalysts", ()) or ()
        catalysts = ((singular,) if singular is not None else ()) + tuple(plural)
        for catalyst in catalysts:
            if catalyst.published_at and catalyst.published_at > snapshot.as_of:
                raise ValueError("future catalyst cannot enter historical simulation")
        return detector.evaluate(snapshot, context)

    def historical_window(
        self, bars: Sequence[MarketBar], *, as_of: datetime
    ) -> list[MarketBar]:
        return bars_at_or_before(bars, as_of)
