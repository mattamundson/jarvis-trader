"""Tests for the Corey self-report vs mechanical divergence grader (Phase F).

The headline feature is the OVERSTATEMENT rate: where Corey's recap CLAIMS his
call worked but the mechanical grade (off real bars, supplied by the caller) says
it did not. These tests pin the claim classifier (including the "exactly" false
positive the bootstrap hit, and negation), the evidence-gated truth table, and
the aggregate's always-carries-n discipline.
"""

from __future__ import annotations

from analysis.corey_verdict_grader import (
    AGREE,
    FLAT,
    HIT,
    MISS,
    MIXED,
    NOEVIDENCE,
    NONE,
    OVERSTATE,
    UNDERSTATE,
    classify_self_verdict,
    grade_divergence,
    mechanical_from_correct,
    render_verdict_divergence,
    summarize,
)

# --- classifier: real claims ---------------------------------------------------


def test_classify_hit_claims():
    assert classify_self_verdict("7460 held perfectly and we bounced right off it.") == HIT
    assert classify_self_verdict("Respected the level all day, textbook.") == HIT
    assert classify_self_verdict("Played out exactly as called into the close.") == HIT


def test_classify_miss_claims():
    assert classify_self_verdict("We got stopped out below 7425.") == MISS
    assert classify_self_verdict("Level was invalidated, no follow-through.") == MISS
    assert classify_self_verdict("Wrong call today, it blew right through.") == MISS


def test_classify_exactly_is_not_a_hit():
    # Bootstrap false positive: "exactly" alone must NOT read as a success claim.
    assert (
        classify_self_verdict("Confidence is exactly what gets tested on days like this.")
        == NONE
    )


def test_classify_negation_cancels_hit():
    # "didn't hold" must not count as the "held" hit phrase.
    assert classify_self_verdict("The level did not hold and we faded the call.") == MISS
    assert classify_self_verdict("It never respected the level.") == MISS


def test_classify_bare_stopped_is_not_a_miss():
    # "stopped" without stop-out context is market-structure language, not a
    # failed-call admission -- must not flip a hit/neutral recap to MISS/MIXED.
    assert classify_self_verdict("Price stopped at support and reversed higher.") == NONE
    assert classify_self_verdict("7460 stopped the selloff cold.") == NONE
    # ...but genuine stop-out language still reads as a miss.
    assert classify_self_verdict("Stopped out at the open.") == MISS
    assert classify_self_verdict("We got stopped for a small loss.") == MISS


def test_classify_planned_breakout_is_a_hit_not_mixed():
    # "broke through ... as called" is a planned breakout, not a failed level;
    # it must not become MIXED (which grade_divergence drops as NOEVIDENCE).
    assert (
        classify_self_verdict("We broke through resistance as called and ran to target.")
        == HIT
    )
    # A pronoun'd qualifier through a parenthetical still resolves to HIT.
    assert classify_self_verdict("It broke through, as I planned, right to target.") == HIT
    # The qualifier may LEAD the break phrase, not just follow it.
    assert (
        classify_self_verdict("As called, we broke through resistance and ran to target.")
        == HIT
    )
    # ...or trail it at a distance (word order / proximity must not matter).
    assert (
        classify_self_verdict("We broke through the key resistance and ran to target as called.")
        == HIT
    )
    # A bare / unqualified break still reads as a miss.
    assert classify_self_verdict("7500 broke through to the downside, no bid.") == MISS
    assert classify_self_verdict("Support broke through and we got stopped out.") == MISS


def test_classify_intent_is_scoped_to_the_break_clause():
    # A leading "as called" for the HELD level must not launder a separate failed
    # break across a contrastive marker -- this stays MIXED, not HIT.
    assert (
        classify_self_verdict(
            "As called, support held perfectly but resistance broke through."
        )
        == MIXED
    )


def test_classify_intent_does_not_cross_a_sentence_boundary():
    # A success claim in a separate sentence must not launder a failed break.
    assert (
        classify_self_verdict("Support broke through. As called, resistance held perfectly.")
        == MIXED
    )


def test_classify_intent_does_not_cross_a_sequence_marker():
    # "then" starts a new clause -- a later success claim must not launder the break.
    assert (
        classify_self_verdict(
            "Support broke through, then as called resistance held perfectly."
        )
        == MIXED
    )


def test_classify_negation_does_not_cross_a_conjunction():
    # "never" negates "invalidated" (adjacent), not the later coordinated hit.
    assert (
        classify_self_verdict("The plan never invalidated and held perfectly.") == HIT
    )


def test_classify_not_only_is_an_intensifier_not_a_negator():
    assert classify_self_verdict("Not only held perfectly, it ran to target.") == HIT
    assert classify_self_verdict("It not only respected the level, it reversed hard.") == HIT


