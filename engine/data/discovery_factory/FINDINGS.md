# Discovery-factory findings

_53 specs synthesized | 2 deployable PASS (>= 30 trades) | 1 under-sampled PASS | 9 near-miss (FAIL w/ adequate sample, PF>=1.10, DSR>=0.10)_

```
LABEL                      VERDICT             TRADES   PF_LO  P_EDGE     DSR    DD% WFO      
----------------------------------------------------------------------------------------------
MNQ_sma_trend_15m          PASS                   186   1.297   0.778   1.000   3.77 STRONG    !DNT
MGC_sma_trend_dd_mid_5m    PASS                   525   1.385   0.750   1.000   4.00 STRONG   
MES_rsi_breakout_15m       PASS                     5   1.478   1.000   0.972   0.29 STRONG   
MGC_sma_trend_rv_1h        FAIL                    33   1.843   0.667   1.000   0.92 MODERATE  *
MGC_sma_trend_rv_t2_PROBE_1h FAIL                    33   1.843   0.667   1.000   0.92 MODERATE  *
MGC_sma_trend_rv_t3_PROBE_1h FAIL                    53   1.677   0.722   1.000   1.59 MODERATE  *
MGC_donchian_15m           FAIL                   243   1.533   0.667   1.000   5.55 MODERATE  *
MGC_sma_trend_1h           FAIL                    41   1.452   0.529   1.000   1.98 WEAK      *
MGC_donchian_dd_hi_15m     FAIL                   282   1.459   0.667   1.000   4.17 MODERATE  *
MGC_sma_trend_5m           FAIL                   388   1.254   0.833   0.792   5.77 STRONG    *
MNQ_sma_trend_5m           FAIL                   388   1.177   0.636   0.700   5.43 MODERATE  * !DNT
MGC_sma_trend_dd_5m        FAIL                   503   1.329   0.583   0.398   5.42 MODERATE  *
MGC_donchian_5m            FAIL                   353   1.314   0.750   0.000   5.61 STRONG   
MGC_sma_trend_rv_mid_PROBE_1h FAIL                    38   1.778   0.611   0.000   1.26 MODERATE 
MGC_sma_trend_rv_t4_PROBE_1h FAIL                    70   1.607   0.632   0.000   1.59 MODERATE 
MES_sma_trend_1h           FAIL                    20   1.565   0.571   0.000   0.98 MODERATE 
MGC_donchian_dd_lo_15m     FAIL                   211   1.381   0.750   0.000   2.60 STRONG   
MGC_donchian_dd_15m        FAIL                   247   1.350   0.667   0.000   4.05 MODERATE 
MGC_sma_trend_dd_lo_5m     FAIL                   350   1.245   0.750   0.000   2.23 STRONG   
MGC_sma_trend_15m          FAIL                   293   1.116   0.583   0.000   5.37 MODERATE 
MGC_sma_trend_dd_15m       FAIL                   140   1.007   0.636   0.000   2.14 MODERATE 
MGC_sma_trend_rv_5m        FAIL                   302   1.001   0.583   0.000   5.69 MODERATE 
MGC_sma_trend_rv_15m       FAIL                   178   0.991   0.583   0.000   5.17 MODERATE 
MGC_bollinger_rsi_1h       FAIL                   173   0.981   0.500   0.000   5.33 WEAK     
MES_donchian_5m            FAIL                   238   0.940   0.700   0.000   5.83 MODERATE 
MNQ_bollinger_rsi_5m       FAIL                   263   0.911   0.636   0.000   5.87 MODERATE  !DNT
MES_atr_channel_1h         FAIL                   267   0.891   0.500   0.000   4.28 WEAK     
MES_sma_trend_rv_5m        FAIL                   266   0.885   0.600   0.000   5.66 MODERATE 
MNQ_donchian_5m            FAIL                   353   0.885   0.727   0.000   5.69 MODERATE  !DNT
MNQ_donchian_breakout_15m  FAIL                   806   0.774   0.545   0.000   5.48 WEAK      !DNT
MES_orb_15m                FAIL                   186   0.732   0.444   0.000   5.42 WEAK     
MES_sma_trend_15m          FAIL                   409   0.728   0.500   0.000   5.61 WEAK     
MES_donchian_1h            FAIL                   201   0.689   0.350   0.000   3.36 WEAK     
MES_sma_trend_rv_15m       FAIL                   234   0.666   0.389   0.000   5.42 WEAK     
MNQ_donchian_15m           FAIL                   220   0.656   0.364   0.000   5.43 WEAK      !DNT
MGC_bollinger_rsi_15m      FAIL                   291   0.650   0.333   0.000   5.76 WEAK     
MGC_donchian_breakout_1h   FAIL                   660   0.621   0.400   0.000   5.13 WEAK     
MGC_atr_channel_1h         FAIL                   307   0.619   0.300   0.000   5.65 WEAK     
MES_donchian_15m           FAIL                   360   0.596   0.333   0.000   5.92 WEAK     
MES_atr_channel_15m        FAIL                   456   0.593   0.333   0.000   5.78 WEAK     
MNQ_bollinger_rsi_15m      FAIL                   184   0.579   0.364   0.000   5.54 WEAK      !DNT
MNQ_orb_15m                FAIL                   102   0.576   0.429   0.000   3.96 WEAK      !DNT
MES_sma_trend_5m           FAIL                   200   0.574   0.500   0.000   5.57 WEAK     
MNQ_donchian_breakout_5m   FAIL                   769   0.535   0.273   0.000   5.36 WEAK      !DNT
MES_bollinger_rsi_15m      FAIL                   295   0.515   0.389   0.000   5.65 WEAK     
MES_donchian_breakout_15m  FAIL                   788   0.510   0.111   0.000   5.45 WEAK     
MGC_donchian_breakout_5m   FAIL                   623   0.490   0.250   0.000   5.56 WEAK     
MGC_bollinger_rsi_5m       FAIL                   232   0.480   0.333   0.000   5.68 WEAK     
MGC_orb_15m                FAIL                    53   0.417   0.143   0.000   5.50 WEAK     
MES_bollinger_rsi_5m       FAIL                   182   0.409   0.273   0.000   5.93 WEAK     
MGC_donchian_breakout_15m  FAIL                   667   0.369   0.167   0.000   5.33 WEAK     
MES_donchian_breakout_5m   FAIL                   255   0.153   0.000   0.000   5.44 WEAK     
MES_sma_trend_rv_1h        INSUFFICIENT_SAMPLE     17   0.658   0.455   1.000   0.92 WEAK     
```

