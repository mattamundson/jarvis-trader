# Kronos Classifier + Research Agent — Operations Runbook

Commits shipped: `bbf3b4c` (Kronos stub), `b0cc58c` (ResearchAgent stub),
`7d3964b` (pipeline wiring), `518eb26` (tuner wiring).

---

## 1. Overview

**Kronos** is the 7th analyst in the 5-stage debate pipeline. It slots alongside
`PatternVisionAnalyst` inside `_run_analysts()` and emits the same
`VisionClassification` shape so the debate stack requires no new protocol branch.
It is wired in `pipeline.py` via `_call_agent_analyze_kronos` and runs concurrently
with the other six analysts inside `asyncio.gather`. With `confidence=0.0` it
contributes zero weight to the debate outcome — identical to a graceful skip.

**ResearchAgent** is an off-pipeline strategy hypothesis generator. It is not called
during a normal pipeline run. It lives in `StrategyTuner.generate_hypothesis()` and
is expected to be triggered after backtest completion or on a scheduled interval.
It returns a fully-specified `StrategyHypothesis` that downstream code can pass to
gate-v2 for scoring before any trade routing is considered.

Both components default off. Neither touches `engine/risk/` or `engine/config.py`.

---

## 2. Files

| Role | Path |
|------|------|
| Kronos classifier | `engine/agents/kronos_classifier.py` (commit `bbf3b4c`) |
| ResearchAgent | `engine/agents/research_agent.py` (commit `b0cc58c`) |
| Pipeline wiring | `engine/agents/pipeline.py` (commit `7d3964b`) |
| Tuner wiring | `engine/learning/_experimental/strategy_tuner.py` (commit `518eb26`) |
| Env template | `engine/.env.example` (commit `6395081`) |
| Tests | `engine/tests/test_kronos_classifier.py` |
| Tests | `engine/tests/test_research_agent.py` |
| Tests | `engine/tests/test_strategy_tuner_research_agent.py` |

---

## 3. Env flags

Both flags live in `engine/.env`. Neither is required in `.env` for the engine to
start — the helpers default to disabled when the key is absent.

```ini
# Kronos financial foundation model — set to 1 to activate
ENABLE_KRONOS=0

# ResearchAgent strategy hypothesis generator — set to 1 to activate
ENABLE_RESEARCH_AGENT=0
```

The guard functions are strict: any value other than the exact string `"1"` is
treated as disabled. An accidental `ENABLE_KRONOS=true` or `ENABLE_KRONOS=yes`
stays off.

---

## 4. Stub behavior (current state)

**Kronos (disabled — `ENABLE_KRONOS` absent or `0`):**
Pipeline initialises `self._kronos = None`. `_call_agent_analyze_kronos` returns
`{"signal": 0.0, "confidence": 0.0, "summary": "Kronos disabled"}` immediately
without acquiring market data. Zero overhead per pipeline run.

**Kronos (flag `1` but model not yet wired):**
`classify()` logs a warning and returns `VisionClassification(signal=0.0,
confidence=0.0, reasoning="stub — Kronos not yet wired")`. The debate stack
receives `confidence=0.0` and discards the vote — no directional influence.

**ResearchAgent (disabled — `ENABLE_RESEARCH_AGENT` absent or `0`):**
`StrategyTuner.generate_hypothesis()` returns `None` after a single debug-level
log line. Callers must check for `None` before consuming the result.

**ResearchAgent (flag `1` but LLM not yet wired):**
`propose()` logs a warning and returns the hardcoded MES mean-reversion
`StrategyHypothesis`. The hypothesis has `confidence=0.0` so gate-v2 will
score it from scratch on first backtest run.

---

## 5. Pre-flight before going live

### Kronos

- [ ] HF Inference API token obtained and stored in `engine/.env` as
      `HF_API_TOKEN=...` (read via `os.environ["HF_API_TOKEN"]` in the real
      `classify()` body — do not hardcode).
