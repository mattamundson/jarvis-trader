"""
Unit tests for the automated pre-close framing brief (framing_context's new
intraday/preclose-commentary gathering + framing_synthesis's session
parameterization) plus an explicit guard that the existing premarket path is
unaffected. All pure/fixture-based — no network, no LLM call, real DB only
via a throwaway temp SQLite file. Mirrors test_morning_framing_brief.py's style.
"""

import asyncio
import sqlite3
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from analysis import framing_context
from analysis.framing_synthesis import (
    _PRECLOSE_SKILL_MD_PATH,
    _SKILL_MD_PATH,
    build_system_prompt,
    parse_brief,
)

_CT = ZoneInfo("America/Chicago")


# ---------------------------------------------------------------------------
# framing_synthesis.build_system_prompt(session="preclose") — guard test for
# market-close-brief/SKILL.md parsing, mirrors the AM file's guard test.
# ---------------------------------------------------------------------------


class TestBuildSystemPromptPreclose:
    def test_real_skill_md_parses_without_error(self):
        prompt = build_system_prompt(_PRECLOSE_SKILL_MD_PATH, session="preclose")
        assert "Output template" in prompt or "confidence" in prompt.lower()
        assert "Bias rules" in prompt
        assert "Hard rules" in prompt

    def test_real_skill_md_contains_required_output_headers(self):
        prompt = build_system_prompt(_PRECLOSE_SKILL_MD_PATH, session="preclose")
        for required in ("Level confidence:", "Acceptance vs Rejection", "Game Theory Cues", "Key Levels"):
            assert required in prompt, f"missing {required!r} in extracted market-close-brief SKILL.md"

    def test_session_preclose_resolves_default_path_without_explicit_arg(self):
        """No skill_md_path given -> resolved from _SESSION_SKILL_PATHS[session]."""
        prompt = build_system_prompt(session="preclose")
        assert "Game Theory Cues" in prompt


# ---------------------------------------------------------------------------
# framing_synthesis.parse_brief(session="preclose")
# ---------------------------------------------------------------------------

_VALID_PRECLOSE_BRIEF = """\
Pre-Close Update — Wed, 2026-07-08 (~1hr to CME RTH close)
Level confidence: HIGH (engine/DB intraday)
Session range so far: $ES ~6580-6610 | $NQ ~24040-24120

Balance / Value Area
Value area forming near the highs.

Acceptance vs Rejection at the Close
Intraday movement = noise, closing price = information.

Game Theory Cues
Buyers' Playbook: hold above 6611.
Sellers' Playbook: reject at 6611.

Key Levels
$ES resistance/support here.

Caveats: pre-close read, not a forecast.
"""


class TestParseBriefPreclose:
    def test_valid_preclose_brief_passes(self):
        assert parse_brief(_VALID_PRECLOSE_BRIEF, session="preclose") == _VALID_PRECLOSE_BRIEF.strip()

    def test_missing_required_header_raises(self):
        broken = _VALID_PRECLOSE_BRIEF.replace("Game Theory Cues", "Something Else")
        with pytest.raises(ValueError, match="missing required section"):
            parse_brief(broken, session="preclose")

    def test_am_brief_shape_fails_preclose_validation(self):
        """An AM-shaped brief (has Structural Levels/Scenario Map, not
        Acceptance vs Rejection/Game Theory Cues/Key Levels) must not
        pass as a valid preclose brief — the two header sets are distinct."""
        am_shaped = (
            "Level confidence: HIGH\nStructural Levels\n...\nScenario Map\n...\nCaveats: x\n"
        )
        with pytest.raises(ValueError, match="missing required section"):
            parse_brief(am_shaped, session="preclose")


# ---------------------------------------------------------------------------
# framing_synthesis — explicit AM-regression guard: no `session` kwarg must
# resolve to the exact premarket behavior that existed before this feature.
# ---------------------------------------------------------------------------


class TestPremarketDefaultUnaffected:
    def test_build_system_prompt_default_resolves_am_skill(self):
        prompt = build_system_prompt(_SKILL_MD_PATH)
        assert "Structural Levels" in prompt
        assert "Scenario Map" in prompt

    def test_parse_brief_default_still_validates_am_headers(self):
        am_brief = (
            "Level confidence: HIGH\nStructural Levels\n...\nScenario Map\n...\nCaveats: x\n"
        )
        assert parse_brief(am_brief) == am_brief.strip()


