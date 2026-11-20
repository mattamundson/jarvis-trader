# ES balance vs trend regime — findings

**Built:** 2026-11-06 00:43 America/Chicago
**Sample:** 992 RTH sessions (2022-12-30 → 2026-11-05) from Databento ES 1m + Yahoo recent.
**Live legal?** NO, size 0

## Label definitions

**Trend day** (primary): close in the outer 20% of the RTH range **and** range ≥ 1.2× the prior 20-day average range, **or** a one-sided Initial Balance breakout ≥ 1× the IB range.

**Balance day:** close inside the IB **or** in the middle 50% of the range, **and** range < 1× the 20-day average.

**Else:** ambiguous.

| Variant | Trend | Balance | Ambiguous |
|---------|-------|---------|-----------|
| primary | 0.421 | 0.292 | 0.286 |
| strict_trend | 0.393 | 0.292 | 0.315 |
| loose_trend | 0.458 | 0.292 | 0.25 |
| strict_balance | 0.421 | 0.279 | 0.299 |
| loose_balance | 0.421 | 0.303 | 0.275 |

Sensitivity is modest (trend ~39–46%). Results below use **primary**. Base: trend **42.1%**, balance **29.2%**.

## Top predictors

1. **open_type = open_drive** — trend 33.7% (lift -8.4%), balance 0.323, n=288, mean range/ATR=1.047
2. **dow = 0** — trend 33.8% (lift -8.3%), balance 0.343, n=198, mean range/ATR=0.888
3. **ib_atr = (-0.001, 0.35]** — trend 50.0% (lift +7.9%), balance 0.314, n=258, mean range/ATR=0.681
4. **ib_atr = (0.5, 0.7]** — trend 34.2% (lift -7.9%), balance 0.276, n=257, mean range/ATR=1.137
5. **open_drive_atr = (0.3, 0.5]** — trend 34.2% (lift -7.9%), balance 0.311, n=161, mean range/ATR=1.142

### Takeaways
1. **Narrow IB (`ib_atr` ≤ 0.35)** — trend 50% (Dalton). Stage-2 only (~09:30 CT).
2. **Day of week** — Monday 33.8% trend (balance lean); Wed/Thu ~48–49% (trend lean).
3. **Event days** — trend 50%, mean range/ATR 1.29. Skip short 0DTE through the print.
4. **Open type (empirical)** — `open_drive` lower trend (33.7%); auction/test-drive higher (~46–48%). Soft signal.
5. **Quiet overnight (`ovn_atr` < 0.5)** — mild balance lean; moderate 0.5–0.75 → higher trend rate.

**Weak/null:** gap_in_range, prior label, prior NR4/inside. **GEX:** only ~6–8 overnight-carry sessions — unavailable for fitting; live overlay only when fresh.

**Unavailable (never invented):** historical ATM straddles, NQ divergence beyond ~7d, VIX1D, multi-year GEX.

## Out-of-sample vs base rate

Walk-forward 60% expanding train, 4 folds, pre-open features:

| Metric | Value |
|--------|-------|
| OOS n | 396 |
| OOS trend rate | 0.379 |
| Majority baseline acc | 0.621 (always non-trend) |
| Logistic OOS acc | 0.583 (lift -0.038) |
| Depth-3 tree OOS acc | 0.475 (lift -0.146) |

Classifiers do **not** beat majority on hard accuracy. Edge is a **rate shift** in score buckets.

### Holdout score buckets (pre-open, last 40%)

| Bucket | Display | n | Trend | Balance | Mean range/ATR |
|--------|---------|---|-------|---------|----------------|
| low | 0-3 | 153 | 0.359 | 0.32 | 0.95 |
| mid | 4-6 | 149 | 0.342 | 0.376 | 0.982 |
| high | 7-10 | 95 | 0.474 | 0.253 | 1.162 |

High (raw≥3) ≈47% trend / 1.16×ATR. Low (raw≤0) ≈36% trend / 0.95×ATR. Modest but directional.

