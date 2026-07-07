"""Regression guard for the candidate-attribution seam that graduates a candidate.

Audit finding (Task #3): the open -> attribution -> graduation chain is sound, but
existing tests hand-build the ``strategy_params`` dict (e.g. ``{"candidate_id": ...}``).
None exercises the PRODUCTION tagger ``forward_test.tag_strategy_params`` — the exact
function ``PortfolioTracker.open_trade(candidate_id=...)`` calls — nor the JSON-string
round-trip the SQLite ``strategy_params`` TEXT column imposes (``get_trade_by_id`` /
``get_closed_trades`` return it raw).

So a refactor of the tagger's output shape, or a JSON (de)serialization change, could
silently drop attribution to the ``symbol`` fallback — which NEVER graduates a
candidate — while every existing test stayed green. These tests close that gap:
the real tagger output, both as a dict and as a persisted JSON string, must resolve
to the precise ``candidate_id`` level.
"""

from __future__ import annotations

import json

from backtest.forward_test import attribution_level, tag_strategy_params

MES_ID = "MES_sma_trend_vix_pctile_blockCrisis_v1"
MGC_ID = "MGC_trend_rv_filter_rank1"


def _closed_row(symbol: str, strategy_params) -> dict:
    """The closed-trade row shape the forward-test loop consumes."""
    return {
        "symbol": symbol,
        "pnl": 12.5,
        "exit_time": "2026-06-12T20:00:00+00:00",
        "strategy_params": strategy_params,
    }


def test_real_tagger_dict_resolves_to_candidate_id_level():
    """The production tagger's dict output attributes at the graduating level."""
    sp = tag_strategy_params({"analyst_signals": {"technical": 0.4}}, MES_ID)
    # The tagger preserves pre-existing keys (calibration still works) ...
    assert sp["analyst_signals"] == {"technical": 0.4}
    # ... and stamps the id where attribution_level looks for it.
    cand = {"id": MES_ID, "symbol": "MES", "params": {}}
    assert attribution_level(_closed_row("MES", sp), cand) == "candidate_id"


def test_real_tagger_survives_json_text_roundtrip():
    """SQLite stores strategy_params as JSON TEXT; the round-trip must not break attribution."""
    sp = tag_strategy_params({}, MES_ID)
    persisted = json.dumps(sp)  # what the DB column holds
    cand = {"id": MES_ID, "symbol": "MES", "params": {}}
    # attribution_level parses the raw JSON string exactly as get_closed_trades returns it.
    assert attribution_level(_closed_row("MES", persisted), cand) == "candidate_id"


def test_mgc_candidate_roundtrip():
    sp = tag_strategy_params({}, MGC_ID)
    cand = {"id": MGC_ID, "symbol": "MGC", "params": {}}
    assert attribution_level(_closed_row("MGC", json.dumps(sp)), cand) == "candidate_id"


def test_wrong_candidate_does_not_attribute_at_candidate_level():
    """A trade tagged for a different candidate must NOT graduate this one."""
    sp = tag_strategy_params({}, "some_other_candidate")
    cand = {"id": MES_ID, "symbol": "MES", "params": {}}
    # Not the candidate_id level (falls back to a non-graduating level or None).
    assert attribution_level(_closed_row("MES", sp), cand) != "candidate_id"
