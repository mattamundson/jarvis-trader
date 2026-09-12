# C-00 — Supplied ThinkScript Source-Integrity Baseline

**Plan:** JARVIS-MIP-1.0  
**Program:** C — Feature Engineering  
**Phase:** 0 evidence inventory for Phase 2 work  
**Safety class:** S0 research documentation  
**State:** IN REVIEW / NO DEPLOYMENT AUTHORITY  
**Objective:** Preserve and classify the exact owner-supplied source corpus before parity work.  
**Non-goals:** Compilation certification, Python parity, edge validation, or trading authorization.  
**Dependencies:** JARVIS-MIP-1.0 adoption; the 16-file owner-supplied corpus.  
**Contracts:** Exact bytes, `SHA256SUMS`, immutable variant IDs, and explicit `known_at`.  
**Owner mode:** Owner-supplied source; research engineer implementation; independent parity review.  
**Required verification rung:** E1 deterministic hash-manifest test for source identity.  
**Observed:** 2026-09-02

## Scope and evidence boundary

This inventory covers the 16 files supplied by the project owner. SHA-256 hashes below identify the exact reviewed bytes. The files were inspected directly; they were not assumed correct because similarly named repository files exist. The reviewed corpus is preserved under `research/source/thinkscript/supplied-2026-09-02/`; its manifest is `SHA256SUMS`, enforced by a deterministic unit test. Same-named files elsewhere in the repository are separate variants until byte differences are documented.

This baseline does not certify Thinkorswim compilation, formula parity with Python, causal availability, statistical edge, or deployment eligibility. Those are separate gates:

```text
source identified → compiles → formula parity → causal/PIT-safe
→ statistically validated → paper eligible → canary/live eligible
```

No supplied study is authorized for execution by this document.

## File-level disposition

