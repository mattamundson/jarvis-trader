"""Shared data-provenance stamping helper for ``insert_decision`` callers.

``main.py``'s ``_log_decision`` (PR #286) stamps every persisted decision with
``{last_bar_source, serve_age_s}`` — WHAT DATA the decision was based on — so a
post-hoc audit can tell a live-IBKR decision from one made on a stale
CSV-cache fallback (the 2026-06-29 frozen-MES-5300 class). That stamping only
covered main.py's own decision path. This module extracts the *same* pattern
so the other ``insert_decision`` callers — ``routers/pipeline_router.py``,
``routers/decisions_router.py``, and ``scanner/signal_scanner.py`` — can apply
identical provenance fields without re-deriving the logic three times.

Purely additive: never changes a trade decision, never raises into the
decision path, degrades to ``None``/no-op when the data manager (or its
expected surface) is unavailable.
"""

from __future__ import annotations


def build_data_provenance(dm, symbol: str) -> dict | None:
    """Snapshot *what data* a decision was based on, for honest persistence.

    Mirrors ``main.py``'s ``_build_data_provenance`` (PR #286) exactly:

    - ``last_bar_source`` — the most-recent data tier that served bars
      (``ibkr`` | ``sqlite_cache`` | ``polygon`` | ``csv_cache`` | ``none``).
      This is GLOBAL on the manager, not per-symbol, so it is *approximate*
      when several symbols are served concurrently; named honestly so a
      reader never over-trusts it.
    - ``serve_age_s`` — seconds since bars were last served *for this
      symbol* (per-symbol via ``symbol_freshness()``, accurate). ``None`` if
      this symbol has not been served yet this run.

    Fully defensive: returns ``None`` when the data manager is unavailable
    and never raises into the decision path (a provenance failure must never
    block or corrupt a decision).
    """
    if dm is None:
        return None
    prov: dict = {}
    try:
        prov["last_bar_source"] = getattr(dm, "_last_bar_source", None)
    except Exception:
        prov["last_bar_source"] = None
    try:
        fresh = dm.symbol_freshness()
        prov["serve_age_s"] = fresh.get(symbol.upper()) if isinstance(fresh, dict) else None
    except Exception:
        prov["serve_age_s"] = None
    return prov


def stamp_signal_data(signal_data: dict | None, provenance: dict | None) -> dict | None:
    """Merge ``provenance`` into a *copy* of ``signal_data``.

    Never mutates the caller's dict — matches ``main.py``'s copy-merge
    pattern (``sig = {**sig, "data_provenance": provenance}``). No-ops
    (returns ``signal_data`` unchanged) when there is no provenance to stamp
    or ``signal_data`` isn't a plain dict.
    """
    if provenance is None or not isinstance(signal_data, dict):
        return signal_data
    return {**signal_data, "data_provenance": provenance}
