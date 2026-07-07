---
repo: AI4Finance-Foundation/FinGPT
url: https://github.com/AI4Finance-Foundation/FinGPT
stars: 19518
language: Jupyter Notebook
license: MIT
archived: false
pushed_at: 2026-04-10
analyzed_at: 2026-04-17
recommendation: defer
surfaces_with_value: [engine-code]
---

# AI4Finance-Foundation/FinGPT

## Core value proposition

FinGPT is an open-source framework for fine-tuning general-purpose LLMs (Llama2, ChatGLM, Falcon, BLOOM) on financial NLP tasks using LoRA and reinforcement learning from human feedback (RLHF). It ships pre-trained sentiment analysis models, multi-task instruction-tuned LLMs, and a forecaster demo that predicts next-week stock moves from news + fundamentals. Primary assets are HuggingFace model weights and benchmark datasets (sentiment, headline classification, NER, relation extraction).

## Surface analysis

### 1. Engine code
**partial-integrate** — FinGPT's sentiment analysis models (FinGPT v3.3: llama2-13b LoRA) overlap significantly with existing `engine/agents/news_analyst.py` and `engine/discord/sentiment_provider.py`, which already synthesize sentiment via Claude Sonnet LLM calls. FinGPT's forecaster demo (predicts weekly price direction from news + fundamentals) could augment `engine/agents/bull_researcher.py` and `engine/agents/bear_researcher.py` with a learned confidence multiplier or prior probability. Blocker: forecaster is a Jupyter notebook with hard-coded DOW30 ticker list; refactor required to work on arbitrary futures (MES, MNQ, MCL). Effort: M-L to adapt forecaster to `engine/agents/price_direction_predictor.py` (needs retraining on CME Globex data or fine-tuning FinGPT v3.3 on historical futures moves + news archive from `discord_corey_commentary` table).

### 2. Project rules
**no-fit** — FinGPT is a model-training framework; no governance or safety-critical rules to upstream.

### 3. Project skills
**no-fit** — FinGPT is research code; no reusable workflows for `.claude/skills/`.

### 4. Slash commands
**no-fit** — No command patterns in FinGPT repo.

### 5. Subagents
**no-fit** — No subagent patterns in FinGPT repo.

### 6. Docs
**dedup-docs** — FinGPT's benchmark results and model cards are documented in HuggingFace model repos (`FinGPT/fingpt-sentiment_llama2-13b_lora`, `FinGPT/fingpt-forecaster_dow30_llama2-7b_lora`). Jarvis-trader already references FinGPT in `tradingview-mcp/RESEARCH.md` as background literature; no new runbooks needed.

### 7. Dev tooling
**no-fit** — FinGPT's training scripts (8-bit, QLoRA, full fine-tuning) are stand-alone Jupyter notebooks; no CI/CD patterns or PM2 hooks to port.

### 8. Dashboard
**no-fit** — FinGPT ships a HuggingFace Spaces web UI for the forecaster demo; no React/Tailwind components to integrate into `dashboard/`.

### 9. Ops / messaging
**no-fit** — FinGPT has no cron jobs, notification patterns, or messaging integrations.

## Integration plan

**Surface 1 (Engine code) — price direction forecaster**

1. Evaluate feasibility of retraining FinGPT v3.3 forecaster on futures data:
   - Acquire 12-24 months of historical news (Finnhub API, SEC filings, macro data) + corresponding weekly price moves (MES, MNQ, MCL candles from jarvis_trader.db)
   - Label training set: +1 (price up next week), 0 (flat), -1 (price down next week)
   - Fine-tune FinGPT v3.3 (llama2-13b LoRA) on this dataset using the repo's training harness (~6-12 hours on RTX 3090, ~$10-20 cost)
   - Validate on hold-out test set; benchmark weighted F1 vs. Sonnet-only baseline

2. If validation passes (F1 > 0.75 on hold-out):
   - Integrate trained model as optional `engine/agents/price_direction_predictor.py`
   - Callable from `engine/agents/debate.py` in the tiebreak escalation path (when abs(score) < 0.05): LLM returns prior probability (e.g., 0.62 = 62% chance of up), Opus refines with low-confidence trades
   - Add `/post-trade-analysis` route to calibrate model performance against realized outcomes monthly

3. If validation fails or training data insufficient:
   - Defer as low-priority experiment; mark for post-paper-trading review
   - Existing Sonnet-based agents (Bull/Bear Researcher + Debate) are adequate for current paper trading

## License & attribution

MIT — freely integrable. If shipping code that imports FinGPT models (e.g., via Hugging Face `transformers` library), attribute in file header and CLAUDE.md acknowledgments section.

## Effort estimate

- **Retraining forecaster**: L (1-3 days) — requires historical news + label generation, training loop, validation
- **Minimal integration (reference models in docs only)**: S (<2 hours)
- **Full integration (trained price direction predictor)**: L-XL (2-4 days including data prep + retraining + testing)

## Red flags

1. **No live price forecasting baseline in repo** — FinGPT's forecaster demo uses a fixed DOW30 training set; unknown generalization to Globex futures (MES, MNQ) or different timeframes (5m, 1h, daily vs. weekly). Will require data collection + retraining.

2. **Sentiment overlap** — Jarvis-trader's `news_analyst.py` already achieves strong sentiment signals via Claude Sonnet prompting. FinGPT's sentiment models are trained LLMs, not prompting-based. Switching to FinGPT v3.3 could reduce cost (local inference vs. Claude API calls) but adds operational complexity (GPU requirement, model versioning, drift monitoring).

3. **Model size risk** — FinGPT v3.3 is 13B parameters (llama2-13b). Local inference requires GPU or cloud. Jarvis-trader currently runs on CPU-only Windows 11 host with no GPU support. Would require either (a) cloud fine-tuning + API deployment (AWS SageMaker, Replicate, Together AI), or (b) quantization to 8-bit/int4 for CPU inference (supported by FinGPT's QLoRA training, but slower).

4. **Training data quality** — Building a high-fidelity label set (news + next-week realized price direction) is non-trivial. Finnhub API rate-limited for free tier; SEC EDGAR parsing is error-prone; historical futures news archives are sparse compared to equity news.

## Decision and next steps

**Recommendation: DEFER** — FinGPT has genuine value on Surface 1 (price direction forecaster could improve Debate tiebreaks), but the blocker is data + infrastructure. Current sentiment/forecasting via Claude Sonnet + Bull/Bear Researchers is adequate for paper trading. Flag this as a post-paper-trading optimization if:

- Sharpe / PF numbers plateau and additional edge is needed
- GPU infrastructure becomes available
- Historical news + label dataset can be assembled with <4 hours of effort

For now, **keep FinGPT in research-backlog for future consideration**; do not block current production pipeline.
