# Saty ATR Levels — ThinkScript Study

**File**: `Saty_ATR_LevelsSTUDY.ts`  
**Author**: Saty Mahajan  
**JARVIS Layer**: Layer 1 Regime + Layer 5 Sizing  
**Status**: Ported  
**Python counterpart**: `engine/backtest/indicators.py::wilder_atr` + `ema_ribbon`  
**Panel**: Upper (price chart)

## Purpose

Saty ATR Levels is the foundational regime and sizing visualizer for JARVIS TRADER. It plots Wilder's ATR-based Fibonacci level extensions from the prior session close and overlays an EMA ribbon (8/21/34) to determine trend direction. The script answers two critical questions:

1. **What is the regime?** The EMA ribbon hierarchy (bullish = price ≥ ema8 ≥ ema21 ≥ ema34) tells you if the market is trending or neutral.
2. **What are the trade levels?** ATR multiples provide exact entry triggers, stop losses, and profit targets — eliminating guesswork.

This is your visual "map" during live trading. Every price level you see corresponds directly to JARVIS backtest entries and exits.

## JARVIS Mapping

The script implements two JARVIS functions:

- **Layer 1 Regime Detection** (`engine/backtest/indicators.py::ema_ribbon`):  
  Computes three EMAs (8/21/34) and compares their ordering to price to classify the regime as TRENDING_BULL or TRENDING_BEAR. Lines 52–53 of the .ts file encode this exact logic: `bullish = price >= fast_ema_value and fast_ema_value >= pivot_ema_value and pivot_ema_value >= slow_ema_value`.

- **Layer 5 Position Sizing** (`engine/backtest/indicators.py::wilder_atr`):  
  Wilder's ATR (period=14) is calculated from the prior session's true range and used to generate Fibonacci-scaled levels. JARVIS uses:
  - Stop loss: **0.70 ATR** (between 0.618 and 0.786 Fibonacci lines)
  - T1 target (1h): **1.50 ATR** (upper_1500 line)
  - T1 target (daily): **2.00 ATR** (upper_2000 white line)
  - T2 target: **2.618 ATR** (the golden ratio extension)
  - T3 target: **4.00 ATR** (calculate manually; beyond typical chart)

All levels are pre-calculated and plotted — you just read the price level from the chart.

## TOS Inputs

| Input | Default | JARVIS Value | Notes |
|---|---|---|---|
| `atr_length` | 14 | 14 | Wilder's period. Do not change. |
| `trading_type` | Day | Day (1h charts) | Controls aggregation period for ATR calc. Use "Day" for 1h charts, "Multiday" for daily charts. |
| `fast_ema` | 8 | 8 | Must match JARVIS ribbon. |
| `pivot_ema` | 21 | 21 | Must match JARVIS ribbon. |
| `slow_ema` | 34 | 34 | Must match JARVIS ribbon. |
| `trigger_percentage` | 0.236 | 0.236 | Call/put entry trigger = prior_close ± (0.236 × ATR). |
| `use_current_close` | no | no | Use prior session close (not current bar). Do not change. |
| `show_all_fibonacci_levels` | yes | yes | Shows intermediate levels (0.382, 0.5, 0.786). |
| `show_extensions` | no | yes | **Change to YES** to see 1.236×–3.0× levels (required for T2/T3 targets). |
| `use_options_labels` | yes | yes | Labels as "Calls"/"Puts" (or set to no for "Long"/"Short"). |
| `show_info` | yes | yes | Shows ATR value, range %, and entry level labels. |

## Visual Elements

**EMA Ribbon** (not plotted as lines by default; see label color):
- **Green label** (top of chart) = Bullish trend (price ≥ ema8 ≥ ema21 ≥ ema34)
- **Red label** = Bearish trend (price ≤ ema8 ≤ ema21 ≤ ema34)
- **Orange label** = Mixed/neutral (neither condition met)

**ATR Level Lines** (Fibonacci-scaled, all from prior close):
- **White lines** (strongest levels): Close level, ±1.0 ATR, ±2.0 ATR, ±3.0 ATR
- **Light gray lines** (0.618/1.618/2.618 ratio): Golden ratio extensions
- **Dark gray lines** (0.382, 0.5, 0.786, 1.236, etc.): Intermediate Fibonacci levels
- **Cyan line** (upper_trigger_level): +0.236 ATR (call entry for longs)
- **Orange line** (lower_trigger_level): -0.236 ATR (put entry for shorts)

**Info Labels** (upper left corner):
- Trend ("Bullish"/"Bearish"/"Mixed")
- Trading period (Scalp/Day/Multiday/Swing/Position/Long-term)
- Range consumed as % of full ATR (Green ≤70%, Orange 70–90%, Red ≥90%)
- ATR value in dollars
- Call/Put trigger levels with ATR values

## Install

1. **Open ThinkOrSwim** desktop application.
2. Go to **Charts** tab.
3. Click the **Studies** button (beaker icon, upper right).
4. Select **Edit Studies**.
5. Click the code bracket icon (`</>`) to open the **ThinkScript Editor**.
6. Click **Open** and navigate to `thinkorswim-scripts/Saty_ATR_LevelsSTUDY.ts`.
7. Click **Save As** and name it "Saty ATR Levels" (or any name you prefer).
8. Close the editor.
9. Back in **Edit Studies**, find "Saty ATR Levels" in the list and click **+** to add it to the chart.
10. A parameters dialog appears. Verify:
    - `trading_type` = Day (for 1h charts)
    - `show_extensions` = yes (to see T2/T3 targets)
    - `show_all_fibonacci_levels` = yes
11. Click **Apply**, then **OK**.
12. The ATR levels appear as horizontal lines on your price chart.

## Alerts

Create these alerts in TOS (**Right-click chart → Add Alert for Study Plot**):

| Signal | Alert Condition | Sound | Use |
|---|---|---|---|
| Bullish Regime | Label color turns GREEN | Optional: Ding | Confirms trend shift to bull |
| Bearish Regime | Label color turns RED | Optional: Ding | Confirms trend shift to bear |
| Range Consumed >90% | ATR % label turns RED | Optional: Bell | EXHAUSTED regime — consider fading extremes |
| Price crosses T1 target | Close > upper_1500_level | Bell | First profit target hit — take 50% |
| Price crosses stop | Close < lower_0618_level (approx) | Bell | Stop breach — exit position |

## Known Limits / Gotchas

- **Aggregation Period Lock**: The `trading_type` input determines the ATR calculation timeframe (Day = daily ATR, Multiday = weekly ATR, etc.). For intraday 1h trading, always use `trading_type = Day`. Changing it mid-session will recalculate ATR retroactively.

- **Prior Close Dependency**: All levels are anchored to the **prior session close**, not the current bar's close. This is intentional (look-ahead prevention). The `use_current_close = no` default is correct.

- **Fibonacci Spacing**: The levels follow the Golden Ratio sequence (1, 1.236, 1.382, 1.618, 1.786, 2.0, 2.236, etc.). Each pair of lines represents a Fibonacci percentage. JARVIS uses the 0.618, 0.786 (stop), 1.5 (T1), and 2.618 (T2) levels most frequently.

- **Extensions Off by Default**: If you don't see T2/T3 target levels, verify `show_extensions = yes` in the study parameters.

- **Weekend Gaps**: On Monday, the prior close is from Friday. Weekend gaps are not re-anchored. If a gap exceeds 3× ATR, manual level adjustment may be needed.

- **Pre-Market Use**: The script works in pre-market (4:00 AM ET), but ATR bands are based on the **prior day's close**, not pre-market action. Wait for 9:30 AM ET (market open) for the most relevant regime.
