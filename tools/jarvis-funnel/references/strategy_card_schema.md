# Strategy Card JSONL Schema

The single source of truth for what a "strategy" is in the funnel. Every record in `strategies_vN.jsonl` follows this schema.

## File Convention

- One JSON object per line (JSONL format)
- File versioning: `strategies_v1.jsonl` (after Phase 1), `strategies_v2.jsonl` (after Phase 2), etc.
- Each version is append-only relative to the prior — strategies don't disappear, their `status` field changes
- Stored in `OneDrive/jarvis-trader-handoff/cards/`

## Schema

```json
{
  "hypothesis_id": "orb_breakout_es_intraday",
  "schema_version": "1.0",
  "created_at": "2026-06-26T08:00:00Z",
  "updated_at": "2026-06-26T08:00:00Z",

  "name": "Opening Range Breakout — ES Intraday",
  "category": "breakout",
  "subcategory": "session_open",

  "economic_rationale": "Institutional order flow concentrates in the first 30min of RTH session, establishing a price range. Breakouts from this range capture continuation moves as systematic and discretionary traders pile in along the new direction. Edge decays as session matures and range becomes well-defined to participants.",

  "rationale_strength": "STRONG",

  "instruments": {
    "primary": "ES",
    "tested_on": ["ES", "MES"],
    "applicable_to": ["ES", "MES", "NQ", "MNQ", "RTY", "M2K"],
    "do_not_use_on": ["GC", "CL"]
  },

  "timeframes": {
    "primary": "5m",
    "applicable": ["5m", "15m"],
    "rationale_for_tf": "Intraday signal; 30m loses the opening dynamics, 1m has too much noise"
  },

  "entry_logic": "Long when price breaks above the high of the first 30min of RTH; Short when price breaks below the low. One trade per direction per session.",

  "exit_logic": "Profit target: 2× the opening range size. Stop: 1× ATR(14) opposite the entry. Time stop: end of RTH session.",

  "parameters": {
    "opening_range_minutes": 30,
    "atr_period": 14,
    "atr_stop_multiplier": 1.0,
    "profit_target_or_multiplier": 2.0,
    "session_start_et": "09:30",
    "session_end_et": "16:00"
  },

  "parameter_sensitivity_to_test": {
    "opening_range_minutes": [15, 20, 30, 45, 60],
    "atr_stop_multiplier": [0.75, 1.0, 1.25, 1.5],
    "profit_target_or_multiplier": [1.5, 2.0, 2.5, 3.0]
  },

  "expected_regime_performance": {
    "low_vol": "MARGINAL",
    "normal_vol": "STRONG",
    "elevated_vol": "STRONG",
    "high_vol": "UNKNOWN"
  },

  "expected_failure_modes": [
    "Choppy range-bound days where breakout reverses (false breakouts)",
    "Pre-FOMC or pre-NFP days with suppressed opening volatility",
    "Holiday-shortened sessions with abnormal opening dynamics"
  ],

  "provenance": {
    "repo_sources": [
      {
        "path": "engine/backtest/orb_signals.py",
        "git_sha": "abc123",
        "last_seen": "2026-06-26"
      },
      {
        "path": "engine/backtest/run_mes_orb_rank1.py",
        "git_sha": "abc123",
        "last_seen": "2026-06-26"
      },
      {
        "path": "engine/backtest/orb_walk_forward.py",
        "git_sha": "abc123",
        "last_seen": "2026-06-26"
      }
    ],
    "bookmark_sources": [
      {
        "url": "https://x.com/some_trader/status/123456",
        "author_handle": "@some_trader",
        "saved_at": "2025-11-15",
        "claim_summary": "ORB 30min works on ES, 60% win rate, 2R targets",
        "claim_verified_in_repo": true
      }
    ],
    "external_doc_sources": [
      {
        "path": "JARVIS_TRADER_MASTER_PART2.md",
        "section": "## Breakout Strategies",
        "last_seen": "2026-06-26"
      }
    ]
  },

  "untested_variants_from_bookmarks": [
    "Filter on premarket volume > X percentile",
    "Skip if overnight gap > 0.5%",
    "Use VWAP as additional confluence for entry"
  ],

  "implementation_status": {
    "exists_in_repo": true,
    "has_backtest": true,
    "has_walk_forward": true,
    "has_paper_trading": false,
    "has_live_trading": false,
    "current_repo_verdict": "FAIL_gate_v2_2026-05-06"
  },

  "phase_1_status": "PASSED",
  "phase_2_status": null,
  "phase_3_status": null,
  "phase_4_status": null,

  "current_tier": null,
  "tier_history": [],

  "next_action": "Phase 2 smoke test on ES 5m, 24mo, author defaults",

  "notes": "Repo's gate_v2 marked this FAIL in May 2026, but the new funnel_gate may reach a different verdict. Worth re-testing — gate_v2's FAIL was based on PF CI lower bound 0, which may be a fixable parameter issue, not a fundamental edge issue."
}
```

## Field Definitions

