# Bookmark-to-Strategy Research Platform Design

**Status:** Approved architecture
**Date:** 2026-08-13
**Scope:** Stage 1 foundation and a manually reviewed 50-bookmark golden batch

## Purpose

Build a reproducible research platform that converts Amo's X bookmarks, linked GitHub repositories, future Reddit research, and every recoverable attachment into traceable claims, computable indicators, preregistered hypotheses, experiments, and append-only verdicts. A source may motivate a hypothesis; it never validates the hypothesis.

## Verified baseline

- 5,632 canonical X records across 13 weekly JSONL files; zero malformed rows.
- 5,546 unique tweet IDs, with 74 duplicate-ID groups requiring version/alias reconciliation.
- Five `.seen.txt` keys have no raw record.
- 331 records have empty tweet text; 335 lack weekly analysis; 21 analyses explicitly failed.
- 2,052 records contain quoted text; 293 contain only short X Article metadata, not complete bodies.
- 1,779 unique expanded links include 867 unique GitHub links and no direct Reddit links.
- 3,873 records reference media: 2,195 inferred images and 1,993 inferred video thumbnails.
- No X images, videos, audio, PDFs, OCR, or transcripts are preserved locally.
- The legacy `.processed.txt` identifiers do not match current canonical keys and are not completeness evidence.

## Non-goals for Stage 1

- No trading strategy is promoted, routed, or declared profitable.
- No paid market-data retrieval or broker mutation occurs.
- No untrusted repository code executes with JARVIS credentials.
- No full-corpus bulk extraction begins until the golden batch passes quality gates.
- No current JARVIS JSON registry is replaced; integration begins read-only and dual-write only after a separate approval.

## Architecture

```text
Canonical source files
  -> idempotent importer
  -> DuckDB research registry
  -> resumable acquisition jobs
  -> content-addressed evidence store
  -> deterministic derivatives (OCR/transcript/table/code)
  -> exact evidence fragments
  -> atomic claims and contradictions
  -> indicators and strategy components
  -> formalization and research queues
```

### Evidence store

Immutable artifacts live beneath `research/evidence/objects/sha256/<prefix>/<hash>`. Model output never overwrites captured evidence. Manifests and derivatives contain the tool, version, model, prompt hash, input hash, output hash, and creation time.

### Registry

Use DuckDB at `research/registry/bookmark_research.duckdb`. All database access goes through repository interfaces; dashboard and scripts do not embed ad hoc SQL. Schema migrations are ordered, checksummed SQL files.

Core tables:

- `sources`, `source_aliases`, `source_versions`, `source_relationships`, `authors`
- `attachments`, `attachment_derivatives`, `fragments`
- `claims`, `claim_evidence`, `concepts`, `claim_concepts`
- `indicators`, `indicator_mentions`, `strategy_ideas`, `idea_components`
- `hypotheses`, `hypothesis_evidence`, `trial_families`
- `dataset_specs`, `experiment_specs`, `experiment_runs`, `run_metrics`
- `robustness_tests`, `verdicts`, `research_decisions`
- `acquisition_jobs`, `legacy_ingest_state`, `artifact_manifests`

Stable IDs use platform-native IDs when available and content hashes otherwise. Attachments are identified by byte SHA-256. Fragments include line, character, page, timestamp, or image bounding-box locators.

## Source completeness contract

Each applicable component has one state:

`not_applicable | not_started | queued | partial | complete | failed_retryable | failed_permanent | blocked_auth | deleted | private | unsupported`

Components are `post_text`, `quote`, `thread`, `article`, `links`, `github`, `images`, `video`, `audio`, `ocr`, and `transcript`. A source is analytically complete only when every applicable component has a terminal state and every successful artifact has a content hash.

## Acquisition behavior

- Jobs are idempotent and keyed by `(source_version_id, component, ordinal, processor_version)`.
- Retries use bounded exponential backoff with per-domain rate limits.
- One failed component does not block independent components.
- Remote media URLs remain provenance; durable evidence is keyed by downloaded bytes.
- Deleted/private/unsupported material remains visible as a terminal failure, never silently disappears.
- Secrets found in source material are quarantined and never written into normal knowledge files.

## Attachment analysis

Images receive original-resolution capture, SHA-256, perceptual hash, MIME/dimensions, OCR, layout segmentation, domain classification, and visual interpretation. Trading charts record symbol, contract, timeframe, visible period, indicator names and parameters, annotations, claimed setup, and reconstructability grade A-D.

Videos require the original media or an authorized transcript source, timestamped transcript, scene/keyframe index, frame OCR, and links between spoken claims and visible charts/code. A thumbnail alone is `partial`, not analyzed.

Code screenshots are reconstructed into a separate derivative, syntax-checked, and never executed automatically. Tables preserve headers, units, footnotes, cell coordinates, and confidence.

## GitHub analysis

