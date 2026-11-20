# External research: balance vs trend day + 0DTE sell-vs-buy premium

**Collected:** 2026-11-06 ~00:40 America/Chicago  
**Sources:** GitHub, X (public search), Reddit (via web index + thread URLs), vendor/academic pages.  
**Scope:** Public rules that claim to predict ES/SPX *balance (range) days vs trend days*, and/or when to *sell 0DTE premium vs buy it*.  
**Sibling note:** Do not edit `regime_score.py` here. Candidate predictors/labels for that script are listed at the end.

Evidence grades used below:
- **Evidence-backed:** published sample size + metrics (backtest, academic, or deflation/OOS), or textbook/academic day-type taxonomy with quantified frequency.
- **Mechanistic / vendor:** coherent market-structure story with case studies; not an independent OOS backtest we verified.
- **Anecdote:** trader post, Reddit/X tip, no reproducible sample.

---

## Top findings (concise)

### 1. Narrow Initial Balance → higher trend-day odds (Dalton / Market Profile)
- **Rule:** IB = first hour RTH high−low. Narrow IB is an unstable base → higher odds of range extension / trend day. Wide IB → more likely normal / trading-range day that holds extremes. Trend days often follow quiet/narrow prior sessions (NR4/NR7/inside day). Open types (drive / test-drive / rejection-reverse / auction) bias the day early.
- **Evidence:** Textbook taxonomy (Dalton *Mind Over Markets*). Firich (2012) WSEAS paper classifies day structures from IB and reports **trend days ≈ 9.54%** of sample; recommends preparing for IB breakout when IB is small. LuxAlgo day-type taxonomy restates the same indicators.
- **Grade:** Evidence-backed (taxonomy + academic frequency); not a modern ES walk-forward classifier.
- **Testable on our data:** Yes — ES 1m bars → IB range vs 20d ATR/avg range; prior-day NR/inside; Dalton open type from first 15–30m; one-sided IB extension.
- **URLs:**
  - https://time-price-research-astrofin.blogspot.com/2023/03/six-types-of-market-days-mind-over.html
  - https://www.luxalgo.com/library/concept/day-type-taxonomy/
  - https://www.wseas.us/e-library/conferences/2012/Zlin/FAA/FAA-12.pdf
  - http://www.aspenres.com/Documents/AspenGraphics4.0/Day_Structures.htm

### 2. Positive GEX / above gamma flip → mean-revert (sell premium); negative GEX → trend/expand (avoid selling / buy vol)
- **Rule:** Spot above gamma flip / net GEX > 0 → dealers buy dips/sell rips → compressed ranges, theta-friendly. Below flip / net GEX < 0 → dealers chase → wider ranges, breakouts harder to fade. Magnitude matters; GEX is regime, not direction.
- **Evidence:** SpotGamma product docs + support articles with mechanism and historical range charts; X/Reddit operators repeat the same rule. No independent multi-year OOS hit-rate table verified in this pass.
- **Grade:** Mechanistic / vendor (+ widespread anecdote). Strong prior for our GEX snapshots, not proven edge alone.
- **Testable on our data:** Partially — GEX history under `/workspace/tape/state/gex-history-*.jsonl` (short/stale risk). Can correlate signed GEX and distance-to-flip with next-session range/ATR and balance/trend labels.
- **URLs:**
  - https://spotgamma.com/what-is-gex-gamma-exposure/
  - https://support.spotgamma.com/hc/en-us/articles/15214161607827-GEX-Gamma-Exposure-Explained-What-It-Is-and-How-SpotGamma-Uses-It
  - https://spotgamma.com/market-gamma-futures-traders/
  - X example (anecdote): https://x.com/BuildwithPublic/status/2035082240229875904
  - X example (neg GEX killed IC): https://x.com/RealSPXSniper/status/2003572328660345231
  - Reddit live IC+GEX: https://www.reddit.com/r/options/comments/1kmlbnb/0dte_spx_ic_using_gex/

