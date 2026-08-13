# Bookmark Research Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the immutable evidence registry, resumable acquisition foundation, and verified 50-bookmark golden-batch pipeline without changing trading behavior.

**Architecture:** Import canonical X JSONL into a repository-backed DuckDB registry, store fetched evidence by SHA-256, track component completeness and acquisition jobs independently, then extract exact fragments and claims for a frozen quality-control batch. Existing JARVIS registries and raw bookmark files remain read-only.

**Tech Stack:** Python 3.12, DuckDB, Pydantic v2, pytest, Hypothesis, httpx, Pillow, JSON/JSONL, SHA-256, optional OCR/vision/transcription adapters.

**Spec:** `docs/superpowers/specs/2026-08-13-bookmark-research-platform-design.md`

## Global Constraints

- No strategy promotion, trading-route change, broker mutation, or paid data retrieval.
- Raw bookmark JSONL, `.seen.txt`, `.processed.txt`, and current JARVIS registries are read-only inputs.
- Every artifact and derivative has a SHA-256 manifest; model output never overwrites evidence.
- Missing parameters remain unknown; model confidence and engagement never make an idea test-ready.
- No third-party repository code executes with JARVIS credentials.
- All writes remain under `research/`, `engine/research_registry/`, `engine/scripts/`, `engine/tests/`, and the two approved docs unless a reviewed plan revision says otherwise.

---

## Planned file map

- `engine/research_registry/models.py` — typed source, artifact, completeness, fragment, claim, and idea records.
- `engine/research_registry/database.py` — DuckDB connection and ordered migration runner.
- `engine/research_registry/repositories.py` — all registry reads/writes; no caller SQL.
- `engine/research_registry/import_x.py` — canonical weekly JSONL normalization and reconciliation.
- `engine/research_registry/evidence_store.py` — atomic content-addressed artifact writes and manifests.
- `engine/research_registry/jobs.py` — idempotent acquisition job state machine and retry policy.
- `engine/research_registry/media.py` — bounded media acquisition and metadata classification.
- `engine/research_registry/derivatives.py` — OCR/vision/transcript adapter contracts and manifests.
- `engine/research_registry/github.py` — GitHub URL parsing and commit-pinned metadata contracts.
- `engine/research_registry/extraction.py` — deterministic fragmentation and validated extraction-result import.
- `engine/research_registry/golden_batch.py` — deterministic 50-record selection.
- `engine/research_registry/reporting.py` — coverage and quality reports.
- `engine/research_registry/migrations/001_initial.sql` — normalized Stage 1 schema and constraints.
- `engine/scripts/import_bookmark_corpus.py` — dry-run/default import CLI.
- `engine/scripts/select_golden_bookmarks.py` — frozen-manifest CLI.
- `engine/scripts/process_golden_bookmarks.py` — resumable acquisition/extraction orchestrator.
- `research/manifests/golden-batch-v1.json` — reviewed, immutable selection.
- `engine/tests/research_registry/` — focused unit, property, integration, and fixture tests.

### Task 1: Establish registry models and migration

**Interfaces:** Produces `SourceRecord`, `SourceVersionRecord`, `CompletenessState`, `AcquisitionJob`, `ArtifactManifest`, `FragmentRecord`, `ClaimRecord`, and `StrategyIdeaRecord`; produces `open_registry(path: Path) -> RegistryDatabase`.

- [ ] Write failing schema tests asserting required tables, uniqueness of `(platform, platform_native_id)`, append-only source versions, and completeness-state checks.
- [ ] Run `engine/.venv/Scripts/python.exe -m pytest engine/tests/research_registry/test_database.py -v` and confirm missing-module/schema failures.
- [ ] Add Pydantic records with enums exactly matching the spec and `migrations/001_initial.sql` with foreign keys and indexes.
- [ ] Implement a migration runner that records filename and SHA-256 and refuses a changed applied migration.
- [ ] Re-run the focused tests and add a round-trip test for Unicode tweet text and nullable attachment locators.
- [ ] Commit only Task 1 paths with `feat(research): add bookmark evidence registry schema`.

### Task 2: Implement the content-addressed evidence store

**Interfaces:** Produces `EvidenceStore.put_bytes(data, metadata) -> ArtifactManifest`, `put_file(path, metadata)`, and `verify(manifest) -> bool`.

