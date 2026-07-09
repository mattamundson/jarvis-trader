# Trading-Agents Research Backlog

_Seeded 2026-06-17 from `docs/repo-integrations/LLMQuant__awesome-trading-agents.md`._
_Source: the `LLMQuant/awesome-trading-agents` curated list (CC0), filtered to entries
that map onto an existing jarvis-trader module and add something we don't already have._

## How to read this

Same scheme as `docs/research-backlog-from-discord.md`: **relevance** (1-5, overlap with
existing modules) × **feasibility** (1-5, ready-to-mine vs. needs infra) = **priority**.
**Do not batch-implement.** Each item gets its own repo-integrator run → analysis doc →
branch → failing test → implement → verify no backtest regression → PR.

Entries already promoted to a full analysis doc are marked **[analyzed]**.

## Shortlist (ranked by priority)

| # | P | R | F | Surface | Repo | Maps to | License | Status |
|---:|---:|---:|---:|---|---|---|---|---|
| 1 | 16 | 4 | 4 | engine | [FinStep-AI/ContestTrade](https://github.com/FinStep-AI/ContestTrade) | `agents/debate.py`, `backtest/consensus.py`, `candidate_registry.py` | Apache-2.0 | **[analyzed]** → `FinStep-AI__ContestTrade.md` |
| 2 | 12 | 4 | 3 | engine | [mnemox-ai/tradememory-protocol](https://github.com/mnemox-ai/tradememory-protocol) | `learning/pattern_db.py`, `consolidator.py` | MIT | **[analyzed]** → `mnemox-ai__tradememory-protocol.md` (partial: audit-chain) |
| 3 | 12 | 4 | 3 | engine/rules | [HKUSTDial/DeepFund](https://github.com/HKUSTDial/DeepFund) | `backtest/evaluation_harness.py`, `paper_tracker.py` | MIT | **[analyzed]** → `HKUSTDial__DeepFund.md` (dedup: rule shipped) |
| 4 | 9 | 3 | 3 | engine | [ulab-uiuc/live-trade-bench](https://github.com/ulab-uiuc/live-trade-bench) | `backtest/evaluation_harness.py`, `forward_test.py` | PolyForm NC | **[analyzed]** → `ulab-uiuc__live-trade-bench.md` (defer: noncommercial) |
| 5 | 9 | 3 | 3 | skills | [marketcalls/vectorbt-backtesting-skills](https://github.com/marketcalls/vectorbt-backtesting-skills) | `.claude/skills/backtest-report`, vectorbt dep | MIT | **[analyzed]** → `marketcalls__vectorbt-backtesting-skills.md` (partial: skills only; vectorbt dep is dead) |
| 6 | 8 | 4 | 2 | ops/data | [6551Team/opennews-mcp](https://github.com/6551Team/opennews-mcp) | `agents/news_analyst.py`, `engine/data/` | MIT (shim) | **[analyzed]** → `6551Team__opennews-mcp.md` (defer: proprietary gated backend, crypto) |

## Notes per item

1. **ContestTrade** — internal two-stage contest (data-factor competition → research-proposal
   competition). Most novel pattern on the list. Full analysis written; see its doc for the
   integration plan and red flags.
2. **tradememory-protocol** — episodic trade-memory MCP (17 tools, 35+ REST endpoints).
   Evaluate schema/retrieval API against our existing `pattern_db` + `consolidator`; likely a
   refinement, not a replacement. License must be confirmed before any code is copied.
3. **DeepFund** — multi-agent fund benchmark with leaderboard; source of the "Time Travel is
   Cheating" point-in-time discipline (arXiv 2505.11065) already cited in `.claude/rules/testing.md`.
   Mine the benchmark methodology, not the A-share data plumbing.
4. **live-trade-bench** — UIUC live-market evaluation harness. Compare methodology against our
   `forward_test.py` / `paper_tracker.py`; useful for honest live scoring, not historical.
5. **vectorbt-backtesting-skills** — vectorbt is already a dependency (`engine/requirements.txt`).
   Harvest optimization/comparison/stats templates into the `backtest-report` skill; do not
   bulk-import.
6. **opennews-mcp** — 84+ news sources, AI impact-scoring, WebSocket streaming. Deferred: we
   already have working news ingestion; only worth it if `news_analyst` needs broader coverage.

## Explicitly excluded (dedup — already covered)

- `paperswithbacktest/pwb-alphaevolve` → `engine/strategies/discovery_loop.py` + `llm_sandbox.py`
- `TauricResearch/TradingAgents` and all CN/A-share/crypto forks → our `engine/agents/pipeline.py`
- `virattt/ai-hedge-fund` → same multi-agent architecture (already in discord backlog #1)
- IBKR MCPs (`rcontesti/IB_MCP`, `code-rabi/interactive-brokers-mcp`) → Tier 3 broker surface;
  needs explicit confirmation + `[safety-review]`, never a silent swap of the IB Gateway path.