## VIX thresholds (overfit risk)

A priori buckets only — no searched cuts (Mechaniq: VIX≥17/20 IC gates failed deflated Sharpe / PBO 0.43).

| Bucket | Holdout | Train lift | OOS lift | OOS n |
|--------|---------|------------|----------|-------|
| <15 | YES | -0.064 | -0.105 | 40 |
| 15-20 | YES | 0.067 | 0.022 | 281 |
| 20-25 | YES | -0.052 | -0.029 | 57 |
| >=25 | FAILED | 0.142 | -0.012 | 19 |

**VIX≥25 failed holdout** → **0 points**. Still a live short-premium tail-risk flag.

## Scoring formula (display 0–10)

| Rule | Pts |
|------|-----|
| Event day | +2 |
| Wed/Thu | +1 |
| Monday | −2 |
| VIX < 15 | −1 (holdout OK) |
| VIX 15–20 | +1 (holdout OK) |
| VIX 20–25 | −1 (holdout OK) |
| VIX ≥ 25 | **0 (holdout FAILED)** |
| Quiet overnight ovn_atr<0.5 | −1 |
| Mod overnight 0.5–0.75 | +1 |
| OPEX | −1 |
| VIX chg ≥ +2 | −1 |
| Wide gap (≥0.5 prior range) | +1 |

Stage-2 (~09:30): narrow IB ≤0.35 ATR +2; mid-wide IB 0.5–0.7 −1; open_drive −1; auction/test-drive +1; OTF≥2 +1.

Display: raw≤−2→0; ≤0→2; ≤2→5; ≤4→7; else→10. Lookup = OOS bucket rates above.

## Premium rules

- **Avoid buying premium** when display ≤ 3 (balance lean) if you want decay on your side.
- **Avoid selling naked premium** when display ≥ 7, on event days, or when IB is narrow.
- **Selling favorable (conditional):** display ≤ 3, no event, IB mid/wide, defined risk only.
- **Net-of-costs (Vilkov):** Vilkov 0DTE study (SSRN 4641356 / github.com/vilkovgr/0dte-strategies): iron condors/butterflies can show positive GROSS Sharpe but after the Aug 2026 bid-ask cost correction, no strategy retains positive NET Sharpe. Day-type skill ≠ automatic premium-selling edge. Paper only until options P&L exists.

## Today — 2026-11-06 NFP

| Field | Value |
|-------|-------|
| Display 0–10 | **5** |
| Raw | 2 |
| Trend p | 0.342 |
| Balance p | 0.376 |
| Fired | event_day(2), mod_overnight(1), vix_spike(-1) |
| ovn_atr / VIX9D/VIX | 0.663 / 1.159 |

**Caveats:** NFP; VIX 28.18 (no fitted points, live tail risk); VIX +11.6 spike; GEX −51.7B stale; avg_range proxied from last 5 RTH only (includes 11/5 crash day); implied ±111 not in score.

**Advice:** MIXED: no strong pre-open edge. Prefer waiting for IB (09:30 CT stage-2) or staying flat.

Live legal? NO, size 0

## Files

- `/workspace/tape/system/regime/labels.py`
- `/workspace/tape/system/regime/features_extra.py`
- `/workspace/tape/system/regime/build_dataset.py`
- `/workspace/tape/system/regime/backtest.py`
- `/workspace/tape/system/regime/regime_score.py`
- `/workspace/tape/system/regime/findings.md`
- `/workspace/tape/system/regime/external_research.md`
- `/workspace/tape/system/regime/data/sessions_labeled.csv`
- `/workspace/tape/system/regime/data/sessions_meta.json`
- `/workspace/tape/system/regime/data/vix_daily_yahoo.json`
- `/workspace/tape/system/regime/data/vix9d_daily_yahoo.json`
- `/workspace/tape/system/regime/data/event_calendar.json`
- `/workspace/tape/system/regime/reports/backtest_results.json`
- `/workspace/tape/system/regime/reports/score_today.json`
- `/workspace/tape/system/regime/tests/`
