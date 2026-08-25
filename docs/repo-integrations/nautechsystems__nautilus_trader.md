---
repo: nautechsystems/nautilus_trader
url: https://github.com/nautechsystems/nautilus_trader
target_file: examples/backtest/crypto_ema_cross_ethusdt_trailing_stop.py
stars: 24800
language: Rust (core) / Python (API)
license: LGPL-3.0
archived: false
pushed_at: 2026-06-29
analyzed_at: 2026-07-17
recommendation: partial-integrate
surfaces_with_value: [engine, dev-tooling, docs]
status: Path-A-implemented (2026-07-17)
---

# nautechsystems/nautilus_trader

## Status update — 2026-07-17 (Path A shipped)

Matt chose **Path A** (parity/differential harness). Implemented and verified:

- `engine/backtest/nautilus_parity.py` — runs one reduced common spec (SMA
  golden-cross in / death-cross out, 1 contract, zero costs) through BOTH the
  in-house `Backtester` and Nautilus's `BacktestEngine`; reads the Nautilus
  instrument multiplier and feeds the identical value to the custom engine so
  contract economics match; returns a `ParityReport` (trade-count match + PnL
  within tolerance).
- `engine/tests/test_backtest_parity.py` — 3 tests, `importorskip`s
  nautilus_trader/pandas so the suite stays green where the optional dep is
  absent.

Verification level: **ran and observed output** (not just type-checks). On
deterministic synthetic bars both engines return exactly 1 trade / +170.00 PnL
(|Δ|=0). On real MNQ 1h cache the trade counts match exactly (19/19 at 2000 bars,
54/54 at 5000) with PnL agreeing to ~0.3–1% — the residual is the documented
entry-fill convention (custom fills next-bar-open; Nautilus fills signal-bar
close). Consequence: `nautilus_trader` is no longer a phantom dependency — the
harness is a live consumer. Three real Nautilus quirks were surfaced and handled
during bring-up (contract activation/expiry windows reject orders on a continuous
multi-year series → switched to a non-expiring equity vehicle; open dangling
position at data end must be excluded to match completed-trades semantics).
`ruff` clean; safety files untouched (no `[safety-review]` needed).

## Core value proposition

NautilusTrader is a production-grade, Rust-native, event-driven trading platform whose
headline design property is **backtest/live parity**: the *same* strategy object runs
unchanged against historical ticks in `BacktestEngine` and against a live venue adapter.
The analyzed file is not library code — it is a ~90-line *example script* that wires an
`EMACrossTrailingStop` strategy (fast/slow EMA cross entry, ATR-based
`TrailingStopMarketOrder` exit with `reduce_only=True`) onto a Binance ETHUSDT spot
backtest driven by 100-tick bars.

The important fact for us: **`nautilus_trader==1.211.0` is already pinned in
`engine/requirements.txt` (line 36) and `requirements-core.txt`, but a full-tree grep
finds zero `import nautilus` / `from nautilus` anywhere in `engine/`.** It is a
declared-but-unused ("phantom") dependency. So this analysis is really about two
separate questions: (a) is the *strategy* in the example novel? — no, we already have it
three times over; and (b) should we either *use* or *drop* the heavyweight dep we're
already carrying? — that's the live decision.

## Surface analysis

### 1. Engine code
`dedup-engine` (strategy) + `partial-integrate` (framework decision).

Every concept in the example is already implemented natively:
- **ATR trailing stop (long & short):** `engine/backtest/backtester.py:347-414`
  (`_process_trailing_stop_long` / `_short`), gated on favorable excursion, with a
  `strict_trailing` every-bar mode. Live equivalent:
  `engine/services/trailing_stop_manager.py` (ATR(14,1h), `TRAILING_STOP_ATR_MULT`).
- **ATR trailing tuning harness:** `engine/backtest/tune_trailing_stop.py`,
  `engine/backtest/test_trailing_stop.py`, `engine/tests/test_trailing_stop_manager.py`.
- **EMA/MA cross entries:** `engine/backtest/signals.py`, `adx_ema_signals.py`,
  `engine/strategy_c/mtf_filter.py` (the two approved paper strategies are SMA-cross
  trend systems — MES SMA(60,200), MGC SMA(50,120)).
- **`reduce_only` close-only stop semantics:** covered by the OMS
  `update_stop_loss` path in `trailing_stop_manager.py`.

So do **not** port the strategy. The only genuine engine-level opportunity is the
`nautilus_trader` dependency itself: we pay its install/wheel weight for nothing today.
Two honest options — pick one:
  1. **Adopt for a parity harness** — use `BacktestEngine` as a *second, independent*
     backtest implementation to cross-check the custom `Backtester`. Value = the
     testing.md "live vs. backtest parity" rule already asks for this; a differential
     test (same signals, both engines, compare fills/PnL) would catch look-ahead or
     fill-model bugs in our vectorized path. This is real but non-trivial (tick data
     wrangling, instrument definitions, venue config).
  2. **Drop the dep** — if we're not going to use it, remove it from
     `requirements*.txt` to cut install surface and supply-chain exposure.

