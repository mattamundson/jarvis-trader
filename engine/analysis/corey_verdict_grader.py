"""
Corey self-report vs mechanical divergence grader (Phase F extension).

The scorekeeper's edge: neither Saty nor Corey grades ITSELF. ``corey_compare.py``
already grades Corey's morning BIAS against the realized session. This module
grades a different, harder thing -- Corey's own AFTER-THE-FACT VERDICT (his
power-hour / next-morning recap language: "held perfectly", "respected the
level", "got stopped") against the mechanical outcome. The gap between what he
CLAIMS and what the tape actually did is his OVERSTATEMENT RATE -- the one metric
that is genuinely ours and that neither source produces about itself.

Design (honest by construction):

- The self-verdict classifier reads CLAIM STRUCTURES, not bare keywords. The
  bootstrap's naive matcher flagged "claims_success" off the word "exactly" in
  "confidence is exactly what gets tested" -- the opposite of a success claim. We
  anchor on hit/miss PHRASES, honor negation, and abstain ("none") rather than
  guess.

- The mechanical verdict is SUPPLIED by the caller (``corey_compare``'s outcome
  grade off real bars / settle), NEVER invented here. This module does not
  fabricate intraday truth -- it only compares a claim to a grade it is handed.
  ``mechanical_from_correct`` bridges the existing ``corey_correct`` 1.0/0.5/0.0
  score without recomputing anything.

- Aggregates ALWAYS carry n. No function returns a bare rate; small, self-selected
  samples are the norm for this source (~8 gradeable days at bootstrap), so every
  summary reports n and labels itself provisional.

Known limitations: this is a regex heuristic over free text, not a parser. It
handles the common Corey recap structures (and a matrix of word orders, negation,
clause boundaries, and Discord smart-quote paste), but exotic multi-clause
phrasings can still be misread. By design the residual failure mode is ABSTENTION
(MIXED/NONE -> NOEVIDENCE, a day dropped from the denominator), which is why every
summary is labelled PROVISIONAL and carries n -- an inverted grade would be the
bug worth fixing, a dropped ambiguous day is expected. The vocabulary
(_HIT_PATTERNS / _MISS_PATTERNS) is intentionally not exhaustive.

Display / journal only -- imported by nothing in ``risk/`` or execution. Pure, no
I/O, no LLM.
"""

from __future__ import annotations

import re
from typing import Any, Optional

# --- Verdict vocabulary --------------------------------------------------------

HIT = "hit"
MISS = "miss"
FLAT = "flat"
MIXED = "mixed"
NONE = "none"

# --- Divergence flags ----------------------------------------------------------

OVERSTATE = "OVERSTATE"  # he claimed a win; the tape says miss/flat
UNDERSTATE = "UNDERSTATE"  # he claimed a miss; the tape says hit
AGREE = "AGREE"  # claim matches the tape
NOEVIDENCE = "NOEVIDENCE"  # not gradeable (no claim, or no mechanical grade)

# Claim structures that assert his morning call WORKED. Each anchors a "worked"
# verb to a level/plan noun, or is an idiom that only reads as a win -- never a
# bare adverb like "exactly", which the bootstrap false-flagged.
_HIT_PATTERNS = [
    r"\bheld (?:perfectly|nicely|beautifully|as called|the level|that level|support|resistance)\b",
    r"\brespected (?:the|that|our|this) (?:level|zone|line|number|area)\b",
    r"\bplayed out (?:exactly )?(?:as|like) (?:called|expected|planned|drawn)\b",
    r"\b(?:worked|resolved) (?:perfectly|cleanly|well|as called|to the (?:tick|level))\b",
    r"\bnailed (?:the|that|it)\b",
    r"\bbounced (?:right |perfectly |cleanly )?off (?:the|that|our)\b",
    r"\brejected (?:right |perfectly |cleanly )?(?:at|from) (?:the|that|our)\b",
    r"\btextbook\b(?!\s+(?:failure|failed|fail|trap|fake|reversal))",
    r"\bright on (?:script|plan|the money)\b",
    r"\bas (?:i |we |you )?(?:called|drawn|mapped|planned)\b",
    r"\bdid (?:its|their) job\b",
    r"\bcall (?:was )?(?:spot[- ]on|dead[- ]on|correct)\b",
]