### 3. Academic 0DTE structure study (Vilkov) — short premium often looks good gross, dies after realistic costs
- **Rule (from paper/repo):** Evaluate 0DTE structures at fixed entry (e.g. 10:00 ET) held to close; condition on VIX / features for OOS tactical choice. Iron butterfly/condor can show **positive gross SR** and **negative net SR after costs** (post cost-correction). Conditional logistic / model-zoo timing can lift gross, but margin over costs is thin.
- **Evidence:** SPXW 0DTE, Sep 2016 – Jan 2026; public replication package. **Aug 2026 correction:** bid-ask was undercharged 100×; after fix, **no strategy/basket retains positive net Sharpe**. Treat older “profitable 0DTE IC” claims with extreme caution.
- **Grade:** Evidence-backed (best public academic package found).
- **Testable on our data:** Regime side yes (VIX, VIX9D, events, range labels). Full options P&L needs option tape we do not currently hold — use as design constraint (cost-aware) rather than replicate P&L.
- **URLs:**
  - https://github.com/vilkovgr/0dte-strategies
  - https://ssrn.com/abstract=4641356
  - Annotated paper excerpt: https://github.com/vilkovgr/0dte-strategies/blob/main/docs/paper/paper-annotated.md

### 4. Searched VIX “elevated only” gates for 0DTE IC can look great and still be overfit (Mechaniq Lab)
- **Rule tested:** Trade managed near-ATM SPX 0DTE IC only when VIX-open ≥ 17 or ≥ 20.
- **Evidence:** ~546 fillable sessions (2022-06→2026-05), fair cost model. In-sample U-shape (mid-vol danger zone, high-vol better) replicated by independent 1-day vol. Gated books lifted Sharpe ~4–5× vs always-on — then **failed** Deflated Sharpe (0.02 / 0.22 vs need ~0.95 @ N=30) and **PBO 0.43**. Spec killed before forward paper.
- **Grade:** Evidence-backed *negative* result — do not treat “VIX > X sell” as settled; if we gate on VIX, fix thresholds a priori and hold out.
- **Testable on our data:** Yes for *range/trend labels* vs VIX buckets (not options P&L). Warn sibling scorer against searching many VIX cuts on the same sample.
- **URL:** https://www.mechaniq.trade/lab/spx-0dte-vol-conditioned-condor-v1

### 5. Practitioner IC filters: mid-morning entry, VIX gate, premium floor, 25% PT / 2× stop; skip catalysts
- **Rule:** Avoid the open noise; enter after IB/range settles (~10:00–10:30 ET or later); optional VIX min/max; require minimum credit; take ~25% of credit; stop ~2× credit; exit before late-day gamma window; **no major event days** (CPI/FOMC/NFP).
- **Evidence:** Option Omega methodology post (how to backtest, not a published equity curve). Reddit r/thetagang “fade the extension”: wait 60m, skip catalysts, size shorts from ATM straddle SD at 10:30 — author claims 0 losses over last 70 days after mod (self-report). Older thetagang IC threads: 5–10δ, 2–3× stops, avoid last hour.
- **Grade:** Anecdote / methodology (useful checklist; not OOS proof). Aligns with waiting for IB before classifying day type.
- **Testable on our data:** Event skip + “minutes since open before classifying” + overnight/IB settled flags — yes. Credit/delta legs — need options data.
- **URLs:**
  - https://optionomega.com/blog/how-to-backtest-a-0dte-iron-condor-on-spx/
  - https://www.reddit.com/r/thetagang/comments/1q38vnj/update_0dte_spx_credit_spreads_fade_the_extension/
  - https://www.reddit.com/r/thetagang/comments/xn0986/anyone_here_been_successfully_selling_0dte_ic/
  - Checklist with VIX buckets (vendor): https://optionscout.ai/blog/0dte-spx-trading-checklist