# ---------------------------------------------------------------------------
# framing_context.get_intraday_snapshot — the one genuinely new capability
# (get_engine_levels()/compute_key_levels() deliberately excludes today).
# ---------------------------------------------------------------------------


class TestGetIntradaySnapshot:
    def _today_bars_df(self) -> pd.DataFrame:
        today_ct_morning = datetime.now(_CT).replace(hour=9, minute=0, second=0, microsecond=0)
        timestamps = [
            (today_ct_morning + pd.Timedelta(hours=i)).astimezone(timezone.utc) for i in range(4)
        ]
        return pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": [100.0, 101.0, 99.0, 102.0],
                "high": [101.5, 102.0, 100.5, 103.0],
                "low": [99.5, 100.5, 98.5, 101.5],
                "close": [101.0, 99.5, 102.0, 102.5],
                "volume": [10, 12, 8, 15],
            }
        )

    def test_extracts_session_range_and_prefers_live_price(self, monkeypatch):
        df = self._today_bars_df()
        monkeypatch.setattr(
            "analytics.regime.load_recent_bars", lambda symbol, n_bars, db_path=None: df.copy()
        )
        monkeypatch.setattr(
            "analysis.morning_levels._value_area", lambda intraday_df: (103.2, 99.8, 101.5, "inside_va")
        )
        monkeypatch.setattr(
            framing_context,
            "_fetch_price_snapshot",
            lambda symbols, timeout=5: {"MES": {"last_price": 102.75}},
        )

        out = framing_context.get_intraday_snapshot(symbols=("MES",))
        snap = out["MES"]
        assert snap is not None
        assert snap["session_open"] == 100.0
        assert snap["session_high"] == 103.0
        assert snap["session_low"] == 98.5
        assert snap["last_price"] == 102.75  # live snapshot preferred over last bar close
        assert snap["vah"] == 103.2 and snap["val"] == 99.8 and snap["poc"] == 101.5

    def test_falls_back_to_last_bar_close_when_snapshot_unreachable(self, monkeypatch):
        df = self._today_bars_df()
        monkeypatch.setattr(
            "analytics.regime.load_recent_bars", lambda symbol, n_bars, db_path=None: df.copy()
        )
        monkeypatch.setattr(
            "analysis.morning_levels._value_area", lambda intraday_df: (None, None, None, None)
        )
        monkeypatch.setattr(framing_context, "_fetch_price_snapshot", lambda symbols, timeout=5: {})

        out = framing_context.get_intraday_snapshot(symbols=("MES",))
        assert out["MES"]["last_price"] == 102.5  # last bar's close

    def test_none_when_no_bars_for_today(self, monkeypatch):
        monkeypatch.setattr(
            "analytics.regime.load_recent_bars", lambda symbol, n_bars, db_path=None: None
        )
        monkeypatch.setattr(framing_context, "_fetch_price_snapshot", lambda symbols, timeout=5: {})

        out = framing_context.get_intraday_snapshot(symbols=("MES",))
        assert out["MES"] is None


# ---------------------------------------------------------------------------
# framing_context.get_corey_preclose_commentary_for — lightweight raw-text
# query against discord_corey_commentary, no schema change.
# ---------------------------------------------------------------------------


class TestGetCoreyPrecloseCommentaryFor:
    def _make_db(self, tmp_path, rows):
        db_path = tmp_path / "test.db"
        con = sqlite3.connect(str(db_path))
        con.execute(
            "CREATE TABLE discord_corey_commentary "
            "(message_id TEXT UNIQUE, timestamp TEXT, content TEXT, channel TEXT)"
        )
        con.executemany(
            "INSERT INTO discord_corey_commentary "
            "(message_id, timestamp, content, channel) VALUES (?, ?, ?, ?)",
            rows,
        )
        con.commit()
        con.close()
        return db_path

    def test_filters_to_after_cutoff_hour_ct(self, tmp_path):
        # 2026-07-08 in July -> CT is CDT (UTC-5). 13:30 UTC = 8:30am CT
        # (premarket); 19:30 UTC = 2:30pm CT (preclose).
        rows = [
            ("m1", "2026-07-08T13:30:00", "Morning update for subscribers", "market-updates"),
            ("m2", "2026-07-08T19:30:00", "Between roughly 6580-6610 (ES)...", "market-updates"),
        ]
        db_path = self._make_db(tmp_path, rows)
        result = framing_context.get_corey_preclose_commentary_for(
            date(2026, 7, 8), db_path=db_path, cutoff_ct_hour=12
        )
        assert result is not None
        assert result["message_count"] == 1
        assert "Between roughly" in result["raw_text"]
        assert "Morning update" not in result["raw_text"]

    def test_none_when_no_rows_for_date(self, tmp_path):
        db_path = self._make_db(tmp_path, [])
        result = framing_context.get_corey_preclose_commentary_for(date(2026, 7, 8), db_path=db_path)
        assert result is None

    def test_none_when_db_missing(self, tmp_path):
        result = framing_context.get_corey_preclose_commentary_for(
            date(2026, 7, 8), db_path=tmp_path / "does-not-exist.db"
        )
        assert result is None


