"""Tests for the post-close Corey recap scorecard (Phase F retrospective glue).

Covers the pure grading assembly (classify recap -> grade vs supplied mechanical
verdict -> summarize/render) and the dormant-safe recap fetch, including a real
temp SQLite DB so the query is verified, not just its dormant path.
"""

from __future__ import annotations

import sqlite3

from analysis.corey_recap_scorecard import (
    build_scorecard,
    fetch_recap_texts,
    grade_day,
    render_scorecard,
)
from analysis.corey_verdict_grader import AGREE, HIT, MISS, NOEVIDENCE, OVERSTATE

# --- grade_day ----------------------------------------------------------------


def test_grade_day_overstate_and_quote():
    rec = grade_day("7460 held perfectly, textbook.", MISS, for_date="2026-07-09")
    assert rec["self_verdict"] == HIT
    assert rec["mechanical_verdict"] == MISS
    assert rec["flag"] == OVERSTATE
    assert rec["gradeable"] is True
    assert rec["date"] == "2026-07-09"
    assert "held perfectly" in rec["quote"]


def test_grade_day_agree_and_noevidence():
    assert grade_day("We got stopped out below 7425.", MISS)["flag"] == AGREE
    # A recap with no definite self-claim is not gradeable.
    out = grade_day("Choppy session, watching the open.", HIT)
    assert out["gradeable"] is False
    assert out["flag"] == NOEVIDENCE


def test_grade_day_snippet_truncates():
    rec = grade_day("held perfectly " + "x" * 500, HIT)
    assert len(rec["quote"]) <= 140
    assert rec["quote"].endswith("…")


# --- fetch_recap_texts: dormant-safe ------------------------------------------


def test_fetch_recap_texts_dormant_paths():
    assert fetch_recap_texts("2026-07-09", db_path=None) == []
    assert fetch_recap_texts("2026-07-09", db_path="/no/such/file.db") == []


# --- fetch_recap_texts: real DB (verifies the query + channel/author filter) ---


def _seed_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE discord_corey_commentary (
            content TEXT, timestamp TEXT, channel TEXT, author_id TEXT
        )
        """
    )
    rows = [
        ("morning: bullish above 7500", "2026-07-09T08:30:00", "market-updates", "corey"),
        ("power hour: held perfectly", "2026-07-09T15:00:00", "market-updates", "corey"),
        ("tathedog aside", "2026-07-09T12:00:00", "general", "564449478174703646"),
        ("random chatter", "2026-07-09T12:05:00", "general", "someone-else"),  # filtered out
        ("prior day post", "2026-07-08T15:00:00", "market-updates", "corey"),  # wrong date
    ]
    conn.executemany(
        "INSERT INTO discord_corey_commentary VALUES (?,?,?,?)", rows
    )
    conn.commit()
    conn.close()


def test_fetch_recap_texts_reads_and_filters(tmp_path):
    db = tmp_path / "commentary.db"
    _seed_db(str(db))
    texts = fetch_recap_texts("2026-07-09", db_path=str(db))
    # market-updates + tathedog's #general row for the date, in timestamp order;
    # other-author #general and the prior-day row excluded.
    assert texts == [
        "morning: bullish above 7500",
        "tathedog aside",
        "power hour: held perfectly",
    ]


# --- scorecard aggregation / render -------------------------------------------


def test_build_and_render_scorecard():
    days = [
        grade_day("held perfectly, textbook", MISS, for_date="2026-07-06"),  # overstate
        grade_day("held perfectly", HIT, for_date="2026-07-07"),  # agree
        grade_day("got stopped out", HIT, for_date="2026-07-08"),  # understate
        grade_day("quiet chop", HIT, for_date="2026-07-09"),  # not gradeable
    ]
    s = build_scorecard(days)
    assert s["n_total"] == 4
    assert s["n_gradeable"] == 3
    assert s["n_overstate"] == 1
    assert s["overstatement_rate"] == round(1 / 3, 4)
    assert "PROVISIONAL" in s["note"]

    md = "\n".join(render_scorecard(days))
    assert "## Corey Self-Report Divergence" in md
    assert "n_gradeable=3" in md


def test_render_scorecard_empty_when_nothing_gradeable():
    assert render_scorecard([grade_day("quiet chop", HIT)]) == []
    assert render_scorecard([]) == []
