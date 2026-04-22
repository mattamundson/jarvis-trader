# OB Omega Keltner Channels (30m) — ThinkScript Study

**File**: `shared_shared_OB_OMEGA_30m7STUDY.ts`

**Author**: OB Style (Maverick & Renegade, Feb 2020) / Keltner variant

**JARVIS Layer**: 4 Entry (30m aggregation)

**Status**: Ported to Python `engine/backtest/indicators.py::keltner_channels`

**Panel**: Upper (price chart overlay)

---

## Purpose

The **OB Omega Keltner Channels (30m)** provides dual-band entry levels for the 30-minute timeframe. It extends the 5m/15m OB Omega logic to longer-term intraday trades while retaining the same two-factor band structure:

- **Inner Band (1.5x factor)**: Moderate extension signal
- **Outer Band (2.0x factor)**: Significant extension signal

This study bridges the gap between aggressive short-timeframe entries (5m/15m) and swing-oriented trades (daily/weekly). Useful for traders who want confirmation at multiple aggregation periods or need alignment across a 3-layer structure.

---

## JARVIS Mapping

In the JARVIS 5-layer framework, Keltner channels fill **Layer 4 Entry Timing**:

| JARVIS Signal | TOS Equivalent | Interpretation |
|---|---|---|
| `kelt_1p5x_touch` | Price crosses Inner Band (1.5x upper) | Moderate extension — consider partial entry or scaling |
| `kelt_2p0x_touch` | Price crosses Outer Band (2.0x upper) | Significant extension — high-confidence entry signal |
| `kelt_basis` | Middle line (SMA 20) | Pullback target and regime anchor |

The 30m version is **less aggressive** than the 5m variant. Use it when:
- 5m/15m charts show chop or noise
- You want to hold longer (30m bars = ~6-10 hour positions depending on liquidity)
- You need multi-timeframe confluence (5m entry confirmation + 30m trend structure)

---

## TOS Inputs (Configurable Parameters)

| Parameter | Default | JARVIS Value | Notes |
|---|---|---|---|
| `period` | AggregationPeriod.thirty_MIN | 30m | Change to HOUR, DAY, etc. for different timeframes |
| `factor` | 1.5 | 1.5 | Inner band multiplier — ATR × 1.5 |
| `factor2` | 2.0 | 2.0 | Outer band multiplier — ATR × 2.0 |
| `length` | 20 | 20 | SMA period for basis and True Range |
| `lineLength` | 50 | 50 | Visual line segment length (right edge bars to display) |
| `ShowLabel` | YES | YES | Toggle timeframe labels ("30min Top", "Daily Bottom") |
| `ShowCloud` | YES | YES | Toggle shaded cloud between bands |
| `ShowClosedDoor` | NO | NO | MACD-gated "closed door" cloud (when MACD < 0 upper, > 0 lower) |

---

## Visual Elements

**Lines & Bands**:
- **Upper_Band1** (1.5x, color 2 — typically blue): Inner resistance band
- **Upper_Band2** (2.0x, color 3 — typically red): Outer resistance band
- **Lower_Band1** (1.5x lower, color 2): Inner support band
- **Lower_Band2** (2.0x lower, color 3): Outer support band
- **Avg** (dashed, color 1 — typically white): SMA 20 basis (pullback target)

**Labels**:
- Timeframe indicator at the right edge: "30min Top" / "30min Bottom" (auto-calculated from aggregation)
- Automatically adjusts label text if `period` input is changed to HOUR, DAY, etc.

**Clouds**:
- Gray cloud between 1.5x and 2.0x bands (shows "channel width")
- MACD-gated cloud (red) on oversold/overbought closes (optional; toggle `ShowClosedDoor`)

---

## Install

### Step 1: Import the Study
1. Open ThinkOrSwim
2. Go to **Studies > Edit Studies > Create**
3. Paste the entire contents of `shared_shared_OB_OMEGA_30m7STUDY.ts`
4. Click **OK** and name it "OB Omega 30m"

### Step 2: Add to Chart
1. Open a chart at 30-minute aggregation (e.g., /MES, SPY, MNQ)
2. Click **Studies > Add Study > My Studies > OB Omega 30m**
3. Adjust inputs in the study settings:
   - `period` = AggregationPeriod.thirty_MIN (or HOUR for daily context)
   - `ShowCloud` = YES for visual reference

### Step 3: Alerts (Optional)
Create price-level alerts at the band crossovers:
1. Right-click chart at a level line (Upper_Band1 or Upper_Band2)
2. Select **Add Alert**
3. Set sound (e.g., Ding for 1.5x, Bell for 2.0x) and notification preference

---

## Alerts

| Signal | TOS Condition | Action |
|---|---|---|
| Inner band touch (1.5x up) | Close crosses above Upper_Band1 | Consider scaling in; watch for reversal |
| Outer band touch (2.0x up) | Close crosses above Upper_Band2 | High-probability entry (ENTRY_NOW candidate) |
| Basis support | Close bounces off Avg | Pullback trade entry or stop-loss level |
| Outer band touch (2.0x down) | Close crosses below Lower_Band2 | High-probability short entry |

---

## Known Limits / Gotchas

1. **Aggregation Mismatch**: If your chart is set to 15m but `period` input is 30m, the bands will lag your chart by 2 bars. Always match: chart TF = `period` input.

2. **Timeframe Labels**: The label calculation assumes `period` is an even multiple of 60 (minutes). If you set `period` to an exotic value (e.g., 37min), the label math breaks and shows garbage. Stick to standard TF: 5m, 15m, 30m, 1h, 4h, daily.

3. **MACD Primer Cloud**: The MACD cloud (red/gray) gates the "closed door" signal, which only fires when MACD is in opposite territory. This is a noise filter, but it can delay signals by 1-2 bars during noisy consolidation.

4. **Basis as Stop Loss**: The SMA 20 (Avg line) is NOT a hard stop; it's a reference level. JARVIS typically uses **0.70 ATR** as the hard stop. Use the basis as a **regime anchor** only.

5. **Multiple Timeframes**: If you're running 5m, 15m, and 30m Keltner variants simultaneously, use the **outer band (2.0x) on 30m as a confirmation filter** for 5m/15m entries. Do not enter on 5m alone if 30m shows price still in 0.5x–1.5x range (less extension).

6. **Cross-Reference**: For the dual-factor (1.5x / 2.0x) Omega variant on other timeframes, see:
   - 5-minute: `ob_omega_keltner_5m.md`
   - 15-minute: `ob_omega_keltner_15m.md`

---

**Status**: Production ported. Python counterpart verified in `engine/backtest/indicators.py::keltner_channels(factor=1.5)` and `keltner_channels(factor=2.0)`.