| # | Supplied file | SHA-256 | Directly observed integrity finding | Required disposition |
|---:|---|---|---|---|
| 1 | `shared_mtftrendbarSTUDY.ts` | `563f19e249cfb342213bc6f88074d12087b52a43355ca2ab73221ead5a4364f7` | Reads a selectable higher aggregation and recursively trails CCI/ATR state. The current higher-timeframe bar can revise until it closes. | Preserve as a visual/reference variant. An executable port must define closed-bar availability and golden-vector the CCI, ATR, transition, and crossover behavior. |
| 2 | `NextSignalMomentumSTUDY.ts` | `aef21fe09c4374af1cb13a79bc69bf81d556e4f64be78dc2360cfdd2e74199af` | Contains Unicode en-dashes in arithmetic and curly quotes in labels, so native compilation is doubtful until tested. Its KAMA constants are `0.4` and `0.2222`, not standard 2/30-period KAMA constants. `InertiaAll` full-range modes and `HighestAll` are chart-wide constructs. | Quarantine from parity/deployment claims. First preserve the original bytes, create a compile-clean canonical source as a new version, and test exact nonstandard constants. Reject full-range regression modes as executable features. |
| 3 | `ThinkScript_study_20221016STUDY.ts` | `13e196d621e95213527f35c7d46d50dc2dc2c1bd66645e427abeb64b2817af1c` | Static-date anchored VWAP using cumulative typical-price×volume after the anchor. Anchor date/time and timezone semantics are implicit. | Candidate reference only. Define timezone, session, zero-volume handling, anchor identity, and reset policy before parity or backtest use. |
| 4 | `JARVIS_Calendar_Edges.ts` | `4fe2b218c089a0e1215c31ebc255a261641d26439b1e6caf0c334884626e4dba` | Historical last-day/pre-holiday classification reads the next bar with `[-1]`; live holiday eves are hard-coded only for 2026–2027. Its 2027 Juneteenth eve is also wrong: it uses Friday 2027-06-18, the observed holiday, instead of Thursday 2027-06-17, the actionable prior session. | Visual overlay only. Live/research logic must use a versioned exchange calendar known as of `decision_at`; do not port the future-bar classification or hard-coded list as production authority. |
| 5 | `AA_CoreyIBv1STUDY.ts` | `e05e75da18a9b41618c18db27bde1101c99cde908ae186b9cdcef27eab87a61a` | Builds the opening range recursively from 09:30 for a configurable duration, then plots completed levels and extensions. Several clouds reference developing daily highs/lows and are presentation logic. | High-priority causal reference for OR/IB. Golden-vector capture, freeze, first-known timestamp, session/timezone, and post-range extension behavior. Keep visual clouds out of executable features unless separately specified. |
| 6 | `shared_AA_CoreyTPOScorev2STUDY.ts` | `99c78b6bc2296db5d4452a83d2cb258ce9c072d8d6c3e4e3680ca3b143da055c` | Uses a developing `timeprofile` object for POC/VAH/VAL/profile extremes and derives targets/scores from those changing values. | Research/advisory until a point-in-time incremental profile implementation proves values as known on each bar. Never backfill final-session profile values onto earlier decisions. |
| 7 | `JARVIS_Calendar_Edges_README.md` | `89252257ee255d5077e137960482f7e316009aae77327b183992f10c23eeda32` | Usage documentation, not executable source. It repeats performance claims and the annual hard-coded-calendar maintenance requirement. | Retain as historical/source documentation. Validate every metric against immutable evidence bundles; do not treat prose as a verdict. |
| 8 | `COHEN_MES_STC_SUB.ts` | `ef6ee0edbf64208008533a7e6ac0d2c2388920afa98f6d110ec1974cbf565694` | Double-stochastic STC recursion smooths with `1 / smooth_factor`; default `smooth_factor=3` means alpha `1/3`. That is not equivalent to pandas `ewm(span=3)` alpha `1/2`. | High-priority exact-parity candidate. Version separately from existing standard/legacy STC variants and prove warmup, zero-range, recursion seed, clamp, and crossover parity with golden vectors. |
| 9 | `TRIN_ChetanSTUDY.ts` | `ef8f3190bdd9ba38c61ab6ae13b17ef34ab081bcaa709dd053484feffde8d3e9` | Price coloring combines `$TRIN` current/low conditions with `VVIX` and `VIX`; it is not a TRIN-only classifier. Cross-symbol publication/alignment semantics are unspecified. | Advisory context only until all three inputs have provider, timestamp, session, staleness, and formula parity tests. Do not label a TRIN-only Python feature as this source’s port. |
| 10 | `Saty_Phase_OscillatorSTUDY.ts` | `74d75bd1f7d227ec66689742cee63e6f6fc384c8d0354432bf74738c18f58dc2` | The oscillator applies EMA(21) pivot, ATR normalization, and EMA(3) smoothing. Compression code contains Pine-style `ta.atr(14)`, which is not established as native ThinkScript syntax. | Split oscillator parity from compression parity. Preserve/verify the EMA(3) oscillator correction; select or reconstruct a compile-valid canonical compression source before claiming full-study parity. |
| 11 | `shared_shared_shared_shared_kelt_3.01STUDY.ts` | `041437688e002fdfd0cc52a03854a44dd82c7876da84c9186f5657c034f96678` | Multi-timeframe simple-average Keltner channel. Plot expressions use negative offsets when `iDisplace>0`, which are future references for presentation. Current higher-timeframe values revise until close. | Candidate normalized-extension feature only with `iDisplace=0`, closed higher-timeframe bars, and exact average/true-range semantics. Plot displacement is never executable input. |
| 12 | `shared_shared_OB_OMEGA_5mSTUDY.ts` | `dc825ead8dba812cbc02e602298d6f7f17f7f5faf0cf8342bfb1101dc581aed6` | Deliberately uses `HighestAll` and `[-lineLength]` to project current Keltner values as right-edge horizontal chart lines; includes an MTF MACD presentation cloud. | Presentation/advisory only. Extract Keltner/MACD formulas as separate causal features if useful; never port right-edge projection mechanics into backtests. |
| 13 | `shared_AA_CoreySinglefinderv2STUDY.ts` | `761f7bea56aafff5e77354d781f13312cb62dea2077f38fafd0d8083a6a2a698` | Pattern definitions and plotted levels use `high[-1]`/`low[-1]`. A bar’s “single” classification is therefore known only after the following bar. | Candidate only with explicit delayed availability: attach the feature to the pattern bar for display, but set `known_at` to the next bar’s close/availability and prohibit earlier execution. |
| 14 | `AA_CoreyGapfinderv1STUDY.ts` | `fc21226d4e40a60c4441d1e3bd1e4a787132da053d54ca2da1a3054efbf167d6` | Default gap comparison is prior close versus current open and is causal at the current bar, while recursive extensions are chart persistence. Session boundaries are not explicit. | Candidate after defining session/calendar, corporate-action/roll treatment, minimum gap, and `known_at`. Validate the detection separately from line-extension visuals. |
| 15 | `GAPS_Chetan1STUDY.ts` | `06f77fe254378998d95220b34959fe645a5187497725ac3de407f7ca6784da91` | Cyan tests `(low[1]-high)>0.10`; orange tests `(high[1]-low)<0.10`, which is true for many ordinary overlaps and is not a complementary gap-down predicate. HYG/SPX differences are computed but unused. | Reject as a production “gap” definition. Preserve for provenance only unless the author supplies intended semantics and labeled examples. |
| 16 | `ThinkScript_study_20230523STUDY.ts` | `3a33c24fbf153488ce105b417da3431b0b493427dca7fb6e28623387ef359566` | Traditional pivots use prior daily high/low/close, which is causal after that daily bar finalizes. `close(...)[-1]` is used only to hide non-current plots when `showOnlyToday` is enabled. | Candidate deterministic reference after defining the trading session/day boundary and using only finalized prior-session OHLC. Exclude display-hiding logic from features. |

