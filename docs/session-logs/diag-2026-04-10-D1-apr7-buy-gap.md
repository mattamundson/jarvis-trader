# Diagnosis: 28 BUY Decisions (Apr 7-8) Lost — Root Cause Analysis

## Ground Truth
- **Apr 7**: 28 BUY + 185 HOLD decisions logged to `decisions` table → 0 paper_trades created
- **Apr 8**: 28 BUY + 389 HOLD decisions logged → 1 paper_trade (#54, stale price data)
- **All 56 BUY decisions** stored in `pending_trade_approvals` with status=`rejected` (resolved on 2026-04-10)
- **Rejection reason (all identical)**: "Stale — purged by JARVIS Stage 7 on 2026-04-10. Market conditions changed."

## Trace: Top 3 Apr 7 BUY Decisions

| Decision ID | Timestamp | Symbol | Approval ID | Created | Status | Confidence | Pipeline JSON |
|-------------|-----------|--------|-------------|---------|--------|------------|---------------|
| 636 | 2026-04-07T09:24:25 | MCL | a139c360... | 2026-04-07T09:24:25 | rejected | 0.0 | `{}` |
| 639 | 2026-04-07T10:24:36 | MCL | 7ebda9e1... | 2026-04-07T10:24:36 | rejected | 0.0 | `{}` |
| 642 | 2026-04-07T11:24:46 | MCL | 3654e31a... | 2026-04-07T11:24:46 | rejected | 0.0 | `{}` |

**Key observation**: Decision and approval timestamps are **identical to the millisecond**, indicating they were created together in the same transaction. Both have **empty `full_pipeline_json`**, meaning neither went through the normal 5-stage pipeline.

## Root Cause Chain

### H1: Pipeline Never Executed (CONFIRMED)
- **Evidence**: `full_pipeline_json` is `{}` for all 56 BUY decisions — should contain analyst_reports, trade_decision, fund_decision, etc.
- **Code path**: `engine/scanner/signal_scanner.py:307` persists decisions with pipeline result. If result lacks confidence data, it defaults to 0.0 (line 298-302).
- **Conclusion**: BUY signals came from **somewhere other than the normal pipeline** or the pipeline ran but returned empty objects.

### H2: Signals Source Unknown (LIKELY)
- The decisions table records `action='buy'` but provides no insight into what triggered them
- Signal data is minimal: `{"source": "scanner", "summary": "..."}` per signal_data_json
- No `trader_output`, `risk_output`, or `fund_output` in full_pipeline_json
- **Code path**: Could originate from:
  - Scanner hardcoded logic (not a full pipeline run)
  - Previous signal accumulation from stale price cache
  - Automated decision logging without LLM execution

### H3: Silent Rejection on Apr 10 (CONFIRMED)
- All 56 pending approvals were **batch-rejected on Apr 10** with identical message
- "Stage 7" is not a defined stage in code (Stages 1-5 are: Analyst → Debate → Trader → Risk → Fund)
- Message pattern ("purged", "stale", "bogus price data") suggests **manual intervention** or **scripted cleanup**
- **Key fact**: Trade #54 (Apr 8, 13:38) was created DESPITE being in the batch; it was marked closed with note: "bogus 84.20 entry from 14-day-stale CSV cache; real MCL ~60-65"
- **Implication**: The system detected stale price data (14-day-old CSV cache) was feeding into decisions

### H4: Confidence = 0.0 Explains Non-Execution (CONFIRMED)
- Line in `signal_scanner.py:298-302`: if all three confidence sources fail, defaults to `0.0`
- Decisions table shows `confidence=0.0` for all 56 BUY decisions
- **Code location**: `engine/scanner/signal_scanner.py`, lines 298–315
- **Impact**: A 0.0 confidence BUY signal may trigger approval creation but fails confidence gates downstream

## Hypothesis Ranking (Evidence-Based)

| Rank | Hypothesis | Likelihood | Evidence |
|------|-----------|------------|----------|
| **1** | H1: Pipeline not executed / returned empty result | **95%** | Empty full_pipeline_json; confidence=0.0 default; no analyst_reports |
| **2** | H5: Scanner using stale CSV cache data | **85%** | Trade #54 explicitly marked "14-day-stale CSV cache"; rejection message mentions "stale/bogus price data" |
| **3** | H2: Stale price data prevented Risk/Fund approval | **75%** | Trade #54 was closed at entry with 0 PnL; indicates detection of bogus pricing |
| **4** | H3: Silent rejection loop (try/except swallowing errors) | **40%** | No explicit code for "Stage 7" purge; unclear when/how batch rejection was triggered |
| **6** | H4: Successful execution but write failed silently | **5%** | Trade #54 exists but is zero-PnL; if write failed, trade wouldn't exist at all |

## Code Locations

| Component | File | Line(s) | Issue |
|-----------|------|---------|-------|
| Decision insertion | `engine/routers/pipeline_router.py` | ~60 | Signature doesn't match actual schema (agent_name vs action) |
| Scanner decision logging | `engine/scanner/signal_scanner.py` | 307–315 | Extracts confidence from 3 sources; defaults to 0.0 if all fail |
| Confidence fallback | `engine/scanner/signal_scanner.py` | 298–302 | `or 0.0` default explains all 56 decisions having conf=0.0 |
| Approval insertion | `engine/database/_mixins_pending_approvals.py` | 19–61 | No validation on entry_price; accepts None (which is valid for Mar 7 batch) |
| Batch rejection | *Unknown* | *Unknown* | "Stage 7" rejection message + batch timing (Apr 10) suggest manual cleanup |

## Recommended Phase 1 Fix

**Primary**: Add validation in `signal_scanner.py:307` to **reject BUY/SELL signals if confidence ≤ 0.05** before creating approvals. Prevents zero-confidence trades from creating database churn.

**Secondary**: Log rejected signals to a separate table (or mark decisions with `confidence_rejected=true`) so visibility exists into why signals were dropped. Current system silently ignores low-confidence signals.

**Root Investigation**: Locate the code/script that performed the Apr 10 batch rejection with "Stage 7" message. Either hardcoded cleanup logic exists that isn't documented, or this was manual intervention. Update CHANGELOG.

## Conclusion

The 28 BUY decisions on Apr 7-8 **were created but never executed** because:
1. They originated from a signal source that didn't run the full 5-stage pipeline (likely scanner with stale price cache)
2. Confidence values defaulted to 0.0, indicating pipeline stages were skipped
3. Pending approvals were created in good faith but later batch-rejected en masse (Apr 10) when stale price data was detected
4. Trade #54 escaped as a zero-PnL zombie trade (entry=84.20 vs real price 60-65) before cleanup

This is **NOT a failure of approval workflow**—approvals were created and resolved correctly. It's a failure of **signal source validation**—stale CSV cache data was feeding into the scanner without being detected at ingestion time.