Resolve every link to its exact target and containing repository. Relevant repositories are captured at a commit SHA with README, license, release metadata, dependencies, tests, and selected source files. Strategy extraction cites repository, commit, file, line locator, and code hash. Static review checks look-ahead, survivorship, adjusted-price misuse, unrealistic fills, unreported search trials, and time-series split leakage. Execution is isolated and credential-free and is outside Stage 1.

## Claim and strategy model

Claims are atomic propositions linked to exact fragments with relationships `supports`, `contradicts`, `qualifies`, `repeats`, `cites`, `defines`, or `parameterizes`. Extraction confidence, source completeness, claim specificity, evidence quality, and validation state remain separate fields.

Strategy ideas decompose into universe, data, feature, setup, trigger, filter, entry, stop, target, exit, sizing, portfolio interaction, execution, and risk override. Missing fields remain `unknown`; the system never invents defaults.

An idea must achieve a formalization completeness score of at least 85/100 and have deterministic entry, exit, timeframe/session, data policy, sizing, costs, null hypothesis, and falsifiers before preregistration.

## Deduplication and independence

- Exact: native ID, canonical URL, normalized-text hash, attachment hash, repository+commit.
- Near-media: perceptual image hash, video frame fingerprints, audio fingerprint, normalized PDF text.
- Semantic claims: retrieve candidates, then label equivalent/narrower/broader/supports/contradicts/unrelated; never merge on cosine similarity alone.
- Strategies have structural and parameterized fingerprints.
- An independence graph prevents ten posts repeating one paper from counting as ten confirmations.

## Edge ontology

Classify ideas as trend, mean reversion, breakout/expansion, calendar, relative value, volatility, dealer positioning, microstructure, event-driven, carry, cross-sectional, risk overlay, execution improvement, data technique, or evaluation method. Entry strategies, context filters, risk overlays, and execution improvements remain distinct deliverable types.

## Golden batch

Select 50 records deterministically from a frozen manifest:

- at least 10 trading/quantitative posts;
- at least 10 GitHub-linked posts;
- at least 10 chart/image posts;
- at least 5 apparent video posts;
- at least 5 Article/thread/quote-rich posts;
- at least 5 incomplete, ambiguous, deleted, or failed-analysis cases;
- representation from Corey, QuantScience, PyQuantNews, and other high-frequency authors without allowing one author to dominate.

Selection balances engagement, JARVIS relevance, source diversity, attachment type, and failure-mode coverage. Engagement prioritizes review only; it never affects evidence quality.

## Quality gates

The golden batch passes only if:

- all 50 sources import exactly once and reruns are idempotent;
- every applicable component reaches a terminal completeness state;
- every captured artifact has an immutable hash and manifest;
- every extracted claim cites an exact fragment;
- no incomplete idea is silently made deterministic;
- all semantic merges have evidence and review status;
- all attachment failures have reason codes;
- a manual review set achieves at least 95% source/attachment association accuracy, 90% atomic-claim precision, and 100% provenance-link completeness for accepted claims;
- zero secrets enter ordinary artifacts;
- no strategy reaches `ready_for_backtest` solely from model confidence or popularity.

## Backtesting handoff contract

Stage 1 produces formalization candidates, not backtests. A later locked hypothesis specifies universe, session, rule DSL, parameters, trial family, dataset, continuous-futures or options policy, costs, splits, embargo/purging, benchmarks, acceptance/failure criteria, and stress suite.

Discovery uses vectorbt; authoritative event-driven simulation uses NautilusTrader; finalists receive independent LEAN replication. MLflow records runs, DVC versions data/artifacts, and DuckDB stores lineage. Futures signals may use explicitly adjusted continuous series but execution/P&L use raw contracts. Options require point-in-time chains and executable-quote models.

## Security and operational constraints

- Windows 11 and PowerShell-compatible commands; Python uses `engine/.venv/Scripts/python.exe` or a separately documented isolated research environment.
- Never read or copy X cookies, tokens, or JARVIS secrets into artifacts.
- Never execute third-party code in the engine environment.
- Network acquisition is rate-limited and resumable.
- Paid data or API usage requires a cost estimate and explicit cap approval.
- Existing source files and registries are read-only inputs during Stage 1.
- All removals or retirements are archival, never destructive.

## Stage 1 deliverables

1. Versioned DuckDB migrations and repository layer.
2. Content-addressed evidence store and artifact manifest writer.
3. Idempotent canonical JSONL importer and reconciliation report.
4. Completeness state machine and acquisition job ledger.
5. Attachment fetcher with safe limits and hash verification.
6. OCR/vision/transcript derivative interfaces with deterministic manifests.
7. GitHub target resolver and commit-pinned snapshot metadata.
8. Fragment, claim, indicator, and strategy-idea repositories.
9. Deterministic golden-batch selector and frozen manifest.
10. Coverage and golden-batch quality reports.

## Deferred subprojects

Full-corpus execution, Reddit discovery, production dashboards, automated hypothesis compilation, vectorbt/Nautilus/LEAN integration, paid data acquisition, and JARVIS runtime registry integration each require their own reviewed plan after the golden batch validates the foundation.

