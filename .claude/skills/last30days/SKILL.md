---
name: last30days
description: Wrapper skill for the last30days research aggregator plugin — queries Reddit, X, YouTube, TikTok, Polymarket, GitHub, and web search in parallel, scores by real engagement, and returns a synthesized brief. Use before any trade setup, after a major news event, when validating a trade thesis against community sentiment, or when asked "what's the vibe on X", "check sentiment for Y", "research last 30 days of Z", "recent chatter on <symbol|topic>", "news sweep for <topic>".
---

# last30days — research wrapper for jarvis-trader

Thin routing layer on top of [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill) (MIT). This skill does not reimplement the research pipeline — it adds jarvis-trader-specific usage context so the plugin gets invoked correctly for pre-trade research.

## Install prerequisite

The plugin must be installed once per machine. From within Claude Code:

```
/plugin marketplace add mvanhorn/last30days-skill
/plugin install last30days-official@last30days-skill
```

If the plugin isn't installed, `/last30days` will return "command not found" and this skill has no effect. Verify with `claude plugin list | grep last30days`.

## When to use

- Pre-trade validation: before committing capital to a discretionary setup on MCL, MNQ, MES, or any options spread.
- News event context: after a Fed decision, CPI release, OPEC statement, or geopolitical event moves a market.
- Trade thesis check: the debate stack said BUY — what is the broader community saying?
- Morning brief enrichment: topics worth researching before open (run manually, not on cron — see below).

## When NOT to use

- Autonomous signal generation — last30days synthesizes background research, it does NOT feed the debate/trader agents. Do not wire its output into `pipeline.py` or `debate.py` without a separate safety review.
- Replacing the morning brief — `engine/notifications/morning_brief.py` already handles portfolio, macro, and Corey commentary. last30days is supplementary, not a replacement.
- Outside Globex hours for futures queries — if the market is closed, recency signals are stale by definition. Skill will still return results; treat them as weekend-read context, not actionable sentiment.

## How to invoke

Direct plugin call:

```
/last30days MCL
/last30days "Fed decision March 2026"
/last30days "crude oil inventory surprise"
```

The plugin returns a markdown brief with a **Best Takes** section plus per-platform entity summaries.

## jarvis-trader context to pass when invoking

When you run this inside a trading session, prefer topic strings that include:

- The ticker symbol in broker format (`MCL`, `MNQ`, `MES`) plus a plain-English descriptor.
- Time window if recent (`"last 3 days"`, `"since CPI"`).
- Source bias if known (`"Reddit r/WallStreetBets"`, `"FinTwit"`).

Example: `/last30days "MCL crude oil OPEC cut last 7 days Reddit + X"`

## Integration with existing workflow

- **Before** `/jarvis-pretrade-check`: run `/last30days <symbol>` to build sentiment context.
- **After** a debate verdict of `inconclusive`: run `/last30days <symbol>` to add qualitative input.
- **During** session handoff: do NOT capture last30days output into session logs unless user explicitly asks — research context is ephemeral, handoffs are for decisions.

## Deferred — automation into morning brief

Proposed in the analysis doc but not implemented: extending `engine/notifications/morning_brief.py` to call `/last30days` for a config-defined `RESEARCH_TOPICS` list. Deferred because:

1. Requires auth setup (X browser session, YouTube/TikTok ScrapeCreators token, optional Polymarket key).
2. Rate-limit exposure — cron invocation on stale tokens will silently 429.
3. Adds recency-bias risk to a notification channel that's meant to be deterministic.

Revisit if the team decides systematic research is a measurable trading edge.

## Attribution

Wrapper around [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill), MIT-licensed. No code copied; this file documents the invocation pattern and trading-context usage only.

## Analysis provenance

Full integration analysis at `docs/repo-integrations/mvanhorn__last30days-skill.md` (batch pilot 2026-04-17, commit `61f4bb2`).
