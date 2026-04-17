---
repo: devwhodevs/engraph
url: https://github.com/devwhodevs/engraph
stars: 111
language: Rust
license: MIT
archived: false
pushed_at: 2026-04-10T19:55:36Z
analyzed_at: 2026-04-17
recommendation: partial-integrate
surfaces_with_value: [Engine code, Project skills, Dash board, Ops/messaging]
---

# devwhodevs/engraph

## Core value proposition

engraph turns markdown vaults (Obsidian, notes directories) into a searchable knowledge graph with semantic embeddings, full-text search, graph traversal, and temporal awareness. It exposes a 25-tool MCP server and optional HTTP REST API that any AI agent can query to read, search, create, and edit notes locally without cloud APIs. Built in Rust with local llama.cpp inference, Metal GPU acceleration on macOS, and SQLite vector storage.

## Surface analysis

### 1. Engine code
**partial-integrate** — engraph's hybrid 5-lane search orchestrator (semantic KNN + BM25 + graph expansion + cross-encoder reranking + temporal scoring via Reciprocal Rank Fusion) solves a specific class of retrieval problem that JARVIS does not currently address: semantic search across markdown documentation and historical context. Potential integration targets: (a) `engine/llm/context_manager.py` — adopt engraph's RRF fusion strategy to blend multiple signal sources (technical + sentiment + regime) instead of sequential weighting; (b) `engine/agents/debate.py` — use engraph as a backing store for debate reasoning history and precedent lookup (`"when did we encounter a similar low-confidence setup"` queries); (c) cross-encoder reranker in `engine/analytics/ic_ensemble.py` — engraph's pattern for post-hoc relevance scoring via lightweight LLM could improve signal ranking. **However:** JARVIS currently has no Obsidian integration at build time, so engraph's core use case (vaulting `C:/Users/mattm/second-brain/`) requires manual wiring and decision on whether to make vault search a first-class feature.

### 2. Project rules
**dedup-rules** — engraph's philosophy of "knowledge isn't flat, connections matter" aligns with `.claude/rules/token-efficiency.md` (parallelize smart searches, avoid redundant reads) and `.claude/rules/workflow.md` (cross-reference before building), but no new rules emerge that override existing discipline.

### 3. Project skills
**integrate-now** — Create `.claude/skills/engraph-search/` with a skill that wraps engraph's MCP 25 tools (search, read, context bundles, vault health, write operations) for JARVIS's second-brain vault (`C:/Users/mattm/second-brain/`). **Concrete plan:** (a) Point engraph index at the vault directory, configure via `engraph configure --add-api-key`; (b) Wire `.claude/mcpServers.engraph` in settings.json with `command: "engraph serve --http"`; (c) Create a skill file that documents intent-based search patterns: conceptual queries (boost semantic lane), operational queries (boost keyword lane), person/project lookups (via graph expansion). Effort is minimal since engraph exposes 25 MCP tools directly. **Verification gate:** Skill must demonstrate a query like `"What is our bias assessment for MCL?"` returning relevant notes from the vault with RRF scores explained.

### 4. Slash commands
**defer** — Once the skill is live (surface 3), slash commands like `/vault-search`, `/vault-context`, `/vault-health` can be built to wrap skill calls. No blocker; depends on skill wiring.

### 5. Subagents
**no-fit** — engraph itself is a retrieval engine, not an agent. JARVIS agents already exist (`debate.py`, `fundamental_analyst.py`, `trader.py`). engraph would be a *data source* for those agents, not a new agent itself.

### 6. Docs
**dedup-docs** — engraph's HTTP API + MCP documentation is comprehensive in its README. Add a runbook at `docs/runbooks/engraph-vault-setup.md` covering: vault directory layout expectations (PARA/flat/custom), first-time indexing, MCP registration in settings.json, example queries. Reference: `https://github.com/devwhodevs/engraph#quick-start`.

### 7. Dev tooling
**no-fit** — engraph is a precompiled Rust binary. No CI/CD, pre-commit hooks, PM2 config, or build step integration needed beyond binary install (Homebrew or cargo).

### 8. Dashboard
**partial-integrate** — engraph's vault search results could surface in a new dashboard widget showing (a) recent vault edits (file list + timestamps), (b) top-cited notes in debates, (c) vault health summary (orphans, broken wikilinks). Requires a new React component consuming the HTTP REST API. **File:** `dashboard/components/VaultSearchWidget.tsx` — simple form + results table showing note name, excerpt, RRF score, intent classification. **Verification gate:** Widget must render without errors and fetch at least one vault entry via HTTP.