def test_classify_textbook_failure_is_not_a_hit():
    # "textbook" modifying a failure must not fire the HIT pattern.
    assert classify_self_verdict("Textbook failure at resistance.") != HIT
    assert classify_self_verdict("Textbook failed breakout, no follow-through.") == MISS
    # ...but a bare "textbook" success read still hits.
    assert classify_self_verdict("Textbook hold at 7500, bounced right off.") == HIT


def test_classify_negated_break_is_not_a_miss():
    # "never broke through" = a hold, not a failed level -- must not read as MISS.
    assert classify_self_verdict("Support never broke through the level.") != MISS
    assert classify_self_verdict("Support never broke through the level.") == NONE


def test_classify_planned_breakout_as_expected_is_a_hit():
    # "as expected" qualifies the break as planned -> HIT, not a dropped NONE.
    assert (
        classify_self_verdict("We broke through resistance as expected and ran to target.")
        == HIT
    )
    # ...but a bare "as expected" with no breakout claim is not a hit on its own.
    assert classify_self_verdict("Choppy range as expected, stood aside.") == NONE


def test_classify_normalizes_smart_apostrophes():
    # Curly U+2019 from Discord/mobile paste must still read "didn't" as a miss.
    assert classify_self_verdict("The level didn’t hold and we faded the call.") == MISS
    assert classify_self_verdict("It never respected the level, wasn’t even close.") == MISS


def test_classify_mixed_and_none():
    assert (
        classify_self_verdict("Support held perfectly but resistance broke through.")
        == MIXED
    )
    assert classify_self_verdict("Choppy overnight session, watching the open.") == NONE
    assert classify_self_verdict("") == NONE


# --- mechanical bridge ---------------------------------------------------------


def test_mechanical_from_correct_mapping():
    assert mechanical_from_correct(1.0) == HIT
    assert mechanical_from_correct(0.0) == MISS
    assert mechanical_from_correct(0.5) == FLAT
    assert mechanical_from_correct(None) == NONE


# --- divergence truth table ----------------------------------------------------


def test_overstate_claim_win_tape_miss():
    out = grade_divergence(HIT, MISS)
    assert out["gradeable"] is True
    assert out["flag"] == OVERSTATE


def test_overstate_claim_win_tape_flat():
    # Claimed a win, tape went nowhere -> still an overstatement.
    assert grade_divergence(HIT, FLAT)["flag"] == OVERSTATE


def test_agree_claim_win_tape_hit():
    assert grade_divergence(HIT, HIT)["flag"] == AGREE


def test_understate_claim_miss_tape_hit():
    assert grade_divergence(MISS, HIT)["flag"] == UNDERSTATE


def test_agree_claim_miss_tape_miss_or_flat():
    assert grade_divergence(MISS, MISS)["flag"] == AGREE
    assert grade_divergence(MISS, FLAT)["flag"] == AGREE


def test_noevidence_gates():
    # No definite claim -> not gradeable.
    assert grade_divergence(NONE, HIT)["gradeable"] is False
    assert grade_divergence(MIXED, MISS)["gradeable"] is False
    # No mechanical grade -> not gradeable.
    out = grade_divergence(HIT, NONE)
    assert out["gradeable"] is False
    assert out["flag"] == NOEVIDENCE


# --- aggregate discipline ------------------------------------------------------


def test_summarize_always_carries_n_and_note():
    records = [
        grade_divergence(HIT, MISS),  # overstate
        grade_divergence(HIT, FLAT),  # overstate
        grade_divergence(HIT, HIT),  # agree
        grade_divergence(MISS, HIT),  # understate
        grade_divergence(NONE, HIT),  # not gradeable
    ]
    s = summarize(records)
    assert s["n_total"] == 5
    assert s["n_gradeable"] == 4
    assert s["n_overstate"] == 2
    assert s["n_understate"] == 1
    assert s["n_agree"] == 1
    assert s["overstatement_rate"] == 0.5  # 2 / 4
    assert "PROVISIONAL" in s["note"]
    assert "n_gradeable" in s["note"]


def test_summarize_empty_returns_none_rate_not_bare_number():
    s = summarize([])
    assert s["n_gradeable"] == 0
    assert s["overstatement_rate"] is None
    assert "PROVISIONAL" in s["note"]


# --- render --------------------------------------------------------------------


def test_render_empty_when_nothing_gradeable():
    assert render_verdict_divergence(summarize([])) == []
    assert render_verdict_divergence(None) == []


def test_render_section_when_gradeable():
    s = summarize([grade_divergence(HIT, MISS), grade_divergence(HIT, HIT)])
    md = "\n".join(render_verdict_divergence(s))
    assert "## Corey Self-Report Divergence" in md
    assert "Overstatement" in md
    assert "n_gradeable=2" in md