# Claim structures that admit the call DID NOT work.
_MISS_PATTERNS = [
    # "stopped" is a miss ONLY with stop-out context. A bare "stopped" is
    # market-structure language ("price stopped at support", "7460 stopped the
    # selloff"), not an admission the call failed -- matching it flips clear
    # hit/neutral recaps to MISS/MIXED and silently corrupts the overstatement score.
    r"\bstopped out\b",
    r"\b(?:got|we got|we were) stopped\b",
    r"\binvalidated\b",
    r"\b(?:did ?n['o]?t|failed to|never) (?:hold|respect|work)\b",
    r"\bno follow[- ]through\b",
    r"\bchopped (?:us |me )?up\b",
    r"\bwrong (?:call|side|way|read)\b",
    r"\bfaded (?:the|our|my) (?:call|bias|read|plan)\b",
    r"\bcall (?:was )?(?:off|wrong|a (?:miss|bust))\b",
    r"\bgave (?:it )?back\b",
]

# Break language is DIRECTIONAL, unlike a stop-out: "broke through resistance as
# called" is a planned breakout (a HIT), not a failed level. So a break phrase is
# miss evidence ONLY when it is NOT immediately followed by a success qualifier;
# otherwise it would flip a clean HIT recap to MIXED, which grade_divergence()
# treats as NOEVIDENCE and silently drops from the overstatement denominator.
_BREAK_MISS_PATTERNS = [
    r"\bblew (?:right )?(?:through|past)\b",
    r"\bbroke (?:right )?(?:through|down through|up through)\b",
]

# A stated intent qualifier ("as called" / "as we planned") marks a breakout as
# PLANNED. It is scoped to the break's own clause via contrastive markers so that
# "As called, support held perfectly but resistance broke through" stays MIXED --
# the "but" separates the intended hold from the failed break.
_INTENT_QUALIFIER = re.compile(r"\bas (?:i |we |you )?(?:called|planned|drawn|mapped|expected)\b")
# A clause boundary ends the break's own clause: a sentence terminator OR a
# contrastive marker. Both must stop the intent scan so a success claim in a
# neighbouring sentence/clause ("Support broke through. As called, resistance
# held perfectly") cannot launder a failed break.
_CLAUSE_BOUNDARY = re.compile(
    r"[.;!?]|\b(?:but|however|though|although|yet|whereas|while|then)\b"
)

# Negators that, when they immediately precede a HIT phrase, cancel it. Guards the
# "held perfectly" -> "didn't hold perfectly" inversion. The 0-2 intervening words
# may NOT include a coordinating conjunction, so a negator does not reach across a
# new clause -- "never invalidated AND held perfectly" leaves "held" un-negated.
# "not only"/"not just" are emphatic intensifiers, NOT negators ("not only held
# perfectly" is a HIT), so a negator immediately followed by only/just is excluded.
_NEG_WINDOW = re.compile(
    r"\b(?:did ?n['o]?t|does ?n['o]?t|was ?n['o]?t|never|failed to|no|not)"
    r"(?!\s+(?:only|just))"
    r"\s+(?:(?!and\b|but\b|or\b|then\b)\w+\s+){0,2}$"
)


_SMART_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})


def _norm(text: str) -> str:
    # Normalize typographic apostrophes/quotes (Discord/mobile paste) so patterns
    # that use a straight ' still match "didn't", "we're", "wasn't".
    t = (text or "").translate(_SMART_QUOTES)
    return re.sub(r"\s+", " ", t.lower()).strip()


def _scan(patterns: list[str], text: str) -> tuple[bool, bool]:
    """Return (has_unnegated, has_negated) for the pattern set over ``text``."""
    unneg = neg = False
    for pat in patterns:
        for m in re.finditer(pat, text):
            if _NEG_WINDOW.search(text[: m.start()]):
                neg = True
            else:
                unneg = True
    return unneg, neg


def _break_is_miss(text: str) -> bool:
    """True if a break phrase reads as a FAILED level (not a planned breakout).

    A break is failure evidence unless the move was stated as intended -- an "as
    called/planned" qualifier in the break's OWN clause, on either side and at any
    distance, but not across a clause boundary (sentence terminator or contrastive
    marker). So "broke through resistance as called" and "as called, we broke
    through" are HITs, while "... support held perfectly BUT resistance broke
    through" and "Support broke through. As called, resistance held" keep the
    break as miss evidence. A bare break ("7500 broke through") is a miss.
    """
    for pat in _BREAK_MISS_PATTERNS:
        for m in re.finditer(pat, text):
            # Clause preceding the break: text after the nearest clause boundary.
            before = text[: m.start()]
            cuts = list(_CLAUSE_BOUNDARY.finditer(before))
            before_clause = before[cuts[-1].end() :] if cuts else before
            # Clause following the break: text up to the next clause boundary.
            after = text[m.end() :]
            nxt = _CLAUSE_BOUNDARY.search(after)
            after_clause = after[: nxt.start()] if nxt else after
            planned = _INTENT_QUALIFIER.search(before_clause) or _INTENT_QUALIFIER.search(
                after_clause
            )
            if not planned:
                return True
    return False