- [ ] Kronos paper input schema confirmed (arxiv 2509.09995): bar count per
      request, feature encoding (`open/high/low/close/volume` vs normalized),
      expected JSON response shape (`signal`, `confidence`, `reasoning` keys or
      different).
- [ ] Model endpoint URL pinned in `engine/.env` as `KRONOS_ENDPOINT=...` (or
      equivalent) — avoids re-deploying when HF model ID drifts.
- [ ] Rate-limit budget confirmed: HF Inference free tier caps at 1,000 calls/day.
      Estimate pipeline call frequency (symbols × runs/hour) and confirm it fits
      before enabling.
- [ ] Baseline pipeline runs captured: record `analyst_reports.kronos.confidence`
      for 24h with flag off (should be `0.0` throughout) to establish the A/B
      baseline before flipping on.

### ResearchAgent

- [ ] LLM cost budget gates configured: default to haiku tier in
      `advisor_client.py` call; escalate to Sonnet only on hypotheses that
      survive an initial cheap pre-screen.
- [ ] Gate-v2 evaluation enabled on returned `StrategyHypothesis` objects —
      every hypothesis must pass `pf_ci_lower >= 1.10`, `p_edge >= 0.95`,
      `mc_95th_dd <= 5%`, `dsr >= 0.10` before any routing consideration.
- [ ] Output cap implemented in the caller: no more than 1 hypothesis per
      symbol per 24-hour window to prevent runaway LLM spend.
- [ ] Archive path for rejected hypotheses decided (e.g. `engine/data/hypotheses/rejected/`)
      so gate-v2 failures are logged and reviewable.

---

## 6. How to flip live — Kronos

1. **Implement the real API call.** Edit `engine/agents/kronos_classifier.py`,
   `KronosClassifier.classify()`. Replace `return self._stub_verdict()` with
   a real `_call_kronos_api(bars)` function. The NEXT STEPS block at the bottom
   of the file is the authoritative implementation checklist.

2. **Add credentials to `engine/.env`:**
   ```ini
   ENABLE_KRONOS=1
   HF_API_TOKEN=hf_...
   KRONOS_ENDPOINT=https://api-inference.huggingface.co/models/<model-id>
   ```

3. **Restart the engine:**
   ```powershell
   .\restart_engine.ps1
   ```
   Wait for `/health` to return `status=ok` (steady-state ~229s).

4. **Verify Kronos is active.** Issue a pipeline run for one symbol and confirm
   the response includes a non-zero `analyst_reports.kronos.confidence`:
   ```powershell
   Invoke-RestMethod http://127.0.0.1:8010/pipeline/run `
     -Method POST `
     -Headers @{"X-API-Key"="<key>"; "Content-Type"="application/json"} `
     -Body '{"symbol":"MES"}' | ConvertTo-Json -Depth 6
   ```
   Look for `"kronos": {"signal": <non-zero>, "confidence": <non-zero>, ...}`.

5. **A/B comparison.** Collect 24h of pipeline verdicts. Compare
   `analyst_reports.kronos.confidence` distribution and flag any directional
   drift in overall `decision` outcomes vs the pre-Kronos baseline.

---

## 7. How to flip live — ResearchAgent

1. **Implement the real LLM call.** Edit `engine/agents/research_agent.py`,
   `ResearchAgent.propose()`. Replace the hardcoded `_HARDCODED_MES_MEAN_REV`
   return with a real call via `agents/advisor_client.py`. The `StrategyHypothesis`
   Pydantic model is the output contract — the LLM must return JSON conforming
   to it.

2. **Wire the trigger.** In `engine/learning/_experimental/strategy_tuner.py`,
   confirm `generate_hypothesis()` is called after each completed backtest run.
   Alternatively add a scheduled endpoint that fires once per symbol per day.

3. **Add the flag to `engine/.env`:**
   ```ini
   ENABLE_RESEARCH_AGENT=1
   ```

4. **Restart the engine:**
   ```powershell
   .\restart_engine.ps1
   ```

5. **Validate the rejection path first.** Trigger `generate_hypothesis("MES")`
   manually and confirm the returned hypothesis is passed to gate-v2 and that a
   failing gate produces a rejection-with-reason log entry before any approval
   path is exercised. Do not let any hypothesis reach routing until this is
   confirmed end-to-end.

6. **Monitor `engine/logs/`** for `ResearchAgent.propose` log messages and
   hypothesis generation counts. Watch for unexpected volume (indicates caller
   loop misfiring).

---

## 8. Rollback

Both components are flag-gated with zero persistent state in the stub phase.

```ini
# engine/.env — revert either or both
ENABLE_KRONOS=0
ENABLE_RESEARCH_AGENT=0
```

```powershell
.\restart_engine.ps1
```

Kronos reverts to a `None` handle in pipeline; the `analyst_reports.kronos`
key returns `{"signal": 0.0, "confidence": 0.0, "summary": "Kronos disabled"}`.
ResearchAgent's `generate_hypothesis` returns `None`. No data to clean up.

---

## 9. Test commands

```powershell
# Kronos classifier unit tests
cd engine && .venv\Scripts\python -m pytest tests/test_kronos_classifier.py -v

