# Personal Discord Autonomous Analyzer — Design Spec

**Date:** 2026-05-20
**Author:** Amo + Claude (Opus 4.7)
**Status:** Approved design — pending implementation plan
**Scope:** Augment the existing `engine/discord/` pipeline so every artifact in personal Discord channel `1490851279180660819` (Jarvis-Trader #general) is deeply analyzed autonomously, 24/7, while Amo is away from the keyboard.

---

## Goal

Today the channel feeds a SQLite `discord_bookmarks` table (393+ rows) via a daily refresh task. The pipeline only **extracts URLs** — it does not read or understand them. The goal of this spec is to upgrade that to **autonomous deep analysis of every artifact**, with results landing in two browsable surfaces (Obsidian vault + gbrain RAG store) and a daily digest.

## Non-goals

- Not building a Discord bot that replies in-channel. (Output surfaces are the Obsidian vault, the gbrain store, and a daily digest — not the same channel that's the input source.)
- Not refactoring the existing bookmark refresh pipeline. The deep analyzer is purely additive.
- Not handling channels other than `1490851279180660819` in this iteration. (Architecturally pluggable for later channels.)
- Not building an agent loop. Hermes is the LLM gateway only, not the orchestrator. (Hybrid orchestrator/agent is a future option, captured in Option C below.)

## Constraints

- Daily LLM spend ≤ **$2/day** (configurable via `DEEP_ANALYZER_DAILY_USD`).
- Max **5 items per 2-minute poll** to bound burst cost and keep restart blast-radius small.
- Local secrets policy (`rules/secret-hygiene.md`): all keys via 1Password / Hermes config — never in code or `.env`.
- Windows pitfalls (`rules/windows-pitfalls.md`): any `.ps1` invoked by Task Scheduler must be UTF-8 with BOM and use `127.0.0.1`, not `localhost`.
- Health-gate verification (`rules/verification.md`): rollout phases must verify with concrete commands, not log absence.

## Existing infrastructure leveraged

| Component | Status | Role in new design |
|---|---|---|
| `engine/discord/` package | Production | Hosts the new `deep_analyzer/` submodule |
| `discord_bookmarks` SQLite table | 393+ rows | Source of artifacts to analyze; gets 3 new columns |
| `refresh_discord_bookmarks.ps1` scheduled task | Daily | Continues to populate `discord_bookmarks`; unchanged |
| `engine/llm/client.py` `JarvisLLMClient` | Production | LLM gateway — Anthropic primary, Gemini failover, cost tracker, `llm_path_healthy` signal. Already wired. |
| Hermes gateway (Telegram/Discord adapter, separate process) | Active | Used only for the daily Discord DM digest delivery — NOT for LLM calls (Hermes has no REST LLM endpoint). |
| `~/my-vault` Obsidian vault | Active | Output surface 1 — durable markdown per artifact |
| gbrain trading brain (1248p / 2251 chunks, Ollama 768-dim embeddings) | Active | Output surface 2 — semantic retrieval |

## Architecture

Three options were considered:

### Option A — Extend `engine/discord/` (selected)

```
[existing] discord_bookmarks (SQLite)
                    │
                    ▼
deep_analyzer/runner.py — every 2 min, picks rows where analyzed_at IS NULL
                    │
       ┌────────────┼────────────┬─────────────┬─────────────┐
       ▼            ▼            ▼             ▼             ▼
   url_handler  image_handler  audio_handler  document_h    text_handler
                    │
                    ▼
        discord_analyses table  +  vault page  +  gbrain ingest
                    │
                    ▼
[06:00 daily] digest.py → ~/my-vault/Daily/YYYY-MM-DD.md "Overnight feed" + Hermes DM
```

**Pros:** Reuses 90% of working infra; checkpoint-able via `analyzed_at`; same operational story as the existing refresh task; failure of one artifact doesn't block others.
**Cons:** Tied to jarvis-trader repo; needs careful per-handler error isolation.

### Option B — Hermes agent loop drives it (rejected)

Standalone Hermes agent runs continuously, calls jarvis-discord MCP, decides per-artifact, calls tools, writes outputs.

**Why rejected:** Agent loops are token-expensive; harder to checkpoint; Hermes already emits Gemini `thinking_config` 400s — putting it in the critical path is risk.

### Option C — Hybrid: deterministic + agent escalation (deferred)

Deterministic dispatch for the 90% case; agent escalation for high-priority / multi-artifact items.

**Why deferred:** Premature complexity until A is shipped and we have signal on what items merit escalation. The deep_analyzer dispatcher is the natural extension point for this later.

## Components

| Component | File | Responsibility |
|---|---|---|
| Orchestrator | `engine/discord/deep_analyzer/runner.py` | Pick unanalyzed rows (LIMIT 5); dispatch; write analysis row; emit side-effects; checkpoint; enforce daily budget |
| URL handler | `engine/discord/deep_analyzer/handlers/url.py` | `httpx` fetch → readability extract → X-post special case → LLM summarize + extract entities, tickers, sentiment, action items |
| Image handler | `engine/discord/deep_analyzer/handlers/image.py` | Download attachment → Gemini 2.5-flash vision via Hermes → OCR + scene + (if chart) symbol + timeframe |
| Audio handler | `engine/discord/deep_analyzer/handlers/audio.py` | Download → `faster-whisper` local transcribe (GPU) → LLM analyze transcript |
| Document handler | `engine/discord/deep_analyzer/handlers/document.py` | `pypdf` / `pdfplumber` → chunk → LLM analyze + index |
| Text handler | `engine/discord/deep_analyzer/handlers/text.py` | Pure text from message body → LLM extract structured fields |
| LLM client | `engine/discord/deep_analyzer/llm.py` | Single entry-point routing through Hermes HTTP API → Gemini primary, Anthropic fallback; per-model price table for cost tracking |
| Storage | `engine/discord/deep_analyzer/storage.py` | DDL + CRUD for `discord_analyses` table; daily-budget query |
| Vault writer | `engine/discord/deep_analyzer/vault.py` | Writes `~/my-vault/Discord-Feed/YYYY-MM-DD/<bookmark_id>--<slug>.md` with YAML frontmatter + analysis body |
| gbrain sink | `engine/discord/deep_analyzer/gbrain_sink.py` | POSTs to gbrain ingest endpoint or writes to the trading brain's `raw/` watched directory |
| Digest generator | `engine/discord/deep_analyzer/digest.py` | Reads last 24h from `discord_analyses`; ranks by priority; writes daily digest section; optionally sends Hermes DM with link |

## Data flow (image example)

```
1. runner.py
   SELECT id, raw_payload FROM discord_bookmarks
   WHERE analyzed_at IS NULL
     AND (claimed_at IS NULL OR claimed_at < datetime('now', '-10 minutes'))
   ORDER BY posted_at DESC LIMIT 5

2. runner.py UPDATE discord_bookmarks SET claimed_at = now() WHERE id IN (...)

3. dispatch(row) → image.py
   - download attachment to %TEMP%\deep_analyzer\<bookmark_id>.png
   - call llm.vision(prompt=IMAGE_PROMPT, image_bytes)
     - Hermes API: provider=google, model=gemini-2.5-flash
     - fallback: anthropic claude-haiku-4-5
   - structured_json = {ocr_text, scene, chart_detected, ticker?, timeframe?, salient_points[]}
   - return AnalysisResult(summary, structured_json, model_used, cost_usd)

4. runner.py
   INSERT INTO discord_analyses (bookmark_id, artifact_type='image', summary, structured_json, model_used, cost_usd)
   vault.write(result)        → ~/my-vault/Discord-Feed/2026-05-20/<id>--<slug>.md
   gbrain_sink.ingest(result) → POST or filesystem write
   UPDATE discord_bookmarks SET analyzed_at=now(), analysis_id=<id>
   delete %TEMP% file
```

## Schema (additive only)

```sql
ALTER TABLE discord_bookmarks ADD COLUMN analyzed_at TIMESTAMP NULL;
ALTER TABLE discord_bookmarks ADD COLUMN claimed_at TIMESTAMP NULL;
ALTER TABLE discord_bookmarks ADD COLUMN analysis_id INTEGER NULL;

CREATE TABLE discord_analyses (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  bookmark_id   INTEGER NOT NULL REFERENCES discord_bookmarks(id),
  artifact_type TEXT    NOT NULL,  -- 'url' | 'image' | 'audio' | 'document' | 'text'
  summary       TEXT    NOT NULL,
  structured_json TEXT  NOT NULL,
  vault_path    TEXT,
  gbrain_chunk_ids TEXT,           -- JSON array
  model_used    TEXT,
  cost_usd      REAL    DEFAULT 0,
  error_text    TEXT    NULL,      -- non-null = failed
  retries       INTEGER DEFAULT 0,
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_discord_analyses_bookmark ON discord_analyses(bookmark_id);
CREATE INDEX idx_discord_analyses_created  ON discord_analyses(created_at);
```

## Error handling

| Tier | Trigger | Behavior |
|---|---|---|
| **Transient** | HTTP 429, 5xx, network timeout, Hermes circuit-open | INSERT analysis row with `error_text`, leave `analyzed_at NULL`, `retries++`; next run picks it up. Max 3 retries → tier 2 |
| **Permanent** | HTTP 400 (bad request, unsupported format), file not found, parse failure | INSERT analysis row with `error_text`, set `analyzed_at=now()` (won't retry), write minimal vault page noting the failure |
| **Catastrophic** | Hermes gateway down, SQLite locked, daily budget breached | Runner exits 1; Task Scheduler logs `Last Result: 1`; next 2-min poll retries; budget breach defers to next day with a marker row |

## Cost tracking

- Every LLM call returns `(response, usage)`.
- `usage` → cost via per-model price table.
- INSERTed into `discord_analyses.cost_usd`.
- Daily total = `SELECT SUM(cost_usd) FROM discord_analyses WHERE date(created_at)=date('now')`.
- Daily total ≥ `DEEP_ANALYZER_DAILY_USD` → runner halts for the day.

## Idempotency & concurrency

`claimed_at` column + `analyzed_at IS NULL` predicate makes the runner safe to run concurrently or after a mid-run crash. Stale claims (>10 min old) are reclaimable. No external lock file needed — SQLite handles row-level coordination.

## Audio handler — local Whisper

`faster-whisper` (GPU-accelerated CTranslate2 build of OpenAI Whisper). Default model: **`medium`** (~1.5 GB VRAM) — chosen for safe coexistence with Ollama's running embedding model on shared GPU. `large-v3` is available as a toggle via `DEEP_ANALYZER_WHISPER_MODEL=large-v3` once VRAM headroom is verified (Phase 3 includes a VRAM-check task). Beats paid OpenAI Whisper API on cost ($0/min vs $0.006/min) and on privacy (audio doesn't leave the box).

## Vault page format

Each artifact writes to `~/my-vault/Discord-Feed/YYYY-MM-DD/<bookmark_id>--<slug>.md`:

```markdown
---
date: 2026-05-20T15:42:00-05:00
discord_message_id: <id>
discord_url: https://discord.com/channels/.../...
artifact_type: image
model: gemini-2.5-flash
cost_usd: 0.0012
tags: [discord-feed, image, chart, MES]
---

# Summary
<one-paragraph summary>

# Structured
- OCR: <text>
- Detected ticker: MES
- Detected timeframe: 5m

# Salient points
- ...
- ...

# Raw
[link to original Discord message]
```

## Daily digest

At 06:00, `digest.py` reads last 24h of `discord_analyses`, ranks by priority (heuristic: trading-relevant tickers + sentiment magnitude + has-action-item flag), and writes:

- Section appended to `~/my-vault/Daily/YYYY-MM-DD.md` "Overnight feed"
- **Discord DM to Amo via Hermes** containing top-3 items + count + vault page link (no email — already noisy)
- Top 10 items + summary stats (total count, by type, total cost) in the vault page

## Testing

| Test | What it pins |
|---|---|
| `test_runner_picks_unanalyzed_rows` | SQL claim + lock semantics |
| `test_runner_respects_limit_5` | Throttle |
| `test_dispatcher_routes_by_artifact_type` | URL vs image vs audio vs PDF detection |
| `test_url_handler_extracts_x_post` | Critical — 62% of channel is X posts |
| `test_image_handler_with_mocked_gemini` | Vision call path |
| `test_audio_handler_with_short_wav` | faster-whisper integration |
| `test_pdf_handler_with_short_doc` | Text extraction path |
| `test_budget_breach_halts_run` | Cost guard |
| `test_transient_error_retries` | 429/5xx → retry |
| `test_permanent_error_writes_failure_page` | 400 → noted, not retried |
| `test_vault_path_collision_handling` | Two artifacts on same date → distinct file names |
| `test_gbrain_ingest_failure_doesnt_block_vault` | Side-effect isolation |
| `test_digest_ranks_by_priority` | Morning digest output |

Coverage target ≥ 90% on new modules. Existing Discord suite (172 tests) must remain green.

## Rollout phases

1. **Phase 0 — schema migration.** `ALTER TABLE` + new table. Reversible. Verified by `sqlite3 .schema discord_bookmarks`.
2. **Phase 1 — text handler only.** Cheapest path. Run on 10 historical rows manually. Validates LLM client, storage, vault writer, gbrain sink.
3. **Phase 2 — URL handler.** Covers 97% of historical channel volume. Run on 50 backfill rows. Inspect vault output by hand.
4. **Phase 3 — image + PDF + audio handlers.** Covers remaining attachment types.
5. **Phase 4 — scheduled task + digest.** Install `JarvisTrader_DiscordDeepAnalyzer` (every 2 min) and `JarvisTrader_DiscordDigest` (06:00 daily). Run for 48h. Monitor budget, error rate, vault page quality.
6. **Phase 5 — full backfill.** One-shot script to clear `analyzed_at` for all historical rows; runner chews through over 24-48h within budget.

## Roll-back

Each phase independently revertible. The scheduled task can be disabled via `schtasks /Change /TN JarvisTrader_DiscordDeepAnalyzer /DISABLE` without breaking the existing refresh pipeline. Schema additions are non-destructive (existing reads ignore new columns).

## Verification gates (per `rules/verification.md`)

- After Phase 4: `SELECT COUNT(*) FROM discord_analyses WHERE date(created_at)=date('now')` returns a sensible number (not 0, not 1000).
- `~/my-vault/Discord-Feed/<today>/` exists and contains markdown pages.
- Hermes `/health` shows `llm_path_healthy=true` continuously through the rollout window.
- Daily cost (`SUM(cost_usd)`) under `DEEP_ANALYZER_DAILY_USD` budget.

## Decisions locked

- **Vault path:** `~/my-vault/Discord-Feed/YYYY-MM-DD/<bookmark_id>--<slug>.md`
- **Digest delivery:** vault page + Discord DM via Hermes; no email.
- **Whisper model:** default `medium`, `large-v3` available via toggle after Phase 3 VRAM check.
- **Rollout order:** text → URL → attachments (validate pipeline at lowest LLM cost first).

## Open issues parked for future iteration

- Pre-existing Gemini `thinking_config` HTTP 400 in Hermes logs (separate ticket; doesn't block this work).
- Option C (hybrid orchestrator/agent escalation) — defer until A is shipped and we have signal on which items merit agent-level reasoning.
- Extending to additional Discord channels — dispatcher is already pluggable; out of scope for this spec.
