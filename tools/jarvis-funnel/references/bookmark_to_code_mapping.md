# Bookmark-to-Code Mapping Logic

How Phase 1 inventory deduplicates strategies across X bookmarks and the jarvis-trader repo.

## The Problem

You bookmark a tweet from `@quant_trader_42` describing "opening range breakout on ES with 30-min range, 2R target, 1R stop." You also have `engine/backtest/orb_signals.py` and `engine/backtest/run_mes_orb_rank1.py` in the repo.

Are these the same hypothesis? Yes. Should they be the same strategy card? Yes. How do we know automatically? That's what this doc specifies.

## The Three-Pass Approach

### Pass 1: Extract Hypothesis Atoms from Both Sides

**From repo (per file):**
For each file in `engine/backtest/run_*.py`, `engine/strategies/`, `engine/strategy_lab/`, `.pine` TOS scripts:
1. LLM agent reads the file
2. Extracts: `category`, `instrument`, `timeframe`, `entry_keywords` (3–5 keywords from entry logic), `exit_keywords`, `parameters` (key=default pairs)
3. Drafts a candidate `economic_rationale` from comments + variable names + analysis docs that reference this file

**From bookmarks (per bookmark):**
For each bookmark in the OneDrive export:
1. LLM agent reads tweet text + any quoted/linked thread
2. Extracts: `claimed_category`, `claimed_instrument`, `claimed_timeframe`, `claim_keywords`, `claimed_metrics` (Sharpe, win rate, R-multiple if stated)
3. Notes author handle and date

Both pass-1 outputs are saved as **atoms** before any merging:
- `atoms_repo.jsonl` — one atom per repo file
- `atoms_bookmarks.jsonl` — one atom per bookmark

### Pass 2: Compute Cross-Source Similarity

For every (repo_atom, bookmark_atom) pair, compute a similarity score:

```
similarity = 
    0.30 × category_match
  + 0.20 × instrument_class_match
  + 0.20 × timeframe_class_match
  + 0.20 × keyword_overlap_ratio
  + 0.10 × parameter_overlap_ratio
```

Where:
- `category_match`: 1.0 if exact, 0.5 if adjacent (e.g., `breakout` vs `momentum`), 0 otherwise
- `instrument_class_match`: 1.0 if same class (ES↔MES same; ES↔NQ different but both index futures = 0.7)
- `timeframe_class_match`: 1.0 if same class (5m and 15m both intraday = 1.0; 5m and 1h = 0.5; 5m and daily = 0)
- `keyword_overlap_ratio`: Jaccard similarity of entry_keywords ∪ exit_keywords
- `parameter_overlap_ratio`: fraction of params with the same name (values may differ)

### Pass 3: Merge Decision

Apply thresholds to the similarity score:

| Score Range | Action |
|---|---|
| ≥ 0.80 | **Auto-merge** — single card, both sources cited |
| 0.50–0.80 | **Candidate merge** — flag for human review |
| < 0.50 | **No merge** — standalone cards |

### Within-Source Dedup

Before cross-source merging, dedup within each source:

**Within repo:** Files that obviously implement the same strategy (e.g., `run_mes_orb_rank1.py`, `run_mes_orb_rank2.py`, `orb_signals.py`, `orb_backtester.py`, `orb_walk_forward.py`) get auto-grouped if they share:
- Same prefix (`orb_`, `run_mes_orb_`, etc.) OR
- Same module imported (e.g., all import from `orb_signals.py`)

The "canonical" file is the one with the most lines / most-recent commit / explicit "rank1" suffix.

**Within bookmarks:** Bookmarks from the same author within 7 days describing the same category+instrument get auto-grouped as a single source. (Same person elaborating on one idea.)

## What Happens to Merged Cards

When a card is merged from multiple sources, its `provenance` field gets ALL sources:

```json
"provenance": {
  "repo_sources": [
    {"path": "engine/backtest/orb_signals.py", "git_sha": "...", "role": "implementation"},
    {"path": "engine/backtest/run_mes_orb_rank1.py", "git_sha": "...", "role": "runner"},
    {"path": "engine/backtest/orb_walk_forward.py", "git_sha": "...", "role": "wfo"}
  ],
  "bookmark_sources": [
    {"url": "...", "author_handle": "@quant_trader_42", "claim_summary": "ORB 30min ES 60% win 2R"}
  ],
  "external_doc_sources": [
    {"path": "JARVIS_TRADER_MASTER_PART2.md", "section": "## Breakout Strategies"}
  ]
}
```

The card's primary `entry_logic` / `exit_logic` / `parameters` come from the **repo implementation** (it's the verifiable source).

The bookmark's claimed metrics and variations go into:
- `untested_variants_from_bookmarks` (array of suggested changes)
- A note in `notes` field if bookmark claims significantly diverge from repo backtest results (worth investigating)

## Conflict Resolution

When repo and bookmark disagree:

| Conflict | Resolution |
|---|---|
| Different parameter defaults | Repo wins; bookmark's value added to `parameter_sensitivity_to_test` |
| Different exit logic | Both logged; primary = repo; bookmark variant goes to `untested_variants_from_bookmarks` |
| Repo says strategy FAILED gate_v2, bookmark claims high Sharpe | Flag in `notes`: "Bookmark claim contradicts repo verdict — investigate why" |
| Bookmark claims work on instrument repo doesn't test | Add to `instruments.applicable_to` (untested) |

## Standalone Bookmarks (No Repo Match)

Bookmarks that don't match any repo strategy become **standalone cards** with:
- `implementation_status.exists_in_repo: false`
- `next_action: "Implement in engine/strategies/ before Phase 2"`
- Card stays in Phase 1 status `NEEDS_IMPLEMENTATION` until Matt either implements it or marks `skip_implementation: true` (and it gets killed at Phase 2 entry)

This is intentional friction. Bookmark-only ideas are cheap to collect and expensive to test. They have to clear a bar before consuming Phase 2 compute.

## Standalone Repo Strategies (No Bookmark)

Most repo strategies will have no bookmark match. That's fine. They proceed through phases on their own merits. The lack of an external source isn't a negative signal — many good ideas come from the author's own research.

## Special Case: TOS / Pine Scripts

`*.pine` files (ThinkOrSwim / TradingView scripts) live in `engine/thinkorswim-scripts/`. These are treated like repo sources but with a flag:
- `provenance.repo_sources[].role: "tos_script"` 
- Indicates the implementation may not yet exist in Python — adds a step before Phase 2

## Special Case: External Analysis Docs

The 9+ `JARVIS_TRADER_*.md` files in the repo root contain a lot of strategy discussion. These are treated as supplementary sources — they enrich existing cards but don't create new ones on their own. Phase 1 extracts hypothesis discussions from these docs and attaches them to matching cards under `external_doc_sources`.

## Output Quality Checks

After Phase 1 produces `strategies_v1.jsonl`:

1. **Dup check:** No two cards with the same `hypothesis_id`
2. **Orphan check:** No bookmark atom unaccounted for (either merged or standalone card)
3. **Rationale check:** Every card has `economic_rationale` ≥ 50 chars OR `phase_1_status: NEEDS_RATIONALE`
4. **Provenance check:** Every card has ≥ 1 source in `provenance`
5. **Hypothesis_id format check:** All IDs match the `{category}_{descriptor}_{instrument_class}_{timeframe_class}` convention

Failures of 1–4 block Phase 2. Failure of 5 is warning only (Phase 1 auto-fixes).