- [ ] Write failing tests for deterministic paths, duplicate-byte idempotency, MIME metadata, atomic replacement, and hash-mismatch rejection.
- [ ] Implement writes through a temporary file followed by atomic rename; never overwrite an existing hash with different bytes.
- [ ] Write sidecar JSON manifests containing source, URL, capture time, MIME, byte length, hash, tool, and tool version.
- [ ] Add property tests proving arbitrary byte inputs round-trip and duplicate inputs do not create duplicate objects.
- [ ] Run focused tests and commit with `feat(research): add immutable evidence store`.

### Task 3: Import and reconcile the canonical X corpus

**Interfaces:** Consumes `RegistryDatabase`; produces `import_corpus(root: Path, registry, dry_run: bool) -> ImportReport`.

- [ ] Build fixtures for duplicate tweet IDs, empty text, quote/article/media fields, malformed input, and a seen key without raw data.
- [ ] Write failing tests for excluding `-parsed.jsonl`, retaining raw file/line/hash provenance, and idempotent reruns.
- [ ] Implement normalization for the 13 canonical `2026-W*.jsonl` files and preserve all aliases rather than deleting duplicates.
- [ ] Import `.seen.txt` and `.processed.txt` into `legacy_ingest_state` without interpreting legacy processed IDs as completeness.
- [ ] Add reconciliation output for canonical rows, logical tweets, duplicate groups, missing raw records, and per-component starting states.
- [ ] Run against fixtures, then run the CLI in `--dry-run` against the real corpus and assert 5,632 rows, 5,546 tweet IDs, 74 duplicate groups, and five seen-only keys.
- [ ] Commit with `feat(research): import canonical X bookmark corpus`.

### Task 4: Add acquisition jobs and completeness derivation

**Interfaces:** Produces `claim_job`, `start_job`, `complete_job`, `fail_job`, `next_jobs`, and `derive_source_completeness`.

- [ ] Write state-machine tests covering valid transitions, retry ceilings, terminal failures, component independence, and idempotent job claims.
- [ ] Implement unique job identity `(source_version_id, component, ordinal, processor_version)` and bounded exponential backoff with deterministic jitter seed.
- [ ] Implement analytical-completeness derivation requiring every applicable component to reach a terminal state.
- [ ] Add crash-recovery tests proving an abandoned running job becomes retryable without duplicating artifacts.
- [ ] Commit with `feat(research): track resumable evidence acquisition`.

### Task 5: Implement bounded attachment acquisition

**Interfaces:** Produces `MediaFetcher.fetch(job, limits) -> FetchResult`; consumes `EvidenceStore` and acquisition jobs.

- [ ] Write mocked HTTP tests for redirects, supported MIME types, byte limits, timeouts, 404/deleted media, retryable 429/5xx responses, and hash deduplication.
- [ ] Implement streaming downloads with explicit connect/read timeouts and maximum bytes; do not load unbounded responses into memory.
- [ ] Record original/resolved URLs, headers, MIME, dimensions where available, and terminal reason codes.
- [ ] Add URL classification distinguishing likely images from video thumbnails; a thumbnail must never complete the video component.
- [ ] Run tests without real network access and commit with `feat(research): acquire and hash bookmark media`.

### Task 6: Define derivative adapters and exact fragments

**Interfaces:** Produces `DerivativeAdapter.process(artifact) -> DerivativeResult` and fragment writers for text spans, OCR regions, timestamps, code spans, and table cells.

- [ ] Write contract tests using fake OCR, vision, and transcript adapters; assert every derivative records input/output hashes, tool/model version, and locator data.
- [ ] Implement adapter protocols and deterministic manifest validation without binding Stage 1 to a single provider.
- [ ] Implement text fragmentation preserving raw line and character offsets and image/video locator schemas.
- [ ] Add tests that reject fragments without a valid source version or attachment hash.
- [ ] Commit with `feat(research): add evidence derivative contracts`.

### Task 7: Resolve GitHub targets reproducibly

**Interfaces:** Produces `parse_github_url(url) -> GitHubTarget` and `GitHubSnapshotManifest` containing repository, exact target, resolved commit, and captured artifacts.

- [ ] Write table-driven tests for repository, blob, tree, commit, release, issue, pull request, discussion, gist, and invalid URLs.
- [ ] Implement pure URL parsing first; add a mocked API client with rate-limit and not-found handling.
- [ ] Require a resolved commit SHA before a repository snapshot can be marked complete.
- [ ] Add fixture tests proving mutable default-branch URLs resolve into immutable snapshot identities.
- [ ] Commit with `feat(research): resolve commit-pinned GitHub evidence`.

### Task 8: Import atomic claims and strategy ideas

**Interfaces:** Produces `import_extraction(result: ExtractionResult) -> ExtractionImportReport`, structural fingerprints, and formalization scores.