### 6. VIX term structure / VIX1D as day-vol estimator
- **Rule A (thetagang):** Prefer selling when cash VIX is in **contango** vs longer tenors; **backwardation** (cash VIX > 3M VIX) = acute fear, both tails underpriced → caution for short premium.
- **Rule B:** Use **VIX1D** (or VIX/√252) to set expected move and place IC wings outside that move; one 2023 SPY IC write-up reported ~81% WR / ~28% return Apr–Sep 2023 with late-day entry (small sample; commenters noted VIX1D near close is mostly *next-day* vol).
- **Rule C (X/Reddit common):** “VIX < 17 sell ICs; VIX > 17 buy” — **anecdote**, conflicts with Mechaniq mid-vol danger zone and with rich-premium intuition.
- **Grade:** A = mechanistic anecdote; B = limited-sample backtest; C = anecdote (treat as hypothesis only).
- **Testable on our data:** Yes — we already load `vix_daily` and `vix9d_daily` in `build_dataset.py`. Proxy term structure with **VIX9D/VIX** ( >1 front-loaded fear; <1 calmer front). VIX1D not in tree yet — add if available.
- **URLs:**
  - https://www.reddit.com/r/thetagang/comments/1js6suc/volatility_levels_suggest_we_are_in_a_bear_market/
  - https://www.reddit.com/r/thetagang/comments/16usw13/performance_of_odte_spy_iron_condors_in_2023/
  - Quant Galore VIX1D IC sketch: https://www.quant-galore.com/p/the-state-of-volatility-address-vix
  - X anecdote VIX<17: https://x.com/BeyondOption/status/2053890783665627330

### 7. Range-day / IC day often precedes a trend day (mean-reversion hangover)
- **Rule:** After a successful iron-condor / pinned session, next day trend risk rises (vol compression → expansion alternation). Dalton/Firich also note wide value areas often followed by quieter rotation and vice versa.
- **Evidence:** X trader note; Market Profile alternation lore. Not quantified in this pass.
- **Grade:** Anecdote / qualitative.
- **Testable on our data:** Yes — lag features: yesterday label, yesterday range/ATR, yesterday close-in-range.
- **URL:** https://x.com/AheadoftheNews/status/1957881454047948932