Flag: adopting (1) touches only research/backtest code, **not** `engine/risk/` or
`engine/config.py`, so no `[safety-review]` tag needed — but any change that lets a
Nautilus run *drive* a paper order would be Tier-3 and is explicitly out of scope here.

### 2. Project rules
`dedup-rules` — `.claude/rules/testing.md` already encodes the "No look-ahead bias /
live-vs-backtest parity" discipline (DeepFund citation). Nautilus is a concrete tool
that *supports* that rule but adds no new rule text.

### 3. Project skills
`no-fit` — nothing here is a reusable Claude workflow. Existing `backtest-report` /
`mcpt-validation` skills already cover backtest interpretation.

### 4. Slash commands
`no-fit`.

### 5. Subagents
`no-fit` — `backtest-runner` already covers backtest execution/analysis.

### 6. Docs
`partial-integrate` (small) — worth a one-paragraph note in
`docs/repo-integrations/` (this file) plus, if option 1 is chosen, a short runbook on
running the parity harness. The example's design lesson — *one strategy object, backtest
and live identical* — is a useful architectural reference point even if we never adopt
the framework, because our current split (`backtester.py` for research vs.
`trailing_stop_manager.py` for live) is exactly the divergence Nautilus is built to
avoid. Currently the backlog entry (`docs/research-backlog-from-discord.md:406`) lists
the repo at P=4/R=1/F=4 with no resolution; this doc resolves it.

### 7. Dev tooling
`partial-integrate` — the dependency-hygiene finding lives here: a pinned, unused,
LGPL, Rust-compiled dependency is exactly the kind of thing a `pip-audit` / unused-import
CI check should flag. Recommend a decision (use or drop) rather than leaving it pinned.

### 8. Dashboard
`no-fit`.

### 9. Ops / messaging
`no-fit`.

## Integration plan

This produces a **decision proposal**, not a code merge. Two mutually exclusive paths:

**Path A — Adopt as a parity/differential backtest harness (effort M-L)**
1. Keep `nautilus_trader` pinned; add `engine/backtest/nautilus_parity.py` that wraps an
   existing signal set (e.g. MES SMA trend) into a minimal Nautilus `Strategy`.
2. Add `engine/tests/test_backtest_parity.py`: run the same instrument/period through
   both the custom `Backtester` and Nautilus; assert trade count and net PnL agree within
   a tolerance. Divergence beyond tolerance = a bug in one engine (that IS the value).
3. Do **not** wire Nautilus into any live/paper order path — research only.

**Path B — Remove the dead dependency (effort S)**
1. Delete `nautilus_trader==1.211.0` from `engine/requirements.txt:36` and
   `requirements-core.txt`.
2. Confirm no import breaks (grep already clean).
3. Note the removal so a future backlog re-scan doesn't re-add it blindly.

Recommendation to user: **Path A is the higher-value move** given testing.md already
mandates live/backtest parity and we currently have no second engine to check the custom
`Backtester` against — but it costs real time. If no one will build the harness soon,
**Path B** stops us carrying an LGPL Rust dependency we never call. Do **not** copy any
code from the example file itself (see license note).

## License & attribution

**LGPL-3.0.** Two distinct concerns:
- **Importing the library** as a dependency (Path A) is fine — LGPL permits use/linking
  without relicensing our code, which is why it's already in `requirements.txt`.
- **Copying source** out of the repo (the example file, the `EMACrossTrailingStop`
  class, any `nautilus_trader/` module) into our tree would pull LGPL obligations onto
  that file. **Do not copy Nautilus source.** Re-implement ideas from scratch (we
  already have) or import the packaged library — never paste.

Attribution: if Path A ships, note "cross-checked against NautilusTrader (LGPL-3.0)" in
the parity harness file header and commit message. No attribution needed for Path B.

## Effort estimate

- Path A (parity harness): **M–L** (2-8hr to a first differential test; L if tick-data
  wrangling for our futures instruments is fiddly).
- Path B (drop dep): **S** (<30min).

## Red flags

- **LGPL-3.0** — do not copy source; import-only. (Not a blocker for use, is a blocker
  for paste.)
- **Rust-compiled dependency** — `nautilus_trader` ships native wheels; pinning it means
  carrying that build/supply-chain surface. Justified only if we actually use it.
- **Instrument mismatch** — the example is Binance **spot crypto** (CASH account, tick
  bars). Our book is CME **micro futures** (MES/MGC, 1h bars, IB Gateway). Any Nautilus
  adoption needs futures instrument definitions and a margin/OMS config that matches our
  reality — the example is not copy-paste applicable.
- **Not a strategy contribution** — treating this as "a new EMA-cross strategy to add"
  would be pure duplication of `backtester.py` + `trailing_stop_manager.py`. The value is
  the framework/parity angle, not the signal.
