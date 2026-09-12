# Strategy registry — initial seed provenance

**Date:** 2026-09-12
**Seeded by:** docs PR `docs/strategy-registry-schema-20260912` (reference-repo
consolidation loop, wave 3)

## Seed sources

| Entry | Source of truth | Verdict at seed time |
|---|---|---|
| `spy_atrband_breakout_rank1` | `docs/research/SPY_atrband_rank1.gate_v2.json` | FAIL (mc_95th_dd 27.41% > 6.0; dsr 0.0) |
| `spy_sma12_momentum_rank1` | `docs/research/SPY_sma12momentum_rank1.gate_v2.json` | FAIL (mc_95th_dd 21.91% > 6.0) |
| `spy_overnight_hold_rank1` | `docs/research/SPY_overnighthold_rank1.gate_v2.json` | FAIL (mc_95th_dd 23.21% > 6.0) |
| `qqq_sma12_momentum_rank1` | `docs/research/QQQ_sma12momentum_rank1.gate_v2.json` | FAIL (mc_95th_dd 33.65% > 5.0; dsr 0.0) |
| `tsla_sma12_momentum_rank1` | `docs/research/TSLA_sma12momentum_rank1.gate_v2.json` | FAIL (pf_ci 1.08 < 1.1; mc_95th_dd 86.83% > 5.0; dsr 0.0) |
| `aapl_sma12_momentum_rank1` | `docs/research/AAPL_sma12momentum_rank1.gate_v2.json` | FAIL (mc_95th_dd 75.56% > 5.0; dsr 0.0) |
| `mes_sma50200_atr_trend` | Root `CLAUDE.md` (live MES SMA(50,200)+2×ATR trend strategy) + CURRENT_STATE.md PRB-02 banner | paper-shadow; live `/paper/validation/approved-paper-gates` showed `overall_pass: false` for MES as of 2026-07-29 (pf 1.79 < 2.0 target; win_rate 43.75% < 55%) |

## Notes

- All six equity cards are x-bookmark edge-scan research artifacts (2026-07-02 scan
  and 2026-08-15 GT-52 validation-gap fills). Their cards state explicitly:
  "Draft/research only — does NOT authorize paper routing." The registry records
  them as `rejected` with the gate card as evidence.
- The equity cards report metrics per configuration inside the card file; the
  registry entries intentionally do not restate per-config numbers — the card file
  is the evidence and the registry links it.
- The MES entry's gate data comes from the PRB-02 banner in
  `docs/CURRENT_STATE.md` (2026-07-29), the most recent written snapshot of the
  live eligibility endpoint. It is marked `as_of` in the entry and must be
  refreshed against the live endpoint before any state change.
