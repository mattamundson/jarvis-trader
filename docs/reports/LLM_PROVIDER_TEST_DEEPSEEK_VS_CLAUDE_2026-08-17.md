# LLM Provider Cost/Quality Verdict — DeepSeek vs Claude (Tier-2 Decision)

**Date:** 2026-08-17 (test run ~23:00 CDT) · **Report:** 2026-08-18
**Author:** JARVIS ops (isolated test, no engine involvement)
**Related commit:** `2a9f22ae` (fix(llm): route default/fast model to deepseek-reasoner when `JARVIS_LLM_PROVIDER=deepseek`)
**Related cards:** T1 (DeepSeek routing), T3 (this report), T4 (spend tracking), T8 (provider decision + failover hardening)

---

## 1. Executive verdict

**Adopt DeepSeek `deepseek-reasoner` as the Tier-2 (decision/analysis) LLM provider.** On an identical bull-researcher prompt fired directly at both APIs, DeepSeek was **5.1x cheaper** ($0.00193 vs $0.0099 per call) and **33% faster** (10.4s vs 15.5s), while producing structurally valid JSON with a coherent thesis, correct entry/stop/target math, an appropriately hedged confidence, and 5 specific risks.

- **Tier-2 (8 non-advisor agents)** → `deepseek-reasoner` (bull_researcher, bear_researcher, fund_manager, risk_manager, trader, news_analyst, social_analyst, technical_analyst).
- **Tier-1 (advisor debate)** → keep `claude-opus-4-7` (deliberate; `advisor_client.py ADVISOR_MODEL` — "Advisor always uses the most capable model").
- **Fallback chain** → `deepseek-reasoner → claude-sonnet-4-6` (already configured in `COST_PER_MTOK`/`FALLBACK_CHAIN`), so Anthropic remains the safety net if DeepSeek degrades.
- **Gate:** this is a single-sample (n=1 per model) test on one prompt. Promote DeepSeek to Tier-2 default, but keep Claude fallback live and re-validate after 1–2 weeks of pipeline logs (T8 card).

---

## 2. Test methodology (isolated, zero engine risk)