## Immediate decisions

1. **Do not combine these studies as equal votes.** Several are overlays, chart-painting tools, or delayed classifications rather than independent alpha.
2. **Promote source identity before formulas.** Each implementation receives a stable variant ID and source hash; corrected source is a new version, never a silent replacement.
3. **Attach availability to every output.** At minimum record `event_at`, `available_at`, `computed_at`, `known_at`, bar/session state, and whether the higher-timeframe bar is final.
4. **Keep display semantics out of research semantics.** `HighestAll`, right-edge projections, bubbles, clouds, labels, displacement, and today-only hiding are not trading features.
5. **Invalidate contaminated evidence.** Initial Balance, VWAP, final-session TPO, future-referenced Singlefinder, displaced MTF features, or any other causal correction requires superseding affected verdicts and rerunning the complete evidence bundle.

## Phase-2 parity queue

| Priority | Variant | First acceptance target |
|---:|---|---|
| 1 | Corey Initial Balance / OR | No pre-range final values; developing and frozen states match controlled source bars. |
| 2 | RTH/session VWAP | Explicit exchange calendar and RTH reset; premarket/Globex bars excluded; exact controlled-bar cumulative values. |
| 3 | Static anchored VWAP | Explicit anchor/timezone and per-variant inclusion/reset policy; include every valid post-anchor bar selected by that policy, including overnight bars when specified. |
| 4 | Saty Phase oscillator | EMA(21) pivot + ATR normalization + EMA(3) output parity; compression kept separate until canonical source compiles. |
| 5 | COHEN STC | Alpha `1/3` recursion, seeds, zero-range branches, clamp, and crossovers match golden vectors. |
| 6 | NextSignal KAMA variant | Compile-clean source version; exact `0.4/0.2222` constants; no standard-KAMA relabeling. |
| 7 | TPO POC/VAH/VAL | Incremental profile values only; final values unavailable before session completion. |
| 8 | TRIN/VIX/VVIX context | All input timestamps/provenance aligned and stale/unavailable states fail closed. |
| 9 | MTF trend/Keltner | Closed higher-timeframe bars only; displacement/right-edge projection excluded. |
| 10 | Singlefinder | One-bar delayed `known_at` enforced in replay and live feature APIs. |
| 11 | Corey gap / traditional pivots | Explicit session boundaries and finalized source bars. |

## Required evidence bundle per variant

- exact source bytes and SHA-256;
- canonical variant ID and owner;
- compile result from Thinkorswim or an explicitly labeled unverified status;
- parameter/default manifest;
- controlled golden input bars and expected output values;
- Python parity receipt with tolerances and warmup rules;
- causal-availability tests, including pre-session and incomplete higher-timeframe bars;
- timezone/session/calendar/contract-roll policy;
- affected-strategy and affected-verdict inventory;
- supersession record and rerun IDs;
- deployment state kept separate from parity state.

## Exit condition

C-00 may be considered complete as a source inventory when the E1 manifest test proves the preserved corpus matches every recorded hash and review confirms that same-named repository variants are not silently substituted. It does not close any parity, causal-integrity, Judge, paper, canary, or live gate.