`*` = near-miss watchlist.


## Caution -- under-sampled PASS (NOT candidates)

These cleared the gate metrics but on **< 30 OOS trades**, so the result is statistical noise, not an edge -- treated as INSUFFICIENT_SAMPLE and **not** briefed for promotion: MES_rsi_breakout_15m (n=5).


## Candidate briefs (PASS, sample-adequate)

### CANDIDATE: MNQ_sma_trend_15m  (passed_via=alt)

> **⛔ MNQ IS ON THE LIVE `DO_NOT_TRADE_SYMBOLS` BLOCK LIST.** Passing the discovery gate does NOT lift that block. This combo cannot be promoted to live/paper without first resolving why MNQ is barred (see signals.DO_NOT_TRADE_SYMBOLS / rules/jarvis-trader.md) -- a separate, explicit human decision.

- **Symbol / family / interval:** MNQ / sma_trend / 15m
- **Champion params:** `{"atr_trail_mult": 2.0, "fast": 8, "slow": 24}`
- **Found on cache:** `MNQ_2025-04-09_2026-06-12_15m_cont.csv`
- **Sample:** 186 OOS trades (adequate=True)
- **Gate metrics:** pf_ci_lower=1.297, p_edge=0.778, dsr=1.000, mc_95th_dd=3.77%, wfo=STRONG, cost_survives=catastrophic

> Research candidate only. Promotion to live/paper is a **human** decision (Phase 1 unified config) -- the factory never writes gate_v2_verdicts/.

### CANDIDATE: MGC_sma_trend_dd_mid_5m  (passed_via=alt)

> ⚠️ **Razor-thin drawdown margin:** mc_95th_dd=4.00% clears the 4% ALT ceiling by <0.1pp -- a coin-flip from FAIL, not robust headroom.

> ⚠️ **Sizing-tuned pass:** this spec was found by lowering `risk_per_trade` to fit the drawdown budget. The `max_drawdown=0.05` breaker couples size to per-window champion selection, so dsr and mc_95th_dd are non-monotonic in size -- a pass at one size is a knife-edge artifact unless it holds across a BAND. Verify against the size band before trusting (see DRAWDOWN_ATTACK_FINDINGS.md).

- **Symbol / family / interval:** MGC / sma_trend_dd_mid / 5m
- **Champion params:** `{"atr_trail_mult": 1.5, "fast": 12, "slow": 48}`
- **Found on cache:** `MGC_2025-03-27_2026-06-12_5m_cont.csv`
- **Sample:** 525 OOS trades (adequate=True)
- **Gate metrics:** pf_ci_lower=1.385, p_edge=0.750, dsr=1.000, mc_95th_dd=4.00%, wfo=STRONG, cost_survives=pessimistic

> Research candidate only. Promotion to live/paper is a **human** decision (Phase 1 unified config) -- the factory never writes gate_v2_verdicts/.