# ResearchAgent unit tests
cd engine && .venv\Scripts\python -m pytest tests/test_research_agent.py -v

# StrategyTuner + ResearchAgent integration tests
cd engine && .venv\Scripts\python -m pytest tests/test_strategy_tuner_research_agent.py -v

# All three together
cd engine && .venv\Scripts\python -m pytest `
  tests/test_kronos_classifier.py `
  tests/test_research_agent.py `
  tests/test_strategy_tuner_research_agent.py -v

# Full suite (verify no regressions)
cd engine && .venv\Scripts\python -m pytest tests/ -m "not slow" -v
```

---

## 10. Risks and known issues

**Kronos input shape mismatch.** The stub accepts `list[dict]` with keys
`open/high/low/close/volume`. The real Kronos model paper (arxiv 2509.09995) may
expect normalized values, a different bar count, or a flat array encoding. Do not
wire the API call until the exact input contract is confirmed from the paper.
Passing mismatched input will produce silently wrong outputs, not an error.

**ResearchAgent propose() called with flag off.** The current stub calls
`logger.warning(...)` and returns the hardcoded hypothesis even when
`ENABLE_RESEARCH_AGENT` is `0`. This is intentional for testability but means
any caller that does not gate on `is_research_agent_enabled()` before calling
`propose()` will generate log spam in production. Callers in
`strategy_tuner.generate_hypothesis()` already gate correctly — verify any new
call site does the same.

**GPU not available on this machine.** Kronos must use the HF Inference API for
inference. Do not attempt to load the model weights locally via `transformers` or
`torch` — this machine has no GPU and the load would block the event loop.

**No rate-limit handling in stub.** The stub never calls HF so there is no
rate-limit path. The real `classify()` implementation must handle 429 responses
from HF Inference gracefully — return `_stub_verdict()` on rate-limit so the
pipeline degrades to neutral rather than raising.

---

## 11. Related vault docs

- `[[repo-kronos-financial-foundation-model]]` — integration card for the Kronos
  paper and model endpoints, filed in second-brain during the repo audit.
- `[[repo-quantagent-research-agent]]` — integration card for the QuantAgent
  ResearchAgent paper schema.

---

## 12. Related runbooks

- [HEALTH_API_CONTRACT.md](HEALTH_API_CONTRACT.md) — `/health` endpoint fields
  and pass criteria; use to verify pipeline is healthy after flag flip.
- `QUANTSTATS_TEARSHEET_RUNBOOK.md` — gate-v2 metric definitions; reference for
  the ResearchAgent hypothesis scoring thresholds.