def classify_self_verdict(recap: str) -> str:
    """Classify Corey's OWN claimed verdict from recap language.

    Returns one of HIT / MISS / MIXED / NONE. Reads claim structures, honors
    negation, and abstains (NONE) rather than guessing. Pure.

    A NEGATED positive claim is itself a miss admission -- "never respected the
    level" / "didn't hold" mean the call failed, so a negated hit phrase counts as
    miss evidence rather than being silently dropped.
    """
    text = _norm(recap)
    if not text:
        return NONE
    hit, hit_negated = _scan(_HIT_PATTERNS, text)
    miss_direct, _ = _scan(_MISS_PATTERNS, text)
    miss = miss_direct or hit_negated or _break_is_miss(text)
    if hit and miss:
        return MIXED
    if hit:
        return HIT
    if miss:
        return MISS
    return NONE


def mechanical_from_correct(corey_correct: Optional[float]) -> str:
    """Map ``corey_compare``'s outcome score (1.0/0.5/0.0/None) to a verdict.

    1.0 -> HIT, 0.0 -> MISS, 0.5 -> FLAT, None -> NONE. Bridges the existing
    outcome grade so this module never recomputes direction off a proxy.
    """
    if corey_correct is None:
        return NONE
    if corey_correct >= 1.0:
        return HIT
    if corey_correct <= 0.0:
        return MISS
    return FLAT


def grade_divergence(self_verdict: str, mechanical_verdict: str) -> dict[str, Any]:
    """Compare a self-claim to the mechanical grade. Evidence-gated. Pure.

    Gradeable only when the self-verdict is a definite HIT or MISS AND the
    mechanical verdict is present (HIT/MISS/FLAT). MIXED and NONE claims, or a
    missing mechanical grade, yield NOEVIDENCE (gradeable=False) -- we do not
    invent a verdict to force a flag.
    """
    out: dict[str, Any] = {
        "self_verdict": self_verdict,
        "mechanical_verdict": mechanical_verdict,
        "flag": NOEVIDENCE,
        "gradeable": False,
    }
    if self_verdict not in (HIT, MISS):
        return out
    if mechanical_verdict not in (HIT, MISS, FLAT):
        return out

    out["gradeable"] = True
    claim_win = self_verdict == HIT
    if claim_win:
        # Claimed a win: only a mechanical HIT confirms it; MISS or FLAT overstates.
        out["flag"] = AGREE if mechanical_verdict == HIT else OVERSTATE
    else:
        # Claimed a miss: a mechanical HIT means he undersold it; else they agree.
        out["flag"] = UNDERSTATE if mechanical_verdict == HIT else AGREE
    return out


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate a list of ``grade_divergence`` results. Always carries n.

    ``overstatement_rate`` is overstate / gradeable, or None when nothing is
    gradeable. A ``note`` is ALWAYS attached warning that the sample is small and
    self-selected -- this function never hands back a bare, context-free rate.
    """
    n_total = len(records)
    gradeable = [r for r in records if r.get("gradeable")]
    n_grade = len(gradeable)
    n_over = sum(1 for r in gradeable if r.get("flag") == OVERSTATE)
    n_under = sum(1 for r in gradeable if r.get("flag") == UNDERSTATE)
    n_agree = sum(1 for r in gradeable if r.get("flag") == AGREE)

    rate = round(n_over / n_grade, 4) if n_grade else None
    note = (
        f"PROVISIONAL: n_gradeable={n_grade} (of {n_total}). Corey posts on "
        "self-selected days and narrates his own outcomes, so this rate is biased "
        "and small-sample. Do not quote without n and an independent-tape check."
    )
    return {
        "n_total": n_total,
        "n_gradeable": n_grade,
        "n_overstate": n_over,
        "n_understate": n_under,
        "n_agree": n_agree,
        "overstatement_rate": rate,
        "note": note,
    }


def render_verdict_divergence(summary: dict[str, Any] | None) -> list[str]:
    """Render a '## Corey Self-Report Divergence' section. Empty when no data."""
    if not summary or not summary.get("n_gradeable"):
        return []
    lines = ["## Corey Self-Report Divergence"]
    rate = summary.get("overstatement_rate")
    rate_str = "n/a" if rate is None else f"{rate:.0%}"
    lines.append(
        f"**Overstatement {rate_str}** "
        f"(overstate {summary['n_overstate']} / understate {summary['n_understate']} / "
        f"agree {summary['n_agree']}; n_gradeable={summary['n_gradeable']} "
        f"of {summary['n_total']})"
    )
    lines.append(f"> {summary.get('note', '')}")
    lines.append("")
    return lines