# ---------------------------------------------------------------------------
# framing_context.assemble_context — explicit AM-regression guard: the exact
# call shape morning_framing_brief.py::_run() uses (no `session` kwarg) must
# never touch either new preclose-only gathering function, and both new
# fields must be None. Executable form of "AM must keep working byte-for-byte."
# ---------------------------------------------------------------------------


class TestAssembleContextPremarketDefault:
    def test_default_session_skips_preclose_gathering_entirely(self, monkeypatch):
        called = {"intraday": False, "preclose_commentary": False}

        async def fake_corey_bias(*_a, **_kw):
            return None

        def fake_engine_levels(*_a, **_kw):
            return {"MES": None, "MNQ": None}

        def fake_system_overlay(*_a, **_kw):
            return {"kill_switch_active": None, "engine_status": "UNKNOWN", "atr": None}

        def fake_intraday_snapshot(*_a, **_kw):
            called["intraday"] = True
            return {}

        def fake_preclose_commentary(*_a, **_kw):
            called["preclose_commentary"] = True
            return None

        monkeypatch.setattr(framing_context, "get_corey_bias_for", fake_corey_bias)
        monkeypatch.setattr(framing_context, "get_engine_levels", fake_engine_levels)
        monkeypatch.setattr(framing_context, "get_system_overlay", fake_system_overlay)
        monkeypatch.setattr(framing_context, "get_intraday_snapshot", fake_intraday_snapshot)
        monkeypatch.setattr(
            framing_context, "get_corey_preclose_commentary_for", fake_preclose_commentary
        )

        context = asyncio.run(framing_context.assemble_context(date(2026, 7, 8)))

        assert called["intraday"] is False
        assert called["preclose_commentary"] is False
        assert context.intraday_snapshot is None
        assert context.corey_preclose_raw is None
        as_dict = context.to_dict()
        assert as_dict["intraday_snapshot"] is None
        assert as_dict["corey_preclose_raw"] is None

    def test_preclose_session_does_invoke_both_gathering_functions(self, monkeypatch):
        called = {"intraday": False, "preclose_commentary": False}

        async def fake_corey_bias(*_a, **_kw):
            return None

        def fake_engine_levels(*_a, **_kw):
            return {"MES": None, "MNQ": None}

        def fake_system_overlay(*_a, **_kw):
            return {"kill_switch_active": None, "engine_status": "UNKNOWN", "atr": None}

        def fake_intraday_snapshot(*_a, **_kw):
            called["intraday"] = True
            return {"MES": {"session_open": 100.0}}

        def fake_preclose_commentary(*_a, **_kw):
            called["preclose_commentary"] = True
            return {"raw_text": "x", "message_count": 1}

        monkeypatch.setattr(framing_context, "get_corey_bias_for", fake_corey_bias)
        monkeypatch.setattr(framing_context, "get_engine_levels", fake_engine_levels)
        monkeypatch.setattr(framing_context, "get_system_overlay", fake_system_overlay)
        monkeypatch.setattr(framing_context, "get_intraday_snapshot", fake_intraday_snapshot)
        monkeypatch.setattr(
            framing_context, "get_corey_preclose_commentary_for", fake_preclose_commentary
        )

        context = asyncio.run(
            framing_context.assemble_context(date(2026, 7, 8), session="preclose")
        )

        assert called["intraday"] is True
        assert called["preclose_commentary"] is True
        assert context.intraday_snapshot == {"MES": {"session_open": 100.0}}
        assert context.corey_preclose_raw == {"raw_text": "x", "message_count": 1}
