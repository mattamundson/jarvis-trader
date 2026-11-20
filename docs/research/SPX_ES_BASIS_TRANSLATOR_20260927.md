# SPX-to-ES/MES Basis Translator — Validation

**Verdict: ACCEPT** · pure research utility; no data fetch or broker integration.

- Formula: `basis_theoretical = spot * (exp((r-q)*T)-1); translated strike = original strike + selected additive basis`
- Theoretical Loom example: SPX strike 7750 → **7808.5** ES using basis **58.54126443**.
- Fresh observed example: 7750 SPX → **7810.0** using observed **60-point** basis.
- Stale observed basis is rejected and falls back to theoretical carry.
- ES and MES translated price levels are identical; symbol/contract metadata remains distinct.
- Roll-window, expiry, staleness, synchronization, and strike-preservation tests are included.
- Functional validation uses the Loom example and deterministic cases; it is not a historical basis-forecast backtest and is not integrated into runtime.

```json
{
  "theoretical_near_loom_region_7800_7825": true,
  "observed_basis_maps_7750_to_7810": true,
  "observed_basis_value_is_60": true,
  "stale_observed_falls_back_to_theoretical": true,
  "es_mes_same_price_level": true,
  "roll_window_flagged": true,
  "original_strike_preserved": true
}
```

Raw evidence: `.hermes/artifacts/mes_ib_vwap_basis_20260927/phase3_spx_es_basis.json`.