### 8. GitHub tooling (for later replication, not new rules)
| Repo | What | Stars (approx) | Notes |
|------|------|----------------|-------|
| [vilkovgr/0dte-strategies](https://github.com/vilkovgr/0dte-strategies) | Academic 0DTE structures + VIX conditioning | — | Best evidence package; cost correction critical |
| [askosyrskiy/iron_fly](https://github.com/askosyrskiy/iron_fly) | SPX 0DTE iron-fly backtest desk | 1 | Fresh; Docker/tape replay |
| [brigoraoul/spy0dte-simulator](https://github.com/brigoraoul/spy0dte-simulator) | SPY/SPX 0DTE credit-spread simulator | — | Useful scaffold |
| [AlexCrescentini/backtest_spx_vanilla_options](https://github.com/AlexCrescentini/backtest_spx_vanilla_options) | Multi-leg SPX EOD backtester | — | DTE/delta configurable; EOD not true 0DTE path |
| [kniyer/spx0dte-strategies](https://github.com/kniyer/spx0dte-strategies) Monte Carlo findings | MC on historical day-move dist | — | **Weak** — extreme returns / not fill-realistic |

Market-profile GitHub search mostly noise (unrelated repos). Day-type logic lives in literature + Pine/LuxAlgo concepts more than starred classifiers.

---

## Evidence-backed vs anecdote (summary table)

| # | Finding | Grade | Sell-premium implication |
|---|---------|-------|--------------------------|
| 1 | Narrow IB → trend odds up | Evidence-backed | Do **not** sell wings until IB proves wide / held |
| 2 | +GEX / above flip → range | Mechanistic | Favors selling when GEX fresh & positive |
| 3 | Vilkov: IC gross≠net | Evidence-backed | Size/expectancy must include costs; don't trust gross WR |
| 4 | Searched VIX≥17 gate overfits | Evidence-backed (negative) | Fix VIX cuts a priori; deflate |
| 5 | Wait 60m / skip events | Anecdote+checklist | Operational filter, test as event+time features |
| 6 | VIX9D/VIX & VIX1D wings | Mixed | Term-structure ratio is testable; VIX<17 rule is not gospel |
| 7 | Balance→trend alternation | Anecdote | Lag labels as features |
| 8 | GitHub simulators | Tooling | Replication aids only |

---

## Candidate predictors for `regime_score.py` (do not implement here)

Concrete, testable features (prefer known pre-open or by T+30/T+60m):

### Pre-open / overnight
1. `ovn_range / atr20` — overnight high−low vs 20d RTH ATR  
2. `ovn_range / implied_move` — overnight vs event/straddle implied (when known)  
3. `gap / prior_range` — RTH open vs prior close, scaled  
4. `vix_close` — prior-day VIX  
5. `vix9d_vix_ratio` — VIX9D/VIX (>1 front fear / backwardation-ish; <1 calmer front)  
6. `event_flag` — NFP/CPI/FOMC (from `event_calendar.json`)  
7. `gex_sign` / `gex_net` / `dist_to_gamma_flip` — from GEX snapshots when fresh (<N hours)  
8. `prior_label` / `prior_range_atr` / `prior_close_pos` — balance→trend lag  
9. `prior_nr_flag` — prior day NR4/NR7/inside (Crabel / Dalton precursor)

### Opening / first hour (for a T+60 “confirm” score, not pre-open)
10. `ib_range / atr20` — **primary Market Profile feature**  
11. `ib_range / ovn_range`  
12. `open_type` — Dalton: `open_drive` | `open_test_drive` | `open_rejection_reverse` | `open_auction` (from first 15–30m directionality + reclaim)  
13. `open_drive_pts` — |close_30m − open| / atr  
14. `ib_break_onesided` — by 10:30, extension ≥ k×IB on one side only (matches existing label logic)  
15. `one_timeframing` — successive 30m HH/HL or LH/LL streak count  

### Labels to add / keep (alongside existing `labels.py`)
- Keep: `trend` | `balance` | `ambiguous` (primary + sensitivity variants) — already defined.  
- Add continuous: `range_atr = rth_range / atr20`, `close_pos ∈ [0,1]`.  
- Add optional Dalton day-type enum: `trend`, `double_distribution`, `typical`, `expanded_typical`, `trading_range`, `sideways` (map from IB width + extension sides + close location).  
- Add options-oriented binary (derived, not fitted): `premium_sell_ok_exante` = (no event) & (gex_sign>0 if fresh) & (vix9d_vix_ratio < 1) & (ib_range/atr20 > q_wide) — for evaluation only after features exist.  
- Do **not** search dozens of VIX thresholds on the train set without a deflated-Sharpe / holdout protocol (Mechaniq lesson).

### Data gaps called out
- Fresh GEX often stale in live context — age must be a feature or NaN gate.  
- No VIX1D series in regime data yet.  
- No 0DTE option quotes → score predicts *day type / range regime*, not IC dollars. Vilkov warns IC edge may not survive costs even if day-type is correct.

---

## X search notes (this pass)
Queries covered 0DTE iron condor + GEX/VIX/range/trend and Market Profile day types. Useful signal posts linked above; heavy noise from automated GEX dispatch accounts (`spxgexai`, etc.) repeating “wide 0DTE IC” under +GEX without metrics. Market Profile day-type query was dominated by promotional reposts of one Vtrender video — taxonomy taken from Dalton/Firich sources instead.

## Reddit notes (this pass)
Subreddits touched via web index: r/options, r/thetagang, r/Daytrading, r/FuturesTrading. Common operational consensus: skip catalysts, wait for open to settle, use expected-move / delta for wings, hard stops. Daytrading IB threads qualitatively match Dalton (narrow IB → expansion risk) without new statistics.

---

## Bottom line for the regime model
1. **Core testable edge candidates:** `ib_range/atr20`, `ovn_range/atr`, `vix9d/vix`, `gex_sign`(+age), `event_flag`, Dalton `open_type`, prior-day compression.  
2. **Sell-premium overlay** should require balance-leaning score **and** non-event **and** (if available) fresh +GEX — then still treat as paper until options P&L exists.  
3. **Distrust** single VIX cutoffs found by search; **trust** holdout + deflation.  
4. Strongest public *options* evidence says short 0DTE structures are fragile after costs (Vilkov correction) — day-type skill ≠ automatic premium-selling edge.