- [ ] Write failing tests for exact fragment citations, contradiction edges, unknown parameters, equivalent-claim candidates, and separation of evidence quality from extraction confidence.
- [ ] Implement validated JSON schemas for claims, indicator mentions, idea components, and review status.
- [ ] Implement structural and parameterized strategy fingerprints from normalized rule graphs.
- [ ] Implement the 100-point formalization score and prohibit `ready_for_backtest` below 85 or with missing deterministic entry/exit/session/data/cost/null fields.
- [ ] Add tests proving engagement/follower counts cannot change evidence or readiness status.
- [ ] Commit with `feat(research): register sourced claims and strategy ideas`.

### Task 9: Select and freeze the golden batch

**Interfaces:** Produces `select_golden_batch(candidates, policy, seed) -> GoldenBatchManifest`.

- [ ] Write failing tests for exactly 50 unique source records, required category minimums, author-diversity cap, deterministic seed, and manifest hashes.
- [ ] Implement scored stratified selection using source diversity, attachment coverage, failure-mode coverage, JARVIS relevance, and engagement only as a reading-priority tiebreaker.
- [ ] Run selection against imported metadata and review the proposed manifest for category and author balance.
- [ ] Freeze `research/manifests/golden-batch-v1.json` with selector version, seed, policy, source IDs, and manifest SHA-256.
- [ ] Commit with `feat(research): freeze bookmark golden batch`.

### Task 10: Build the resumable golden-batch orchestrator

**Interfaces:** Produces a dry-run/default CLI with `--acquire`, `--derive`, `--source-id`, `--max-jobs`, and `--resume`; no paid services are invoked implicitly.

- [ ] Write integration tests with fake acquisition and derivative adapters covering success, partial evidence, retries, restart/resume, and permanent failures.
- [ ] Implement orchestration as job scheduling plus repository calls; keep providers behind interfaces.
- [ ] Default to dry-run and require explicit flags for network acquisition and model-derived processing.
- [ ] Emit machine-readable JSON and human-readable Markdown reports without marking partial sources complete.
- [ ] Commit with `feat(research): orchestrate golden bookmark analysis`.

### Task 11: Add coverage and quality reporting

**Interfaces:** Produces `build_coverage_report(registry) -> CoverageReport` and `build_golden_quality_report(registry, manifest) -> GoldenQualityReport`.

- [ ] Write tests for global totals, component-state matrices, missing artifacts, failed jobs, claim provenance, formalization queues, and legacy-ledger mismatch reporting.
- [ ] Implement DuckDB-backed views for source completeness, unprocessed attachments, claims needing review, contradictions, idea clusters, formalization backlog, and provenance gaps.
- [ ] Add explicit golden thresholds: 95% source/attachment association accuracy, 90% atomic-claim precision, and 100% provenance completeness for accepted claims.
- [ ] Generate reports into `research/reports/` with timestamp, code commit, registry hash, and manifest hash.
- [ ] Commit with `feat(research): report bookmark evidence coverage`.

### Task 12: Verify Stage 1 and document the scale-up gate

**Interfaces:** Consumes all Stage 1 outputs; produces a signed-off quality report and no trading-system mutation.

- [ ] Run all focused tests: `engine/.venv/Scripts/python.exe -m pytest engine/tests/research_registry -v`.
- [ ] Run Ruff on `engine/research_registry` and the three new CLIs.
- [ ] Re-import the real corpus twice into a disposable registry and verify identical counts and hashes.
- [ ] Verify the golden manifest contains exactly 50 unique sources and every processed component has a terminal state.
- [ ] Manually review the predefined audit sample and record precision/provenance results.
- [ ] Run the repository's non-slow regression suite before declaring integration safe.
- [ ] Write `research/reports/STAGE1_SCALE_UP_DECISION.md` with PASS/FAIL against every spec criterion; FAIL means no full-corpus launch.
- [ ] Commit with `docs(research): record bookmark foundation verification`.

## Self-review record

- Spec coverage: foundation storage, import, reconciliation, jobs, attachments, derivatives, GitHub, claims, formalization, golden selection, reporting, and verification each map to a task.
- Deferred scope is explicit: Reddit discovery, full 5,632-record execution, provider selection, production dashboards, and backtest-engine integration are separate subprojects.
- Type consistency: registry, evidence, job, derivative, extraction, manifest, and reporting interfaces are introduced before consumers.
- Placeholder scan: no implementation step relies on an unspecified error-handling or testing instruction.

