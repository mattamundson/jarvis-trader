# MES Weekly-VWAP Acceptance — Research Verdict

**Verdict: REJECT** · retained features: `[]`.

Input: `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\backtest\cache\MES_2024-09-22_2026-05-29_5m_cont.csv` · SHA-256 `516beb11568f3270e595035b1dada669654c6b337f87b81b35fc386dff092a12`.

| feature | n | Brier model | price>VWAP | unconditional | diff vs price | CI | Holm p (price/uncond) | model exp. | baseline exp. | retained |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|---|
| `time` | 1068 | 0.566435 | 0.567764 | 0.565365 | 0.001329 | `[-0.000238, 0.003057]` | 0.422919/1.0 | 23.644378 | 22.609472 | False |
| `volume` | 1068 | 0.566434 | 0.567764 | 0.565365 | 0.00133 | `[0.000255, 0.002753]` | 0.08198/1.0 | 23.165153 | 22.609472 | False |
| `developing_vpoc` | 1068 | 0.565976 | 0.567764 | 0.565365 | 0.001788 | `[-0.003874, 0.007589]` | 1.0/1.0 | 24.045481 | 22.609472 | False |
| `developing_tpo_poc` | 1068 | 0.567545 | 0.567764 | 0.565365 | 0.000219 | `[-0.002117, 0.002411]` | 1.0/1.0 | 23.293203 | 22.609472 | False |
| `clv_delta_proxy` | 1068 | 0.566162 | 0.567764 | 0.565365 | 0.001602 | `[-0.002399, 0.005873]` | 1.0/1.0 | 14.771239 | 22.609472 | False |

The CLV/cumulative-delta field is an OHLCV proxy, not true bid/ask delta. No feature is retained unless paired OOS Brier clears both the price-above-weekly-VWAP and trailing-unconditional arms after Holm correction, while economics also beat the price>VWAP arm.

Data caveat: the stitched, non-back-adjusted continuous cache can distort developing weekly VWAP when a quarterly roll occurs inside the week. This study rejects every feature and makes no promotion claim.

Raw evidence: `.hermes/artifacts/mes_ib_vwap_basis_20260927/phase2_weekly_vwap_acceptance.json` and sidecars.