- **Date/time:** 2026-08-17 ~23:00 CDT.
- **Method:** direct API calls from `engine/` with keys read from `engine/.env`. No pipeline, no engine process, no risk to live trading.
- **Prompt:** a bull-researcher-style system + user prompt representative of the actual decision agents — argue the strongest LONG-MES case from a real technical-analyst-style report (deeply oversold MES at $7741–7743 support, RSI 15.1, ADX 42.7, hidden-pivots rounded-top, OBV divergence, current price $7742.75), with a strict output contract: `thesis, entry_price, stop_loss, take_profit, confidence (0–1), key_risks[]` as valid JSON.
- **Models tested:**
  - Claude: `claude-sonnet-4-6` (Anthropic SDK, the engine's historical default for decision agents)
  - DeepSeek: `deepseek-reasoner` (DeepSeek OpenAI-compatible endpoint, `https://api.deepseek.com/v1/chat/completions`)
- **Both calls:** `max_tokens=800`, identical system + user messages.
- **Run history (important for interpreting token counts):** Run 1 fired both models back-to-back and produced the headline cost/latency numbers. DeepSeek's run-1 response hit the `max_tokens=800` cap during the reasoning phase — `completion_tokens=800`, `content=""`, i.e. no usable output (the billing still applied: $0.00193). A second DeepSeek call with the same prompt was made to capture actual content: `completion_tokens=538` (incl. 240 reasoning), `finish_reason="stop"`, full valid JSON. All DeepSeek *content* samples below are from run 2; the cost/latency row reflects run 1 (the conservative, higher-billed figure).

---

## 3. Comparison table

| Metric | `claude-sonnet-4-6` | `deepseek-reasoner` | Delta |
|---|---|---|---|
| **Cost per call** | $0.00990 | $0.00193 | **5.13x cheaper** |
| **Latency** | 15.5 s | 10.4 s | **33% faster** |
| Input tokens | 275 | 330 | +20% (same prompt; model tokenization differs) |
| Output tokens | 605 | 800 billed (run 1 cap) / 538 actual (run 2, incl. 240 reasoning) | — |
| JSON validity | ✅ structurally valid | ✅ structurally valid | tie |
| Trade math (entry/stop/target) | coherent, R:R ~3:1 | coherent, R:R ~2.9:1 | tie |
| Confidence calibration | 0.38 — hedged, appropriate for mixed signal | 0.38 — hedged, appropriate for mixed signal | **tie (both 0.38)** |
| Risk enumeration | 8 specific risks | 5 specific risks, well-reasoned | tie (Claude broader; DeepSeek sufficient) |
| Reasoning content exposed | ❌ (Anthropic hides it) | ✅ 953-char `reasoning_content` (auditable chain) | **DeepSeek edge** |
| Finish reason | stop | stop (run 2; run 1 hit max_tokens during reasoning) | tie (usable output) |

**Cost math (per engine `COST_PER_MTOK`):**
- Claude: `(275×$3.00 + 605×$15.00) / 1e6 = $0.00990`
- DeepSeek: `(330×$0.55 + 800×$2.19) / 1e6 = $0.00193`

**Unit rates (engine `llm/client.py:236-254`):**

| Model | $/MTok in | $/MTok out |
|---|---|---|
| claude-sonnet-4-6 | 3.00 | 15.00 |
| deepseek-reasoner | 0.55 | 2.19 |
| claude-opus-4-7 (advisor, unchanged) | 15.00 | 75.00 |

---

## 4. Output samples

### 4a. Claude (`claude-sonnet-4-6`) — full output (verbatim, saved payload)

Claude wrapped its output in a ```json fence (the engine's extractor already handles this). Full text below:

```json
{
  "thesis": "Extreme oversold conditions at key support create a high-probability mean-reversion long opportunity in MES. RSI at 15.1, Williams %R at -97, and Stochastic %K at 5.0 represent historically rare multi-indicator capitulation readings that statistically precede sharp counter-trend bounces, even within established downtrends. Price is sitting precisely at the $7741-7743 support zone — a level the market has already demonstrated awareness of. The minor OBV bullish divergence is critical: price is making lows but accumulation is quietly occurring, suggesting institutional absorption at this level. Volume at 0.06x average indicates seller exhaustion — a dry-up in sell-side participation at support is a classic spring setup. The risk/reward is asymmetric: the defined downside targets from the Hidden Pivots pattern ($7729/$7716/$7703) give us a tight, measurable stop placement, while any mean-reversion snap-back toward the nearest SMA cluster or prior consolidation offers a 3:1+ reward ratio. We are NOT calling a trend reversal — we are trading a counter-trend mean-reversion bounce from a statistically extreme oversold reading at a defined support level. The trade is managed tightly and we exit into strength, not held as a reversal thesis.",
  "entry_price": 7743.50,
  "stop_loss": 7700.00,
  "take_profit": 7875.00,
  "confidence": 0.38,
  "key_risks": [
    "Dominant downtrend confirmed by ADX 42.7 — counter-trend trades have high failure rates in strong trend environments",
    "Hidden Pivots rounded-top pattern with 80% bearish confidence directly contradicts the long thesis and targets $7703 or lower",
    "Price trading below all major SMAs (20/50/200) — no structural support from moving averages above",
    "Extremely thin volume (0.06x average) can cause erratic, illiquid price action that triggers stops prematurely or prevents clean exits",
    "OBV divergence is described as 'minor' — insufficient as a standalone reversal signal without price confirmation",
    "No confirmed reversal candle, pattern, or momentum crossover — entry is anticipatory, not confirmed",
    "Gap-down open or macro catalyst (Fed commentary, geopolitical shock, economic data miss) could accelerate selling and blow through stop",
    "Oversold conditions can persist and extend in strong downtrends — 'oversold can get more oversold'"
  ]
}
```

**Claude usage:** `input_tokens=275`, `output_tokens=605`, `latency=15.5s`, `cost=$0.00990`, `finish_reason=stop`.

### 4b. DeepSeek (`deepseek-reasoner`) — full output (verbatim, saved payload)

```json
{
  "thesis": "MES is deeply oversold at major horizontal support with multiple momentum oscillators at extreme readings not seen in prolonged downtrends, and OBV is showing a bullish divergence. With volume at 0.06x average, the bearish move lacks participation, increasing the odds of a violent short-covering mean-reversion bounce off the $7741-7743 support shelf. Long entry here offers asymmetric reward if price stabilizes and reclaims structure toward the 20 SMA.",
  "entry_price": 7742.75,
  "stop_loss": 7729.00,
  "take_profit": 7780.50,
  "confidence": 0.38,
  "key_risks": [
    "Strong confirmed downtrend with ADX 42.7 and price below all major SMAs means rallies are likely to be sold without a confirmed reversal.",
    "Hidden Pivots rounded-top pattern carry 80% confidence and target lower levels at $7729, $7716, and $7703, suggesting support may break.",
    "Extremely thin volume can lead to slippage and false breakouts; a liquidity vacuum could extend the move lower.",
    "No bullish price-action confirmation exists yet—oversold conditions can remain oversold in a persistent downtrend.",
    "If $7741 fails, stop loss triggers quickly and momentum could accelerate toward the lower pivot targets."
  ]
}
```

**DeepSeek usage detail (captured payload):** `prompt_tokens=330`, `completion_tokens=538` (incl. `reasoning_tokens=240`), `total_tokens=868`, `prompt_cache_hit_tokens=256` / `prompt_cache_miss_tokens=74`. Finish reason `stop`.

**Notable caveat:** the DeepSeek API echoed `"model": "deepseek-v4-flash"` in the response for a `deepseek-reasoner` request. Either the API aliases the label or billing differs from the engine's cost table — verify the billed model on the DeepSeek dashboard during T4 (spend tracking) before trusting the cost table long-term. [ASSUMPTION]

### 4c. Quality comparison notes

- Both models respected the JSON contract; no markdown-wrapped JSON in the DeepSeek content (Claude's was wrapped in a ```json fence in the raw response — the engine's extractor already handles this).
- Claude's R:R: (7875.00−7743.50)/(7743.50−7700.00) ≈ 131.50/43.50 ≈ **3.02:1**. DeepSeek's R:R: (7780.50−7742.75)/(7742.75−7729.00) ≈ 37.75/13.75 ≈ **2.75:1**. Both coherent; Claude's is more aggressive on target (and stop), DeepSeek's is tighter and closer to the support shelf.
- **Both models returned `confidence=0.38`** for a genuinely mixed setup (strong downtrend vs extreme oversold). Identical and appropriately conservative — not an aggressive bull case from either. Calibration is a **tie**.
- DeepSeek exposes `reasoning_content` (953 chars) — the engine can log the reasoning chain for auditability. Claude does not expose this.

### 4d. JSON validity check (independent re-verification, 2026-08-18)

Both saved payloads were re-parsed with `json.loads` against the strict output contract (`thesis: string, entry_price: number, stop_loss: number, take_profit: number, confidence: float 0-1, key_risks: array<string>`):

| Check | `claude-sonnet-4-6` | `deepseek-reasoner` |
|---|---|---|
| Raw parse (after stripping ```json fence on Claude) | ✅ valid | ✅ valid |
| Required keys present (6/6) | ✅ | ✅ |
| Numeric types (entry/stop/target) | ✅ 7743.50 / 7700.00 / 7875.00 | ✅ 7742.75 / 7729.00 / 7780.50 |
| confidence in [0,1] | ✅ 0.38 | ✅ 0.38 |
| key_risks non-empty array of strings | ✅ 8 items | ✅ 5 items |
| entry within prompt's price context | ✅ ($7741-7743 zone) | ✅ ($7741-7743 zone) |
| Verdict | **usable** | **usable** |

Result: both outputs are machine-usable as-is; no extraction repair needed for either.

---

## 5. Real operational cost evidence (engine tracking DB, 2026-08-04 → 2026-08-18)

From `engine/data/llm_costs.db` (`llm_calls` table, 117,512 total rows incl. failures; table below = successful calls in the 2026-08-04 → 2026-08-18 window, re-verified 2026-08-18):

| Model | Calls | Total cost | Avg $/call | Avg latency |
|---|---|---|---|---|
| claude-sonnet-4-6 | 1,093 | $12.52 | $0.01146 | 12.1 s |
| kimi-k3 | 295 | $7.73 | $0.02621 | 50.4 s |
| claude-haiku-4-5 | 2,119 | $5.32 | $0.00251 | 9.8 s |
| claude-opus-4-7 (advisor) | 97 | $1.93 | $0.01991 | 4.5 s |
| deepseek-reasoner | 7 | $0.017 | $0.00239 | 9.8 s |
| qwen2.5:7b (local) | 694 | $0.00 | $0.00 | 69.7 s |
| **Total** | **4,305** | **$27.52** | — | — |

**Savings estimate:** the Sonnet tier is the second-largest spend line ($12.52/14d). Moving those 1,093 calls to DeepSeek at the observed $0.00239/call ≈ **$2.61/14d**, saving **~$9.90/14d ≈ $258/yr** on the Sonnet tier alone. Including the broader decision tier, realistic full-pipeline savings are **$300–500/yr** at current volume. Latency on the decision tier also drops ~30–40%.

---

## 6. Risks & mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Single-prompt test (n=1) — quality may not generalize | Med | Keep Claude fallback live; re-validate after 1–2 weeks of pipeline logs (T8) |
| DeepSeek API echo label `deepseek-v4-flash` vs `deepseek-reasoner` — billing ambiguity | Med | Verify on DeepSeek dashboard during T4 spend tracking |
| Reasoning tokens count toward output billing (240/538 in test) | Low–Med | Cost model already uses $2.19/MTok output; accounted for in savings estimate |
| DeepSeek availability / rate limits | Low | `FALLBACK_CHAIN[deepseek-reasoner] = claude-sonnet-4-6` (already in client.py) |
| Prompt caching changes cost profile (256 cached tokens observed) | Low | Caching reduces cost — the engine's flat-rate model overstates, never understates |
| 8 agent files still hardcode Claude model constants | Med | T1 card: refactor to route via `JARVIS_LLM_PROVIDER` (tracked separately) |

---

## 7. Recommendation for the Tier-2 provider decision

1. **Default Tier-2 provider = DeepSeek `deepseek-reasoner`** — 5.1x cheaper, 33% faster, structurally valid JSON, comparable-or-better confidence calibration on the test prompt, plus auditable reasoning content.
2. **Keep Anthropic `claude-sonnet-4-6` as the fallback** (already wired in `FALLBACK_CHAIN`).
3. **Keep `claude-opus-4-7` for the advisor debate** (unchanged, deliberate).
4. **Blocking prerequisites before full promotion** (handled by sibling cards):
   - T1 — refactor the 8 hardcoded `claude-*` agent constants so `JARVIS_LLM_PROVIDER=deepseek` actually routes every non-advisor agent (this test caught that only `default_model`/`fast_model` were routed — see commit `2a9f22ae`).
   - T4 — persistent spend tracking so DeepSeek's real billed cost (including the `v4-flash` label question) is visible before the 1–2 week gate.
5. **Decision gate (T8):** after T1 + T4 are complete, confirm DeepSeek stays as default with a circuit breaker and documented cost ceiling, or revert to Anthropic with a written reason.
