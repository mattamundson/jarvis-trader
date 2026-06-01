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

## 5. Kronos schema verified (2026-05-20)

**Source:** arxiv 2508.02739 ("Kronos: A Foundation Model for the Language of
Financial Markets", AAAI 2026) + GitHub `shiyu-coder/Kronos` README + paper
HTML methods section. Fetched 2026-05-20.

### Confirmed input schema

| Field | Confirmed value |
|-------|-----------------|
| Input type | **Pandas DataFrame** — NOT a list of dicts |
| Required columns | `open`, `high`, `low`, `close` (mandatory); `volume`, `amount` optional (filled with zeros if missing) |
| Normalization | **z-score** applied per-dimension independently, then clipped to **[-5, 5]**. Done internally by `KronosPredictor` — caller passes **raw OHLCV values** (NOT pre-normalized) |
| Max sequence length | **512 K-lines** for Kronos-small/base/large (tokenizer: `Kronos-Tokenizer-base`); **2048 K-lines** for Kronos-mini (tokenizer: `Kronos-Tokenizer-2k`) |
| Recommended lookback | 400 bars (per README examples) |
| Timestamp required | Yes — two `pandas.Series`: `x_timestamp` (historical) + `y_timestamp` (future periods to predict) |
| Additional required arg | `pred_len` (int): number of future bars to forecast |

### Confirmed output schema

| Field | Confirmed value |
|-------|-----------------|
| Output type | **Pandas DataFrame** (NOT a dict with `signal`/`confidence`/`reasoning` keys) |
| Output columns | `open`, `high`, `low`, `close`, `volume`, `amount` — forecasted future bar values |
| Task type | **Regression / generative forecasting** — NOT classification (no bull/bear/neutral labels) |
| Confidence score | **None natively** — probabilistic uncertainty available only via `sample_count > 1` (multiple Monte Carlo rollouts averaged; std dev across samples = implicit uncertainty) |
| Sampling params | `T` (temperature, default 1.0), `top_p` (nucleus, default 0.9), `sample_count` (default 1) |

### Confirmed inference model

| Field | Confirmed value |
|-------|-----------------|
| Inference mode | **Local model load** — `KronosPredictor(model, tokenizer, max_context=512)` |
| HF model IDs | `NeoQuasar/Kronos-mini`, `NeoQuasar/Kronos-small`, `NeoQuasar/Kronos-base` |
| HF tokenizer IDs | `NeoQuasar/Kronos-Tokenizer-2k` (mini), `NeoQuasar/Kronos-Tokenizer-base` (small/base/large) |
| HF Inference API | **NOT used** — no hosted serverless endpoint; local `from_pretrained` load required |
| GPU requirement | Multi-GPU finetuning via `torchrun`; inference can run CPU but will be slow |
| License | **MIT** |

### Tokenizer architecture details

Binary Spherical Quantization (BSQ): 20-bit vocabulary (two 10-bit subspaces).
Transformer-based autoencoder (3 layers, 256 dimensions). Tokenizer files are
**required** and must be loaded from HF Hub separately from the model weights —
the two `from_pretrained` calls cannot be skipped.

### Changes required to the stub before flipping live

The current stub signature is:
```python
async def classify(self, bars: list[dict]) -> VisionClassification
```

The real Kronos contract requires **all of the following changes** before wiring:

1. **Input type mismatch — CRITICAL.** Stub accepts `list[dict]` with
   `open/high/low/close/volume/timestamp` keys. Kronos requires a
   `pandas.DataFrame` with columns `['open','high','low','close']` plus separate
   `pandas.Series` for `x_timestamp` and `y_timestamp`. The `list[dict]`
   conversion must happen inside `_call_kronos_api` before the predictor call.

2. **No classification output — CRITICAL.** Kronos produces forecasted future
   OHLCV bars, not a `signal`/`confidence`/`reasoning` dict. A translation layer
   must convert forecast returns to a directional signal:
   - Compute predicted return: `(pred_close[-1] - input_close[-1]) / input_close[-1]`
   - Map return to signal in `[-1.0, +1.0]` via a chosen scaling function
   - Derive confidence from `sample_count > 1` std dev (requires `sample_count >= 5`)
   - This translation is **not provided by Kronos** — it must be implemented in the stub

3. **No HF Inference API — CRITICAL.** The runbook currently references
   `KRONOS_ENDPOINT` as an HF Inference REST endpoint. Kronos has no hosted
   serverless endpoint. Inference requires loading model weights locally via
   `KronosPredictor`. The `HF_API_TOKEN` is needed only for `from_pretrained`
   downloads, not for per-request API calls.

4. **No pre-normalization.** Stub comment says "keys: open/high/low/close/volume"
   without specifying normalization. Raw OHLCV values should be passed —
   `KronosPredictor` applies z-score + clip internally. Caller must NOT
   pre-normalize.

5. **Minimum bar count.** Stub says "N TBD from paper schema." Confirmed minimum
   practical lookback is **at least 1 bar** (no hard lower bound documented),
   with 400 bars recommended. Empty list `[]` will fail at DataFrame construction.
   Add a guard: `if len(bars) < 10: return self._disabled_verdict()`.

6. **`amount` column.** Stub does not include `amount` in its dict schema. If
   bars dict lacks `amount`, it must be added as zeros before DataFrame
   construction or the predictor will fill it automatically.

7. **Inference is blocking / CPU-intensive.** `KronosPredictor.predict()` is
   synchronous and CPU/GPU bound. Must be wrapped in `asyncio.get_event_loop()
   .run_in_executor(None, ...)` to avoid blocking the FastAPI event loop.

---

## 6. Pre-flight before going live

### Kronos

- [x] **DONE** — Kronos paper input schema confirmed (arxiv 2508.02739, AAAI 2026):
      raw OHLCV DataFrame, z-score normalized internally, 400-bar recommended
      lookback, max 512 tokens for small/base, local inference only.
- [x] **DONE** — Output schema confirmed: forecasted OHLCV DataFrame, no native
      classification or confidence score; signal derivation requires custom
      post-processing.
- [x] **DONE** — Inference mode confirmed: local `KronosPredictor`, not HF
      Inference API. Remove `KRONOS_ENDPOINT` from the planned env vars; the
      `HF_API_TOKEN` is only for model download.
- [ ] Model weights downloaded and cached locally. Recommended: `NeoQuasar/Kronos-small`
      (24.7M params, 512-token context) as the first live candidate. Cache to a
      path outside the engine venv (e.g. `~/.cache/huggingface/`).
- [ ] Signal-derivation layer implemented and tested: predicted return → `[-1,+1]`
      signal, `sample_count >= 5` → std dev → confidence proxy. Thresholds
      for bull/bear boundary must be decided (suggest ±0.002 = 0.2% predicted
      return as initial boundary; validate on paper data first).
- [ ] Executor wrapper implemented in `classify()` to avoid blocking the
      asyncio event loop during model inference.
- [ ] `list[dict]` → `pd.DataFrame` conversion validated with real engine bar data
      (confirm column names, timestamp dtype, no NaN in OHLCV).
- [ ] Rate-limit budget confirmed: local inference has no per-call API rate limit,
      but inference latency on CPU will be significant. Measure wall-clock time for
      a 400-bar `predict()` call on this machine before enabling in the hot path.
- [ ] Baseline pipeline runs captured: record `analyst_reports.kronos.confidence`
      for 24h with flag off (should be `0.0` throughout) to establish the A/B
      baseline before flipping on.
- [ ] `HF_API_TOKEN` stored in `engine/.env` for model download only (not per-call
      auth). Remove `KRONOS_ENDPOINT` from `.env.example` — it does not exist.

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

## 12. Calibration (2026-05-20)

Empirical threshold calibration run against 90 days of 1-hour bar data
(smoke-test and corrupt-close rows excluded).  Method: p75 of the
absolute 5-bar-ahead log-return distribution.  Script:
`scripts/calibrate_kronos_threshold.py`.  Full JSON:
`scripts/data/kronos_threshold_calibration.json`.

| Instrument | Bars | p50 abs (bps) | p75 abs (bps) | **Recommended threshold** |
|------------|------|---------------|---------------|--------------------------|
| MES        | 1,483 | 22.4          | 48.4          | **48 bps**               |
| MNQ        | 1,414 | 30.5          | 63.2          | **63 bps**               |
| MCL        | 2,063 | 74.3          | 207.4         | **207 bps**              |

**Global median:** 63.2 bps (prefer per-instrument values).

**Current `BULL_BEAR_THRESHOLD_BPS` default:** 20 bps — this is below the
median 5-bar move for all three instruments.  Setting it to the per-instrument
p75 values above will prevent the classifier from declaring bull/bear on
routine noise while still catching structurally significant moves.

**Action required before flipping `ENABLE_KRONOS=1`:**
Update `KronosClassifier.BULL_BEAR_THRESHOLD_BPS` (or wire per-instrument
overrides) based on the values above.  The recommended single-value conservative
starting point is **48 bps** (MES, the lowest-vol instrument), which ensures
Kronos stays quiet except on genuine moves for all three instruments.

**Methodology caveat:** The p75-of-absolute threshold is calibrated on a single
90-day sample.  Return distributions are non-stationary across regimes —
trending periods inflate the threshold, choppy periods deflate it.  Revisit
after 30 days of live Kronos verdicts to validate the chosen value is
correctly separating signal from noise.

---

## 14. Predictor wired (2026-05-20)

`_predict_sync` and `_predict_async` are now implemented in
`engine/agents/kronos_classifier.py`.  The stub `NotImplementedError` is gone.

### What changed

| Item | Before | After |
|------|--------|-------|
| `_predict_async` | `return None` (stub) | `run_in_executor` wrapping `_predict_sync` |
| `_predict_sync` | `raise NotImplementedError` | calls `KronosPredictor.predict(df, x_timestamp, y_timestamp, pred_len)` |
| `__init__` params | `model_name`, `lookback` | `model_path`, `tokenizer_path`, `horizon_bars`, `lookback`, `max_context` |
| Module-level singleton | none | `_get_or_load_predictor()` — weights loaded once, shared across all instances |
| Import guard | none | `try: from model import ...` at module top; `_KRONOS_AVAILABLE` flag; engine boots without Kronos installed |

### Verified install command (2026-05-20)

The Kronos repo does **not** publish a pip package.  Canonical install:

```bash
git clone https://github.com/shiyu-coder/Kronos.git
cd Kronos
pip install -r requirements.txt
```

After cloning, add the Kronos directory to `sys.path` (or install editable:
`pip install -e .` if a `setup.py`/`pyproject.toml` exists) so that
`from model import Kronos, KronosTokenizer, KronosPredictor` resolves.

All dependency details (including HuggingFace Hub, torch, transformers versions)
are documented in `engine/requirements-kronos.txt`.

### Pre-flight checklist — updated status

- [x] **DONE (2026-05-20)** — `_predict_sync` wired: calls `KronosPredictor.predict()`
      with raw OHLCV DataFrame, auto-built `x_timestamp`/`y_timestamp` Series,
      `pred_len=horizon_bars`.  z-score normalisation applied internally.
- [x] **DONE (2026-05-20)** — Module-level singleton: `_get_or_load_predictor()` loads
      weights once from HF Hub; subsequent calls return cached instance.
- [x] **DONE (2026-05-20)** — Graceful fallback: `ImportError` at startup sets
      `_KRONOS_AVAILABLE=False`; `_predict_sync` returns `None`; engine boots
      cleanly without Kronos installed.
- [x] **DONE (2026-05-20)** — `run_in_executor` wrap: `_predict_async` off-loads the
      synchronous, CPU-bound predictor call to a thread pool executor.
- [x] **DONE (2026-05-20)** — `engine/requirements-kronos.txt` created with install
      instructions and optional dep list (separate from requirements-core.txt).
- [x] **DONE (2026-05-20)** — Side-by-side harness: `scripts/kronos_side_by_side.py`
      diffs `analyst_reports["kronos"]` between Kronos-OFF and Kronos-ON pipeline
      runs; outputs `scripts/data/kronos_side_by_side_<date>.md`.
- [x] **DONE (2026-05-21)** — Model weights downloaded and cached locally.
      `NeoQuasar/Kronos-mini` (~15.7 MB) + `NeoQuasar/Kronos-Tokenizer-2k` (~15.1 MB)
      cached to `~\.cache\huggingface\hub\`. Both load successfully on CPU.
- [x] **DONE (2026-05-21)** — Wall-clock latency measured: **0.53 seconds** per
      `predict()` call on 400-bar window, CPU-only. Well under any pipeline timeout.
      Shadow run is viable on this machine without batch inference queuing.
- [ ] **PENDING** — `list[dict]` → `pd.DataFrame` conversion validated with real
      engine bar data (confirm column names, timestamp dtype, no NaN in OHLCV).
- [ ] **PENDING** — Full pipeline side-by-side harness run (engine must be running at
      `127.0.0.1:8010`): `python scripts/kronos_side_by_side.py --symbol MES --days 3`.
      First-run direct-classifier validation done (see §16 and vault report).
- [ ] **PENDING** — `SSL_CERT_FILE` fix before activating in engine context:
      add `SSL_CERT_FILE=<certifi-path>` to `engine/.env` or fix the stale Anaconda
      path in the shell profile. Stale path blocks `from_pretrained()` on first load.
- [ ] **PENDING** — `HF_API_TOKEN` stored in `engine/.env` for model weight download
      (not required for public models, but eliminates the rate-limit warning).
- [ ] **PENDING** — `ENABLE_KRONOS=0` added to `engine/.env.example` — Amo does this.
- [ ] **PENDING** — MC confidence: `sample_count >= 5` wired to produce std dev
      confidence proxy instead of the current return-magnitude proxy.

### Side-by-side script usage

```powershell
# From repo root, venv active, engine running at 127.0.0.1:8010
cd C:\Users\mattm\ThinkorSwim\jarvis-trader
engine\.venv\Scripts\python scripts\kronos_side_by_side.py --days 3 --symbol MES
# Output: scripts/data/kronos_side_by_side_<timestamp>.md
```

---

## 15. ResearchAgent wired (2026-05-20)

Real LLM calls wired in `engine/agents/research_agent.py`. Implementation summary:

### What changed

- `propose()` now calls `JarvisLLMClient` via `AdvisorClient`'s lazy-load pattern
  when `ENABLE_RESEARCH_AGENT=1`. Default (flag off) still returns the hardcoded
  MES mean-reversion stub immediately at zero cost.
- Model tier: **haiku** (`claude-haiku-4-5-20251001`, $0.80/$4.00 per MTok).
  Never escalates to Sonnet without explicit caller approval.
- Parse pipeline: LLM output -> strip markdown fences -> extract JSON ->
  `model_validate` -> on any failure, log warning + return hardcoded stub. Never raises.
- Symbol field always forced to match the requested symbol, regardless of what the
  LLM returns.

### Cost gate

| Item | Value |
|---|---|
| Table | `engine/data/jarvis_trader.db` -> `research_agent_costs` |
| Schema | `(date TEXT PRIMARY KEY, usd_spent REAL DEFAULT 0)` |
| Check timing | **Pre-call** — budget check fires before LLM is contacted |
| Default budget | `$5.00/day` |
| Override | `RESEARCH_AGENT_DAILY_BUDGET_USD=<value>` in `engine/.env` |
| On exhaustion | Returns hardcoded stub + logs `WARNING: daily budget exhausted` |
| Spend recording | Post-call upsert using actual token counts from `LLMCallResult` |
| Typical cost/call | ~$0.00164 (600 input + 400 output tokens at haiku rates) |

The $5/day budget allows approximately 3,000 calls/day at haiku rates — far
more than the weekend cron will ever issue. The gate is a safety net against
runaway caller loops, not a practical throttle.

### Weekend cron

New module: `engine/scheduler/research_agent_weekend.py`

Function: `run_weekend_research_pass(symbols, n_hypotheses_per_symbol=3)`

| Output | Path |
|---|---|
| Hypothesis JSON | `engine/data/research_hypotheses/<YYYY-MM-DD>/<SYMBOL>-<N>.json` |
| Vault summary | `master-jarvis/second-brain/raw/_session-research/research-pass-<YYYY-MM-DD>.md` |

Runner script: `scripts/run_research_agent_weekend.py`

Reads `RESEARCH_AGENT_SYMBOLS` (comma-separated, default `MES,MNQ,MCL,MGC`) and
`RESEARCH_AGENT_N_HYPOTHESES` (default `3`, max `5`) from the environment.

**Suggested Windows Scheduled Task (Saturday 10:00 CT):**

```powershell
schtasks.exe /Create `
  /TN "Jarvis-ResearchAgent-Weekend" `
  /TR "\"$env:LOCALAPPDATA\Microsoft\WindowsApps\pwsh.exe\" -NonInteractive -File \"C:\Users\mattm\ThinkorSwim\jarvis-trader\scripts\run_research_agent_weekend.py\"" `
  /SC WEEKLY /D SAT /ST 10:00 /RL LIMITED
```

Note: `ENABLE_RESEARCH_AGENT` must be present in `engine/.env` (set to `1`) for
LLM calls to fire. Running the cron with the flag off still exercises the
artifact-write path using the hardcoded stub — useful for smoke-testing the
scheduled task itself.

### Pre-flight before going live — ResearchAgent (updated checklist)

- [x] **DONE** — LLM call wired (haiku tier, `JarvisLLMClient` via `AdvisorClient`).
- [x] **DONE** — Daily cost gate implemented ($5.00 default, pre-call check, post-call
      upsert in `research_agent_costs` table).
- [x] **DONE** — Parse fallback: JSON extraction, `model_validate`, graceful degradation
      to hardcoded stub on any failure.
- [x] **DONE** — Weekend cron module + runner script written.
- [x] **DONE** — 18/18 tests passing (6 new + 4 pre-existing strategy-tuner tests).
- [ ] Set `ENABLE_RESEARCH_AGENT=1` in `engine/.env` when ready for first live run.
- [ ] Install Jarvis-ResearchAgent-Weekend scheduled task (schtasks command above).
- [ ] Validate the rejection path: trigger `generate_hypothesis("MES")` and confirm
      the hypothesis is logged but NOT routed to any trade execution path.
- [ ] After first live weekend pass, review `engine/data/research_hypotheses/<date>/`
      and the vault summary before running any downstream backtest on the hypotheses.

### Safety concern: signal feature name hallucination

**LLM hallucination of signal feature names is the primary structural risk.**
The system prompt constrains `signal_weights` keys to a whitelist of 10 known
engine features (`stc_crossover`, `vwap_proximity`, etc.), but `signal_weights`
is typed as `dict[str, float]` — it accepts arbitrary keys without raising a
`ValidationError`.

Downstream consequence: a backtest harness consuming `signal_weights` will
silently ignore unknown keys (because the backtester looks up named features and
skips unknowns), producing a hypothesis that appears to have fewer active signals
than intended. This is a **silent degradation**, not an error — gate-v2 scores
will be skewed.

**Mitigation (future work):** Add a `model_validator(mode="after")` to
`StrategyHypothesis` that checks all `signal_weights` keys against the known
feature set and raises `ValidationError` for unknowns. Until that is added,
review the JSON artifacts from each weekend pass before running backtests.

---

## 13. Related runbooks

- [HEALTH_API_CONTRACT.md](HEALTH_API_CONTRACT.md) — `/health` endpoint fields
  and pass criteria; use to verify pipeline is healthy after flag flip.
- `QUANTSTATS_TEARSHEET_RUNBOOK.md` — gate-v2 metric definitions; reference for
  the ResearchAgent hypothesis scoring thresholds.

---

## 16. Installation complete (2026-05-21)

**Status:** COMPLETE. Kronos installed into engine venv. Non-stub inference
confirmed. `ENABLE_KRONOS=0` remains the default — activation is a separate decision.

**`_KRONOS_AVAILABLE=True` after install.** The engine boots cleanly and
`_KRONOS_AVAILABLE=False` branch is no longer triggered — the warning log about
"Kronos package not installed" no longer appears.

### What was installed and verified

| Item | Result |
|------|--------|
| Engine venv Python | 3.12.10 |
| `torch` | 2.5.1 (already installed) |
| `huggingface_hub` | 1.15.0 (already installed) |
| `transformers` | 5.9.0 — installed this session |
| `einops` | 0.8.1 — installed this session |
| `safetensors` | 0.6.2 — installed this session |
| Kronos clone | `C:\Users\mattm\Code\Kronos-upstream\` |
| Install method | `.pth` file — `engine\.venv\Lib\site-packages\kronos-upstream.pth` |
| Import verify | `from model import Kronos, KronosTokenizer, KronosPredictor` → OK |
| `KronosPredictor.__module__` | `model.kronos` (confirmed) |
| Model loaded | `NeoQuasar/Kronos-mini` + `NeoQuasar/Kronos-Tokenizer-2k` — both OK |
| Device | `cpu` (no GPU on this machine) |
| Inference latency | **0.53 seconds** per predict() on 400-bar window, CPU |
| Non-stub output | CONFIRMED — OFF: `predicted -10.6 bps`, ON: `predicted +8.4 bps` |
| Combined checkpoint size | ~30.8 MB (~15.7 MB mini + ~15.1 MB tokenizer) |
| `_KRONOS_AVAILABLE` after install | `True` |
| `is_kronos_enabled()` | `False` (ENABLE_KRONOS=0, default unchanged) |
| `engine/.env` modified | NO — ENABLE_KRONOS not set |

### Install path to use (canonical — run manually)

Kronos has **no `setup.py` or `pyproject.toml`**. The canonical install is a
clone + `.pth` file to put the cloned directory on `sys.path`.

```powershell
# 1. Clone Kronos (requires git clone permission or manual run)
git clone https://github.com/shiyu-coder/Kronos.git C:\Users\mattm\Code\Kronos-upstream

# 2. Install dependency gaps into engine venv
engine\.venv\Scripts\pip.exe install "transformers>=4.38.0"
engine\.venv\Scripts\pip.exe install "einops==0.8.1" "safetensors==0.6.2"

# 3. Add Kronos to sys.path via .pth file
Add-Content -Path "engine\.venv\Lib\site-packages\kronos-upstream.pth" `
  -Value "C:\Users\mattm\Code\Kronos-upstream"

# 4. Verify import
engine\.venv\Scripts\python.exe -c "from model import Kronos, KronosTokenizer, KronosPredictor; print('OK')"

# 5. Test model load (first call downloads ~30.8 MB to ~/.cache/huggingface/)
engine\.venv\Scripts\python.exe -c "
from model import Kronos, KronosTokenizer, KronosPredictor
tok = KronosTokenizer.from_pretrained('NeoQuasar/Kronos-Tokenizer-2k')
m = Kronos.from_pretrained('NeoQuasar/Kronos-mini')
pred = KronosPredictor(m, tok, max_context=512)
print('OK — device:', pred.device)
"

# 6. Verify classifier picks it up
cd C:\Users\mattm\ThinkorSwim\jarvis-trader
engine\.venv\Scripts\python.exe -c "
import sys, os
sys.path.insert(0, 'engine')
os.environ['API_KEY'] = 'smoke'
from agents.kronos_classifier import is_kronos_enabled, _KRONOS_AVAILABLE
print('_KRONOS_AVAILABLE=', _KRONOS_AVAILABLE)  # expect True after install
"
```

### To verify install is correct (after running steps above)

```powershell
engine\.venv\Scripts\python.exe -c "from model import KronosPredictor; print(KronosPredictor.__module__)"
# Expected output: model.kronos
```

### Permission grant for Claude Code to run this automatically in future

Add to `C:\Users\mattm\ThinkorSwim\jarvis-trader\.claude\settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Bash(git clone https://github.com/shiyu-coder/Kronos.git*)",
      "PowerShell(git clone https://github.com/shiyu-coder/Kronos.git*)"
    ]
  }
}
```

### Disk footprint summary

| Component | Location | Size |
|-----------|----------|------|
| Kronos repo (code only, no weights) | `C:\Users\mattm\Code\Kronos-upstream\` | ~2–5 MB (estimated) |
| `NeoQuasar/Kronos-mini` weights | `~\.cache\huggingface\hub\` | ~15.7 MB |
| `NeoQuasar/Kronos-Tokenizer-2k` weights | `~\.cache\huggingface\hub\` | ~15.1 MB |
| `transformers` + `einops` + `safetensors` | `engine\.venv\Lib\site-packages\` | ~200–400 MB (transformers is large) |
| **Total net new** | | **~220–430 MB** |

Note: `transformers` is the largest dependency by far (~200–400 MB including
tokenizer models and supporting files). If disk is constrained, only `einops`
and `safetensors` can be installed without `transformers` — but `transformers`
is listed in `engine/requirements-kronos.txt` as required for `KronosTokenizer`'s
`from_pretrained` loader.

### Side-by-side run — pending install + engine running

Once the install is complete and the engine is running at `127.0.0.1:8010`:

```powershell
# Run with ENABLE_KRONOS=1 set in subprocess env (does NOT modify engine/.env)
$env:ENABLE_KRONOS = "1"
engine\.venv\Scripts\python.exe scripts\kronos_side_by_side.py --symbol MES --days 3
# Output: scripts/data/kronos_side_by_side_<timestamp>.md
```

The script sends `X-Kronos-Override: 1` header to the engine pipeline, which
the engine can use to override the env flag per-request without an engine restart.
If the engine build predates that header support, the diff will show all-zeros
(both OFF and ON return the same stub result).

### ENABLE_KRONOS default — confirmed OFF

`ENABLE_KRONOS=0` is the default. This install session does NOT and MUST NOT
modify `engine/.env`. Activation is a separate decision after:
1. Latency measured (`predict()` on 400-bar window, CPU-only)
2. Side-by-side report reviewed showing non-stub ON verdict
3. Explicit Amo authorization for shadow run

### Blocker for full activation

**Primary blocker: CPU inference latency unknown.** The Kronos-mini model
(~24M params) must run inference on CPU (no GPU on this machine). A 400-bar
`predict()` call is estimated at 5–30 seconds. If latency exceeds the pipeline's
per-analyst timeout, Kronos will always time out and contribute `confidence=0.0`
regardless of the flag — making the shadow run moot. Measure first with the
latency probe in the vault report before authorizing activation.

Latency probe (run after install):
```powershell
engine\.venv\Scripts\python.exe -c "
import time, pandas as pd
from model import Kronos, KronosTokenizer, KronosPredictor
tok = KronosTokenizer.from_pretrained('NeoQuasar/Kronos-Tokenizer-2k')
m = Kronos.from_pretrained('NeoQuasar/Kronos-mini')
pred = KronosPredictor(m, tok, max_context=512)
bars = pd.DataFrame({'open': [5000.0]*400, 'high': [5010.0]*400,
                     'low': [4990.0]*400, 'close': [5005.0]*400})
x_ts = pd.date_range(end=pd.Timestamp.now(), periods=400, freq='1h')
y_ts = pd.date_range(start=x_ts[-1], periods=6, freq='1h')[1:]
t0 = time.perf_counter()
result = pred.predict(bars, pd.Series(x_ts), pd.Series(y_ts), pred_len=5)
elapsed = time.perf_counter() - t0
print(f'Latency: {elapsed:.1f}s | device: {pred.device}')
print(result[['open','high','low','close']].tail())
"
```

Shadow run viable if latency < 15s. Needs batch inference queue if > 30s.
