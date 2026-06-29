"""Phase 1c — unified per-symbol trading-status reconciliation.

The honest "what's trading now" spine. Three config layers have historically
disagreed about whether a symbol trades:

  * ``backtest/paper_config.py``      — the ``enabled`` flag per instrument
  * ``backtest/signals.py``          — ``DO_NOT_TRADE_SYMBOLS`` (the blocklist)
  * the gate-v2 verdict ledger       — latest PASS/FAIL/INSUFFICIENT_SAMPLE

This module collapses them into ONE per-symbol view and, crucially, **flags any
disagreement** between the layers (the split-brain that `test_paper_config_donottrade_sync`
guards at the config level — surfaced here as a live, observable signal).

Pure logic by design: every source is injected via a callable, so this is fully
unit-testable without files, a database, or a running engine. The router
(`routers/trading_status_router.py`) wires the real sources in.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

# Verdict strings that mean "the gate is intentionally withholding trades while
# more data accrues" — an ENABLED symbol sitting in one of these is EXPECTED
# (e.g. MES trend polling for OOS samples), NOT a config contradiction.
_PENDING_VERDICTS = frozenset({"INSUFFICIENT_SAMPLE", "INSUFFICIENT_DATA", "PENDING", "NO_VERDICT"})


@dataclass
class SymbolStatus:
    """One symbol's reconciled trading status across all three authority layers."""

    symbol: str
    enabled: bool                         # paper_config.enabled
    authorized: bool                      # NOT in DO_NOT_TRADE_SYMBOLS
    verdict: Optional[str]                # latest gate-v2 verdict, or None if no file
    verdict_family: Optional[str]
    verdict_created_at: Optional[str]
    verdict_age_days: Optional[float]     # None if created_at unparseable / no clock
    oos_trades: Optional[int]
    # Derived single-truth:
    tradeable: bool                       # would actually place a trade right now
    config_agrees: bool                   # the three layers are mutually consistent
    disagreements: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_age_days(created_at: Optional[str], now: Optional[datetime]) -> Optional[float]:
    """Age of an ISO-8601 ``created_at`` in days vs ``now``. None if either is
    missing or the timestamp can't be parsed — never raises."""
    if not created_at or now is None:
        return None
    try:
        ts = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return round((now - ts).total_seconds() / 86400.0, 2)


def build_symbol_status(
    symbol: str,
    *,
    enabled: bool,
    authorized: bool,
    verdict_row: Optional[dict[str, Any]],
    now: Optional[datetime] = None,
) -> SymbolStatus:
    """Reconcile one symbol. ``verdict_row`` is a ledger row (see
    ``strategy_ledger_router.find_verdict``) or None when no verdict exists."""
    row = verdict_row or {}
    verdict = row.get("verdict")
    verdict_norm = (verdict or "").upper() or None

    tradeable = bool(enabled and authorized and verdict_norm == "PASS")

    disagreements: list[str] = []
    # (1) Hard contradiction: config says trade it, blocklist says never.
    if enabled and not authorized:
        disagreements.append(
            "enabled in paper_config but present in DO_NOT_TRADE_SYMBOLS"
        )
    # (2) Trading a strategy the gate has FAILed.
    if enabled and verdict_norm == "FAIL":
        disagreements.append("enabled but latest gate-v2 verdict is FAIL")
    # (3) Enabled with no verdict at all — can't confirm it should trade.
    if enabled and verdict_norm is None:
        disagreements.append("enabled but no gate-v2 verdict on file")
    # (4) A validated, authorized edge left switched off (stale disable / missed).
    if (not enabled) and authorized and verdict_norm == "PASS":
        disagreements.append(
            "gate-v2 PASS and authorized but disabled in paper_config"
        )
    # Note: enabled + a _PENDING_VERDICTS state is INTENTIONAL (data-gathering),
    # so it is deliberately NOT a disagreement.

    return SymbolStatus(
        symbol=symbol,
        enabled=enabled,
        authorized=authorized,
        verdict=verdict,
        verdict_family=row.get("family"),
        verdict_created_at=row.get("created_at"),
        verdict_age_days=_parse_age_days(row.get("created_at"), now),
        oos_trades=row.get("oos_trades"),
        tradeable=tradeable,
        config_agrees=not disagreements,
        disagreements=disagreements,
    )


def build_trading_status(
    symbols: list[str],
    *,
    enabled_for: Callable[[str], bool],
    authorized_for: Callable[[str], bool],
    verdict_for: Callable[[str], Optional[dict[str, Any]]],
    now: Optional[datetime] = None,
) -> list[SymbolStatus]:
    """Reconcile a set of symbols into per-symbol statuses, sorted symbol-asc.

    All three sources are injected as callables so the engine wiring and the
    tests share one code path. ``verdict_for`` must never raise — wrap lookups
    that might (the ledger reader already returns None on malformed files)."""
    out: list[SymbolStatus] = []
    for sym in sorted(set(symbols)):
        out.append(
            build_symbol_status(
                sym,
                enabled=bool(enabled_for(sym)),
                authorized=bool(authorized_for(sym)),
                verdict_row=verdict_for(sym),
                now=now,
            )
        )
    return out


def summarize(statuses: list[SymbolStatus]) -> dict[str, Any]:
    """Roll-up counts for the surface header."""
    return {
        "total": len(statuses),
        "tradeable": sum(1 for s in statuses if s.tradeable),
        "enabled": sum(1 for s in statuses if s.enabled),
        "disagreements": sum(1 for s in statuses if not s.config_agrees),
    }