### 9. Ops / messaging
**no-fit** — engraph has no alerting or cron integration. It is a passive query layer, not an active notifier.

## Integration plan

**Phase 1 (Immediate, S effort):**
1. Install engraph binary: `brew install devwhodevs/tap/engraph` (or pre-built binary for platform).
2. Index the vault: `engraph index C:/Users/mattm/second-brain/` — one-time run, ~5 min including model download.
3. Configure API key: `engraph configure --add-api-key` → save key to `engine/.env` as `ENGRAPH_API_KEY`.
4. Add MCP server to `.claude/settings.json`:
   ```json
   {
     "mcpServers": {
       "engraph": {
         "command": "engraph",
         "args": ["serve", "--http", "--port", "3031"]
       }
     }
   }
   ```
5. Verify: `curl -H "Authorization: Bearer <API_KEY>" http://localhost:3031/api/vault-map` returns vault overview.

**Phase 2 (Follow-up, M effort):**
1. Create skill `.claude/skills/engraph-search/SKILL.md` (300-400 lines):
   - Document 25 MCP tools + HTTP equivalents.
   - Provide intent classification logic (conceptual/operational/person/health → lane weights).
   - Example queries for each intent type.
2. Add runbook `docs/runbooks/engraph-vault-setup.md` covering installation, indexing, and troubleshooting.
3. Create `dashboard/components/VaultSearchWidget.tsx`:
   - Form input for search query.
   - Results table (note name, excerpt, score, intent).
   - Link to open note in Obsidian via `obsidian://open?...` URI scheme.

**Phase 3 (Optional, L effort):**
1. Wire engraph search into `engine/agents/debate.py` — add a precedent-lookup call when debate score is inconclusive (|score - threshold| <= 0.05). Example: `engraph search "MCL low-confidence setups"` → retrieve historical debate logs, inject as context.
2. Add cross-encoder reranking to `engine/analytics/ic_ensemble.py` using engraph's reranker (if enabled via `--enable-intelligence`).

## License & attribution

**License:** MIT. engraph can be freely integrated; attribute in `.claude/skills/engraph-search/SKILL.md` header comment:
```
Engraph MCP Server & HTTP API integration.
Source: https://github.com/devwhodevs/engraph (MIT)
Adapted for jarvis-trader vault search.
```

## Effort estimate

- **Phase 1 (Binary install + indexing):** S (30 min, one-time).
- **Phase 2 (Skill + runbook + widget):** M (4-6 hr, async).
- **Phase 3 (Agent integration):** L (8-12 hr, requires debate.py refactor + testing).
- **Total for partial-integrate (Phases 1-2):** M.

## Red flags

1. **engraph is young** — Created 2026-03-19, 111 stars, 8 forks, last push 2026-04-10. Not yet battle-tested in production systems. Consider pinning a specific release version (not `main` branch) if integrating.
2. **Obsidian API integration is optional** — engraph can auto-detect running Obsidian and delegate operations via circuit breaker, but this is graceful fallback, not required. If Obsidian is not running, engraph still works via file watching.
3. **No Windows native binary yet** — Repository shows Homebrew + prebuilt x86_64 Linux, arm64 macOS only. Compiling from source on Windows (Rust toolchain) requires CMake for llama.cpp. Workaround: Run engraph in WSL2 Ubuntu, expose HTTP API on port 3031, call from Windows dashboard. **Decision needed:** Is WSL integration acceptable, or should Windows binary support be a blocker?
4. **Vault structure assumptions** — engraph's PARA migration and semantic similarity (for folder placement) assume a well-structured vault. Matt's `C:/Users/mattm/second-brain/` is documented as ~60 wiki pages with clean Git history, so this is low risk, but verify layout before indexing.
5. **MCP tool count (25) vs. REST endpoints (26)** — Slight API surface asymmetry (MCP has `context who/project/vault-map`, REST has `/api/identity`). Skill must document both paths to avoid user confusion.

## Summary

**engraph is valuable for JARVIS as a knowledge graph retrieval layer**, unlocking semantic search across Matt's second-brain vault and enabling agents to reference historical reasoning, precedents, and operational context. Phase 1 (binary + indexing) is low friction; Phase 2 (skill + widget + runbook) unlocks immediate value. Phase 3 (agent integration) is deferred but promising for improving debate reasoning and cross-validation. **Main blocker:** Windows binary — if WSL2 integration is unacceptable, this becomes a `defer`. **Recommendation:** Start with Phase 1-2, verify vault indexing works on this machine, then revisit agent integration in a follow-up session.