### Identity
- **hypothesis_id** (string, required, unique): Snake-case canonical name for the *economic idea*, not the specific implementation. Used as primary key for dedup. Format: `{category}_{descriptor}_{instrument_class}_{timeframe_class}`.
- **schema_version** (string): Track schema changes
- **created_at, updated_at** (ISO 8601): Timestamps

### Description
- **name** (string): Human-readable name
- **category** (enum): `breakout` | `mean_reversion` | `trend_following` | `momentum` | `carry` | `arbitrage` | `event_driven` | `volatility` | `seasonality` | `microstructure` | `ml_based` | `composite`
- **subcategory** (string): Free text refinement

### The Critical Field: Economic Rationale
- **economic_rationale** (string, required, min 50 chars): WHY this should work. "RSI < 30 = buy" without a reason is auto-killed.
- **rationale_strength** (enum): `STRONG` | `MODERATE` | `WEAK` | `MISSING` — auto-computed by Phase 1 LLM based on rationale quality

### Scope
- **instruments**: Primary + tested + applicable + do-not-use
- **timeframes**: Primary + applicable + rationale for the TF choice

### Logic
- **entry_logic** (string): Plain English entry rules
- **exit_logic** (string): Plain English exit rules
- **parameters** (object): Default parameter values
- **parameter_sensitivity_to_test** (object): Sweep ranges for Phase 3

### Expectations (Pre-Test)
- **expected_regime_performance**: `STRONG` | `MARGINAL` | `WEAK` | `UNKNOWN` per regime
- **expected_failure_modes** (array): Known/suspected failure scenarios

### Provenance (Merged from Repo + Bookmarks + Docs)
- **provenance.repo_sources** (array): All repo files implementing or describing this hypothesis
- **provenance.bookmark_sources** (array): X bookmarks describing this idea, with verification flag
- **provenance.external_doc_sources** (array): Analysis docs in the repo discussing this hypothesis

### Bookmark-Specific Enrichment
- **untested_variants_from_bookmarks** (array): Variations suggested by bookmarks that aren't yet tested. Feed into Phase 3 parameter sensitivity.

### Status Tracking
- **implementation_status**: What exists in the repo today
- **phase_N_status** (enum): `null` | `PASSED` | `FAILED` | `NEEDS_RATIONALE` | `IN_PROGRESS`
- **current_tier** (enum): `null` | `A` | `B` | `C`
- **tier_history** (array): Log of tier changes with timestamps and reasons
- **next_action** (string): What to do next with this strategy

### Free Notes
- **notes** (string): Anything the LLM or human wants to flag

## Hypothesis ID Convention

The `hypothesis_id` is critical because it's how we dedup. Convention:

```
{category}_{descriptor}_{instrument_class}_{timeframe_class}
```

- **category**: from the enum above
- **descriptor**: 1-3 words describing the specific edge (e.g., `breakout`, `gap_fade`, `vix_contango`)
- **instrument_class**: `es` | `nq` | `gc` | `cl` | `zc` | `vix` | `equity` | `options` | `multi`
- **timeframe_class**: `intraday` | `swing` | `overnight` | `multiday` | `eod`

Examples:
- `breakout_opening_range_es_intraday`
- `mean_reversion_overnight_gap_es_overnight`
- `volatility_contango_carry_vix_multiday`
- `trend_following_donchian_es_swing`

**Same `hypothesis_id` = same strategy** even if implementation details differ. The card merges multiple implementations.

## Bookmark-to-Code Mapping (Dedup Logic)

When Phase 1 finds both a repo implementation and a bookmark describing what may be the same idea:

### Auto-Merge Triggers (high confidence)
- Same category + same instrument class + same timeframe class + ≥ 2 keyword overlap in entry logic
- Example: `engine/backtest/orb_signals.py` (category=breakout, instrument=ES, tf=intraday, keywords=["opening", "range", "breakout"]) + bookmark mentioning "ORB" or "opening range breakout on ES" → auto-merge

### Manual Review Required (medium confidence)
- Same category + same instrument class but different timeframe, OR
- Same instrument class + same timeframe but different category, OR
- Keyword overlap 1 of 2+

→ Phase 1 LLM produces a "candidate_merge" entry; human reviews before merging

### No Merge (low confidence)
- Different category AND different instrument class → standalone cards

The mapping logic lives in `references/bookmark_to_code_mapping.md` and is implemented in `scripts/phase1_inventory.py::_dedup_and_merge()`.

## Versioning Workflow

```
Phase 1 inventory → strategies_v1.jsonl
                        ↓
Phase 2 results → strategies_v2.jsonl (status fields updated, no new cards unless mid-phase discovery)
                        ↓
Phase 3 results → strategies_v3.jsonl
                        ↓
Phase 4 results → strategies_v4.jsonl (final)
                        ↓
Tier assignments → strategies_current.jsonl (live, mutable, used by tracker.py)
```

`strategies_current.jsonl` is the only file the tracker reads. The vN files are immutable snapshots for audit.
