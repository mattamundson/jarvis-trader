"""Systematic signal -> paper-order bridge (Wave 2 / lane 2).

Turns a generated entry signal for a GRADUATED (deployed_live) candidate into a
paper order through the SafetyLayer -- the only approved broker path. This closes
the "validated -> tradeable" gap WITHOUT routing every trade through the per-trade
human approval queue, while preserving every existing safety gate.

SAFETY POSTURE -- everything here is default-OFF and cannot fire on its own:
  * Master switch ``SYSTEMATIC_AUTO_EXECUTE`` (env, default "0"). When off,
    ``execute_signal`` short-circuits and submits NOTHING. This is the whole-module
    kill switch; the bridge is inert until Amo flips it (Tier-3).
  * Candidate gate: only a single ``deployed_live`` candidate per symbol executes
    (``candidate_registry.live_candidate_for_symbol``, which is fail-safe on the
    zero/ambiguous case). A signal whose candidate is not the deployed one is
    skipped, never guessed.
  * Routes through ``SafetyLayer.submit_paper_order`` -> all 14 risk checks + IB
    paper port 4002 only (live ports are rejected at the gateway). LIVE_TRADING_
    ENABLED is enforced downstream by the SafetyLayer gate; it is NOT bypassed here.
  * NOT wired to any scheduler or pipeline. There is no production caller in the
    engine, so it cannot trade autonomously until a scheduled task / pipeline hook
    is added -- another explicit Tier-3 step.
  * Idempotent: every (candidate_id, symbol, signal_date) is recorded in a JSONL
    ledger and a repeat signal is skipped, so a re-run never double-submits.

The class is fully injectable (safety_layer, registry dict, ledger_path,
auto_execute) so it unit-tests against a mocked SafetyLayer with zero broker risk.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Optional

from backtest.candidate_registry import live_candidate_for_symbol
from execution.submission_dedup import SubmissionDedup

_HERE = Path(__file__).resolve().parent
# Runtime ledger lives under the gitignored engine/data/ tree.
_DEFAULT_LEDGER = _HERE.parent / "data" / "systematic_exec" / "exec_ledger.jsonl"


def _default_live_trading_check() -> bool:
    """Return True if the system is in LIVE trading mode (fresh config read).

    Fail-CLOSED: if the live state cannot be determined, return True so the
    bridge refuses to submit -- an autonomous order path must never proceed when
    it cannot confirm it is in paper mode.
    """
    try:
        from config import settings

        return bool(getattr(settings, "LIVE_TRADING_ENABLED", False))
    except Exception:
        return True


class LiveSignalExecutor:
    """Bridge a generated signal to a paper order through the SafetyLayer."""

    def __init__(
        self,
        safety_layer: Any,
        registry: Optional[dict[str, Any]] = None,
        *,
        ledger_path: Optional[Path | str] = None,
        auto_execute: Optional[bool] = None,
        dedup: Optional[SubmissionDedup] = None,
        live_trading_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._safety = safety_layer
        self._registry = registry  # None -> candidate_registry loads its default lock
        self._ledger_path = Path(ledger_path) if ledger_path else _DEFAULT_LEDGER
        if auto_execute is None:
            auto_execute = os.getenv("SYSTEMATIC_AUTO_EXECUTE", "0") == "1"
        self._auto = bool(auto_execute)
        # Shared cross-path dedup ledger (auto-approve queue + this bridge).
        self._dedup = dedup if dedup is not None else SubmissionDedup()
        self._live_trading_check = live_trading_check or _default_live_trading_check

    def _is_killed(self) -> bool:
        """Kill-switch state via the SafetyLayer's accessor; fail-closed.

        ``SafetyLayer.is_killed`` is a ``@property`` (so ``getattr`` returns a
        bool, not a callable); a method/callable is also supported. A missing
        accessor or any error fails CLOSED (refuse) -- we never assume "safe"
        when the state cannot be confirmed.
        """
        try:
            val = getattr(self._safety, "is_killed", None)
            if val is None:
                return True  # no accessor -> cannot confirm safe -> refuse
            return bool(val()) if callable(val) else bool(val)
        except Exception:
            return True  # any failure to read kill state -> refuse (fail-closed)

    # -- ledger helpers ---------------------------------------------------
    @staticmethod
    def _signal_key(candidate_id: str, symbol: str, signal_date: str) -> str:
        return f"{candidate_id}|{symbol.upper()}|{signal_date}"

    def _seen_keys(self) -> set[str]:
        if not self._ledger_path.exists():
            return set()
        keys: set[str] = set()
        for line in self._ledger_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            k = rec.get("key")
            if k:
                keys.add(k)
        return keys

    def _append(self, record: dict[str, Any]) -> None:
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._ledger_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")

    # -- core -------------------------------------------------------------
    async def execute_signal(self, signal: dict[str, Any], candidate_id: str) -> dict[str, Any]:
        """Attempt to submit a paper order for ``signal`` attributed to ``candidate_id``.

        Returns a result dict. ``executed`` is True iff the order reached
        ``submit_paper_order`` (regardless of the safety verdict); a gated skip
        returns ``executed: False`` with a ``gate`` reason. The SafetyLayer verdict
        (``approved``/``reason``/``order_id``/``routed_to_ib``) is passed through.
        """
        symbol = str(signal.get("symbol", "")).upper()
        signal_date = str(signal.get("signal_date", ""))

        # -- Gate 1: master switch (default OFF) --------------------------
        if not self._auto:
            return {
                "executed": False,
                "gate": "auto_execute_disabled",
                "reason": "SYSTEMATIC_AUTO_EXECUTE is off (default-off safety gate)",
            }

        # -- Gate 2: candidate must be the deployed_live one for the symbol
        deployed_id = live_candidate_for_symbol(symbol, self._registry)
        if deployed_id != candidate_id:
            return {
                "executed": False,
                "gate": "candidate_not_deployed",
                "reason": (
                    f"candidate '{candidate_id}' is not the deployed_live candidate "
                    f"for {symbol} (deployed={deployed_id})"
                ),
            }

        # -- Gate 2.5: safety re-check (mirror queue _safety_guard_for_approve)
        #    Refuse in live mode: this autonomous PAPER path must never route a
        #    live order even when the system is in live mode. Then the kill switch.
        if self._live_trading_check():
            return {
                "executed": False,
                "gate": "live_mode_refused",
                "reason": "LIVE_TRADING_ENABLED=True - systematic paper bridge refuses live mode",
            }
        if self._is_killed():
            return {
                "executed": False,
                "gate": "kill_switch",
                "reason": "kill switch active - bridge refuses to submit",
            }

        # -- Gate 3: bridge's own idempotency (guards this path's re-runs) -
        key = self._signal_key(candidate_id, symbol, signal_date)
        if key in self._seen_keys():
            return {
                "executed": False,
                "gate": "duplicate",
                "key": key,
                "reason": "signal already attempted (idempotent skip)",
            }

        side = str(signal.get("side", "")).lower()
        action = "BUY" if side in ("long", "buy") else "SELL"
        quantity = int(signal.get("quantity", 1) or 1)
        price = float(signal.get("entry_price", 0.0) or 0.0)
        stop = signal.get("stop")
        stop_price = float(stop) if stop is not None else None

        # -- Gate 3.5: shared cross-path dedup (auto-approve queue + bridge)
        #    First-wins on (symbol, action, trading_date): if the other path
        #    already submitted this opportunity today, skip to avoid 2x exposure.
        dkey = self._dedup.make_key(symbol, action, signal_date)
        if self._dedup.already_submitted(dkey):
            return {
                "executed": False,
                "gate": "cross_path_duplicate",
                "key": dkey,
                "reason": "another path already submitted this (symbol, action, date)",
            }

        # -- Submit through the SafetyLayer (paper only) ------------------
        result = await self._safety.submit_paper_order(
            symbol=symbol,
            action=action,
            quantity=quantity,
            price=price,
            order_type="MKT",
            stop_price=stop_price,
        )

        record = {
            "key": key,
            "candidate_id": candidate_id,
            "symbol": symbol,
            "action": action,
            "quantity": quantity,
            "price": price,
            "stop_price": stop_price,
            "signal_date": signal_date,
            "approved": bool(result.get("approved")),
            "order_id": result.get("order_id"),
            "routed_to_ib": bool(result.get("routed_to_ib")),
            "reason": result.get("reason"),
        }
        self._append(record)

        # Claim the shared cross-path slot only when the order actually reached
        # the broker. A rejected or unrouted submit (approved=True but
        # routed_to_ib=False, e.g. the broker call raised) placed nothing, so it
        # must not block the other path for the rest of the day (2026-10-26).
        if bool(result.get("approved")) and bool(result.get("routed_to_ib")):
            self._dedup.record(
                dkey,
                source="bridge",
                native_id=candidate_id,
                extra={"order_id": result.get("order_id")},
            )

        return {
            "executed": True,
            "key": key,
            "approved": bool(result.get("approved")),
            "reason": result.get("reason"),
            "order_id": result.get("order_id"),
            "routed_to_ib": bool(result.get("routed_to_ib")),
        }
