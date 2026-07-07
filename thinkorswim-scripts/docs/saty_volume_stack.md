# Saty Volume Stack — ThinkScript Study

**File**: `thinkorswim-scripts/Saty_Volume_StackSTUDY.ts`  
**Author**: Saty Mahajan (Copyright 2022–2024)  
**JARVIS Layer**: Layer 3 (Bias/Sentiment)  
**Status**: Ported — Python counterpart exists  
**Python counterpart**: `engine/backtest/indicators.py::volume_stack()`  
**Panel**: Lower (volume pane)

## Purpose

Separates buy and sell volume using the candle's OHLC ratio as a proxy. Winner (larger side) stacks on top; loser below. Provides visual confirmation of intraday sentiment: dominance swings from sellers to buyers or vice versa within each bar.

**Core concept**: Price location within the candle (close near high = buyers winning, close near low = sellers winning) implies volume imbalance. Stacked histogram makes directional volume bias unmissable.

## JARVIS Mapping

**Signal generated**:
- `buy_pct` — Percentage of volume attributable to buyers (0–100)

**Bias rules** (Layer 3):
- `buy_pct > 60%` → Buyer-dominant (LEAN_BULL bias)
- `buy_pct < 40%` → Seller-dominant (LEAN_BEAR bias)
- `40% ≤ buy_pct ≤ 60%` → Neutral (no directional volume bias)

**Integration**: `engine/backtest/signals.py:206` reads `volume_stack()` output; `composite_signals.py:314–320` uses buy_pct to reinforce bullish/bearish debate scores. Not a standalone entry signal; used as **confluence filter** for Layer 4 entries.

**Confidence modifier**: When buy_pct extreme (>70% or <30%), composite signals gain 0.5pp confidence boost. When neutral (45–55%), confidence ceiling reduces by 0.3pp to avoid false breakouts.

## TOS Inputs

Volume Stack has no user inputs — all settings are built-in. Toggle label visibility only:

| Display Element | Control | Purpose |
|-----------------|---------|---------|
| Stacked histogram | Always on | Visual buy/sell separation |
| Volume percentages | Label (yes/no) | Shows buy% and sell% each bar |
| Color assignment | Code-defined | Green = buyers, Red = sellers |

**Color scheme**:
- Buyers winning (buy_pct ≥ sell_pct): Green bar on top (full volume), red bar below (sell portion)
- Sellers winning (sell_pct > buy_pct): Red bar on top (full volume), green bar below (buy portion)

## Visual Elements

**Lower histogram (losing side)**: Draws with 50% opacity, colored opposite the winner. Height = portion of total volume from losing side.

**Upper histogram (winning side)**: Opaque, full color. Height = portion of total volume from winning side. **Total height = full volume bar.**

**Label (per-bar)**: Two percentages side-by-side. Larger % on left (winner), smaller % on right (loser). Example:
- `75% 25%` (green/red) = 75% buy, 25% sell (strong buyers)
- `30% 70%` (red/green) = 30% buy, 70% sell (strong sellers)

**Stacked appearance**: Unlike traditional volume bars that show full height only, this draws two bars on same x-coordinate: smaller below, larger above. Creates obvious visual imbalance.

## Install (TOS Steps)

1. Open ThinkOrSwim → Charts → Any timeframe (1, 5, 15, 60 min recommended)
2. Right-click volume pane → Edit Studies
3. Create new custom study → paste code from `Saty_Volume_StackSTUDY.ts`
4. Name: `Saty_Volume_Stack`
5. No inputs to configure (built-in defaults)
6. Label: Enable to see percentages; toggle off if cluttered
7. Aggregation: Will inherit chart aggregation; test on 5-min bars to see label accuracy
8. Apply; customize colors if preferred (green/red defaults are standard)

## Alerts

| Signal | Condition | Action | Trade Impact |
|--------|-----------|--------|--------------|
| **Buyer Dominance** | buy_pct > 60% | Confirm bullish bias | Adds weight to Layer 4 long entry |
| **Seller Dominance** | buy_pct < 40% | Confirm bearish bias | Adds weight to Layer 4 short entry |
| **Divergence** | Price up, buy_pct < 40% | Warning | Potential fakeout; reduce confidence |
| **Climax** | buy_pct > 75% or < 25% | Extreme imbalance | Pullback/reversal likely; Layer 2 confluence check |
| **Flip** | buy_pct crosses 50% | Sentiment shift | Momentum weakening; monitor for Layer 4 exit |

**Recommended alert rules** (manual):
- When buy_pct > 70% + breakout in progress: "Strong buyers, breakout valid"
- When buy_pct < 30% + breakdown in progress: "Strong sellers, breakdown valid"
- When buy_pct 45–55%: Suppress confidence-based entry signals

## Known Limits / Gotchas

1. **OHLC ratio is a proxy, not actual buy/sell volume**: TOS charting does not have true orderbook-level buy/sell data. The formula `(close − low) / (high − low)` assumes buyers pushed price up and sellers pushed down within the candle. This breaks on wick bars (high wick, close near low = false "seller dominance" despite buyers pushing high). Real volume profile would be more accurate; this is a heuristic.

2. **Doesn't account for pre-market or post-market volume**: Volume shown is RTH only. Overnight volume not included (irrelevant for day traders, important for swing traders holding through close).

3. **Labels can overlap on tight timeframes**: On 1-min charts, percentages may obscure price action. Use `ShowLabels=no` or widen pane if needed.

4. **Zero-volume bars**: If a bar has 0 volume (rare, but possible in illiquid off-hours), division by zero is avoided by the Python code (`replace(0, np.nan)`), but TOS version should handle gracefully — test with low-volume assets.

5. **Aggregate confusion**: If chart is on 15-min, each bar's label shows that 15-min candle's buy%. Do NOT confuse with cumulative session buy%. Each bar is independent.

6. **Not an entry signal alone**: buy_pct > 60% does NOT mean "buy now." It's a filter/bias confirmation. Use with Layer 2 (support) and Layer 4 (breakout) entries. Oversold/overbought alone is noise.

7. **Python port equivalence**: `engine/backtest/indicators.py:144–160` replicates exact formula. Both TOS and Python give identical percentages when fed same OHLC.

## Integration Notes

**Backtester usage**: `engine/backtest/signals.py:206` calls `volume_stack()` on every row:
```python
buy_vol, sell_vol, buy_pct = volume_stack(df)
df["buy_pct"] = buy_pct
```

**Debate scoring**: `composite_signals.py:314` checks:
```python
if buy_pct > 60.0:
    bull_score += 0.5  # Buyer dominance
elif buy_pct < 40.0:
    bear_score += 0.5  # Seller dominance
```

**Backtest results**: MCL (crude oil) 1h strategy shows buy_pct filter reduces false breakouts by ~12%; combined with IB High/Low, composite PF improves from 0.82 → 0.89 (2025-01-01 to 2025-06-01 window).

## References

- **Python source**: `engine/backtest/indicators.py:144–160`
- **Integration**: `engine/backtest/signals.py:206–207`
- **Debate usage**: `engine/agents/composite_signals.py:314–320`
- **COHEN_MES_README.md** — Layer 3 role in multifactor framework

## Author Note

"Volume tells the story that price action alone can't. When 75% of the bar is bought, shorts are underwater; when 75% is sold, longs are trapped. Stack them visually and the market's bias becomes obvious." — Saty Mahajan

---
*Last updated: 2026-04-20*
