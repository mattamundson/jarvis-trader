---
name: strategy-spec-extract
description: Turn a trader's transcript, video, or written notes into a structured jarvis-trader strategy candidate, then route it into the engine's existing pre-registration + forward-test gates (never auto-execution). Use when the user says "extract a strategy from this transcript/video", "turn this trader's rules into a candidate", "codify this setup", "make a rules spec from these notes", or pastes a YouTube/trader transcript and wants it operationalized. Adapts the crypto rules.json idea from jackson-video-resources/claude-tradingview-mcp-trading, stripped of exchange execution and remapped to jarvis futures + the candidate_registry graduation flow.
---

# strategy-spec-extract

Extracts a testable strategy hypothesis from a human source (transcript / video / notes) and
lands it as a **pre-registered candidate** in the engine's existing validation pipeline. The
extracted spec is a *hypothesis to be tested*, never an executable bot.

Idea source: the `prompts/01-extract-strategy.md` + `rules.json` *pattern* from
[jackson-video-resources/claude-tradingview-mcp-trading](https://github.com/jackson-video-resources/claude-tradingview-mcp-trading).
That repo declares **no license** (its `LICENSE` URL 404s and `package.json` has no `license`
field), so treat it as all-rights-reserved: this skill reuses only the *concept/approach* of
spec extraction, remapped and rewritten for jarvis futures — it does not copy that repo's
prompt or rules text. That repo's crypto **execution** half is deliberately not integrated (see the
`tradingview-mcp` skill's "Rejected integration" section). Only the *specification* idea is
kept, and it is remapped onto jarvis-trader's futures + pre-registration discipline.

## Hard boundaries

- **Extraction ≠ deployment.** Producing a spec never trades, never sizes a position, never
  routes an order. The only path from spec → tradeable is the engine's graduation rule below,
  and even graduation is *necessary, not sufficient* (gate-v2 routing still governs).
- **No LLM-invented rules.** Extract only what the source explicitly states. Mark anything you
  inferred as `inferred: true` in `notes` — an inferred rule is a question for Matt, not a fact.
- **Futures only, active paper instruments only.** Map the source to **MES or MGC** — the active
  paper instruments (MGC re-authorized 2026-08-04 on a fresh gate-v2 CORE PASS, PR #597; verify
  `DO_NOT_TRADE_SYMBOLS` / `paper_config.py` at use time since its status has flipped before). If
  the source is crypto/equities/FX with no clean futures analog, say so and stop — do not
  force-fit. **MNQ and MCL are HALTED** (`DO_NOT_TRADE_SYMBOLS`); you may draft a candidate for a
  halted symbol but mark it `status: "paused"`, never `forward_testing`.
- **No exchange keys, no `.env` execution knobs.** The crypto repo's `BITGET_*`,
  `MAX_TRADE_SIZE_USD`, `PAPER_TRADING`, etc. do NOT come across. Position sizing and risk
  live in hardcoded `engine/config.py` / `engine/risk/`, which this skill never touches.

## Step 1 — Extract the raw spec

From the transcript/notes, pull only what the trader explicitly says:

1. **Indicators** — name + settings + the job each one does.
2. **Bias criteria** — bullish / bearish / neutral conditions.
3. **Entry rules** — separated by long / short.
4. **Exit rules** — targets, trailing, time stops.
5. **Risk rules** — stop distance, R-multiple, max trades, avoidance flags.
6. **Timeframe(s)** — and any HTF/LTF hierarchy.

Verbatim-or-flagged: quote the trader where possible; tag inferences.

## Step 2 — Remap to a jarvis candidate

Translate the raw spec into the shape the engine's registry expects. The required candidate
fields (enforced by `engine/backtest/candidate_registry.py`) are:
`id`, `symbol`, `family`, `status`, `hypothesis`, `params`.

```json
{
  "id": "extracted-<source>-<symbol>-<yyyymmdd>",
  "symbol": "MES",
  "family": "<e.g. vwap_rsi_reversion>",
  "status": "paused",
  "hypothesis": "One falsifiable sentence: what edge, on what instrument, in what regime.",
  "params": {
    "timeframe": "<tf the source states, e.g. 5m>",
    "indicators": { "<name>": "<setting the source gives — omit any the source doesn't state>" },
    "entry_long":  ["<long condition verbatim from source>", "..."],
    "entry_short": ["<short condition verbatim from source>", "..."],
    "exit":  ["<exit/target/stop rule from source>", "..."],
    "risk":  ["<risk rule from source>", "point-in-time only"]
  },
  "lock_in_sample": {
    "gate_verdict": "PENDING",
    "passed_via": "<core|alt — copy verbatim from the gate verdict; wfo_lifecycle.py emits exactly these>",
    "pf_ci_lower": "<actual — from the gate-v2 WFO verdict>",
    "p_edge": "<actual — gate-v2>",
    "dsr": "<actual — gate-v2>",
    "mc_95th_dd": "<actual — gate-v2>",
    "n_oos_windows": "<actual — gate-v2>",
    "total_oos_trades": "<actual — gate-v2>",
    "p_binom": "<actual — from family_fdr.binomial_oos_pvalue(p_edge, n_windows), NOT gate-v2; omit if the family report wasn't run>"
  },
  "source": "<trader / URL>",
  "notes": "Timeframe/asset caveats. Flag every inferred rule here."
}
```

Keep params **mechanical and locked** — the registry judges a *frozen* hypothesis. You register
a new `id` rather than mutating params later. `allowed_status`:
`forward_testing | graduated | rejected | paused`.

**`lock_in_sample` is required discipline, not optional** — even though `verify_registry()`
only enforces `id/symbol/family/status/hypothesis/params`, the forward-test loop reads
`lock_in_sample` (`candidate_registry.py`) to compare OOS results against a *frozen* baseline.
Fill it from the **actual** gate-v2 WFO verdict (the fields above mirror a real entry:
`gate_verdict`, `pf_ci_lower`, `p_edge`, `dsr`, `mc_95th_dd`, `n_oos_windows`,
`total_oos_trades` — all from `wfo_lifecycle.compute_gate_v2()`). `p_binom` is the **exception**:
`compute_gate_v2()` does not emit it — it comes from `family_fdr.binomial_oos_pvalue(p_edge,
n_windows)` / the family report, so copy it from there if you ran the family FDR pass, else omit
it (the registry validator does not require it). Never invent any of these numbers.
The template ships `status: "paused"` and `gate_verdict: "PENDING"` with `<actual …>`
placeholders **on purpose** — two independent guards against a premature copy going live:
`get_active_candidates()` keys only on `status == "forward_testing"`
(`candidate_registry.py:103`), so a `paused` candidate is inert even if committed early; and a
half-filled lock must never read as a `PASS` baseline. Do **not** flip `status` to
`forward_testing`, set `gate_verdict: "PASS"`, or fill the metrics until the real Step-3 run
produces them — a `forward_testing` candidate with a fake PASS lock enters the forward loop
with no frozen expectation and contaminates the graduation decision. Register and activate it
only *after* Step 3's backtest + MCPT produce these values.

## Step 3 — Route into the real gates (do NOT invent a parallel path)

1. **Point-in-time check first.** Confirm every rule uses only bars `<= t` (no `shift(-n)`, no
   full-series fit, gate news on publish timestamp). See `.claude/rules/testing.md` "No
   look-ahead bias". A leaked rule is discarded, not tuned.
2. **Backtest the EXTRACTED rules — not the built-in strategy.** ⚠️ `POST /backtest/run` does
   **not** accept a strategy/params body: `BacktestRequest` is only symbol/date/interval/capital
   and `run_backtest()` unconditionally calls `generate_instrument_signals(df, symbol=...)`
   (`engine/routers/backtest_router.py`), i.e. it runs the symbol's *canonical* strategy. So that
   endpoint validates the extracted candidate **only if** the candidate is literally the canonical
   rule set. For a genuinely new extracted spec you MUST implement its rules as a point-in-time
   signal function (a candidate-specific runner over `engine/backtest/backtester.py`) and confirm
   the *exact locked rules* were exercised before trusting any metric. Never copy metrics from the
   default `/backtest/run` (or TradingView's tester) into `lock_in_sample` as if they belonged to
   the extracted rules — that corrupts the pre-registration. Summarize with the `backtest-report` skill.
3. **MCPT** — run the `mcpt-validation` skill (bar-permutation) to check the edge isn't
   data-mining noise. One run per locked spec; a fail means discard, not adjust.
3b. **Gate-v2 WFO produces the lock stats — not the single backtest/MCPT.** ⚠️ The
   `lock_in_sample` fields (`gate_verdict`, `passed_via`, `pf_ci_lower`, `p_edge`, `dsr`,
   `mc_95th_dd`, `n_oos_windows`) are computed by `wfo_lifecycle.compute_gate_v2()` over a
   **walk-forward** run — a single Backtester run + bar-permutation MCPT cannot produce them. So
   run a candidate-specific WFO / gate-v2 pass BEFORE step 4 and fill the lock verbatim from that
   verdict; never hand-fill or borrow backtest/MCPT numbers into the lock. (This is why the WFE
   step below is really a precondition of registration for a genuinely new candidate, not an
   afterthought.)
4. **Pre-register** the candidate in `engine/backtest/candidate_registry.json` with its
   in-sample lock stats **(from the step-3b gate-v2 verdict)**. Graduation rule (from the registry): `min_forward_oos_windows: 6`,
   `min_forward_pf_ci_lower: 1.10`, `min_forward_p_edge: 0.95`, `must_survive_family_fdr: true`.
   ⚠️ **Flipping `status` to `forward_testing` is NOT enough to accumulate those windows.** The
   live entry path is LLM-driven, not mechanical, so a mechanical registry candidate "never fires
   live and only ever attributes at symbol level (never graduates)" unless its forward paper
   trades are tagged with the `candidate_id` (`engine/backtest/forward_test.py`). A genuinely new
   extracted rule set therefore needs a **candidate-specific, observe-only paper generation +
   `candidate_id` tagging path** before window accumulation is real — without it the candidate sits
   at non-graduating symbol-level attribution indefinitely. Don't promise graduation until that
   tagging path exists.
5. **WFE** — check the `jarvis-wfe-check` thresholds before anyone considers sizing.

At every step the candidate is paper-only and human-gated. Nothing here can place an order.

## What this skill does NOT do

- Does not edit `engine/config.py`, `engine/risk/`, or any safety file.
- Does not place, size, or approve trades.
- Does not add an exchange connector or any auto-execution loop.
- Does not promote a candidate to live — that is a separate, Tier-3, human decision.

## Related

- `mcpt-validation` — permutation test the extracted edge
- `backtest-report` — format the backtest run
- `jarvis-wfe-check` — walk-forward efficiency gate
- `engine/backtest/candidate_registry.py` / `candidate_registry.json` — the pre-registration lock
- `tradingview-mcp` skill — chart reads for the same instruments; also documents why the
  companion crypto execution bot is rejected
