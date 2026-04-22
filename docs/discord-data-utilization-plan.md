# Discord Data Utilization Plan — JARVIS Trader
## Created: 2026-04-02

---

## Overview

**281,838 Discord records** from the Corey Auction Tools server are now imported into `data/jarvis_trader.db`. This plan defines exactly how each data source gets integrated into JARVIS's trading pipeline to improve signal quality, RL performance, and trade execution.

### Data Inventory

| Table | Records | Date Range | Signal Value |
|-------|---------|------------|--------------|
| `discord_bot_signals` | 215,887 | Jul 2023 → Apr 2026 | HIGH — real production bot alerts with win/loss stats |
| `discord_ib_reports` | 940 | Jul 2023 → Apr 2026 | HIGH — IB levels for structural boundaries |
| `discord_corey_commentary` | 64,943 | Aug 2020 → Apr 2026 | MEDIUM — market regime context from expert |
| `discord_corey_alerts` | 68 | Jul 2023 → Dec 2024 | MEDIUM — Corey's hand-picked manual trades |

### Symbol Distribution (bot_signals)
- NQ: 70,083 | GC: 43,202 | ES: 33,701 | YM: 25,840 | RTY: 21,485 | 6E: 17,397 | CL: 4,132

---

## Integration 1: RL Environment Enhancement (HIGHEST PRIORITY)

**What**: Add Discord signal context to the 18-feature RL state space in `engine/strategies/rl_environment.py`.

**Why**: The bot has 2+ years of LIVE signal performance data with actual win rates, MFE/MAE stats, and gain/draw metrics. Adding this as external market "wisdom" gives the RL agent a direct line to proven edge.

### New Features to Add (5 additional)

| Feature Index | Name | Source | Range | Computation |
|--------------|------|---------|-------|-------------|
| 18 | `discord_signal_active` | `discord_bot_signals` | 0/1 | 1 if same-symbol signal within last 4 bars |
| 19 | `discord_win_rate_context` | `discord_bot_signals` | 0.0–1.0 | Rolling 30-day win rate for this symbol |
| 20 | `discord_proximity_entry` | `discord_bot_signals` | -1.0 to 1.0 | (price - entry) / ATR, clamped |
| 21 | `discord_proximity_target` | `discord_bot_signals` | 0.0–2.0 | Distance from T1 in ATR units |
| 22 | `discord_alignment` | both tables | -1/0/1 | -1=counter, 0=neutral, 1=aligned with JARVIS bias |

### Implementation Steps

1. **Create `engine/discord/signal_context.py`**
   ```python
   class DiscordSignalContext:
       """Queries discord_bot_signals for RL feature injection."""

       def get_features(self, symbol: str, timestamp: datetime, price: float, atr: float) -> dict:
           # Returns dict with 5 features above
           # Uses cached rolling stats (TTL 5 min) to avoid per-bar DB queries
   ```

2. **Modify `engine/strategies/rl_environment.py`**
   - Inject `DiscordSignalContext` at `__init__`
   - Extend `_build_state()` to call `context.get_features()` and append to state array
   - Update `observation_space` from `Box(18)` to `Box(23)`
   - Update `_build_state()` docstring with feature index map

3. **Update `engine/strategies/feature_names.py`** (if exists) to add the 5 new feature names

4. **Retrain RL agent** after integration — existing weights are invalid with new state shape

**Files to modify**: `rl_environment.py`, `engine/discord/signal_context.py` (new)

---

## Integration 2: IB Reports → Layer 2 Structure Signals (HIGH PRIORITY)

**What**: Feed `discord_ib_reports.ibu50/ibu100/ibd50/ibd100` into `engine/backtest/signals.py` Layer 2 (Structure Map).

**Why**: Layer 2 currently uses VPOC/VAH/VAL from volume profile. The IB report data provides **pre-market-calculated** auction boundary levels that the bot uses. Adding these creates a direct structural reference layer with a 940-record validated history.

### Current Layer 2 Structure

```python
# engine/backtest/signals.py — Layer 2
structure = {
    'vpoc': ...,   # current
    'vah': ...,    # current
    'val': ...,    # current
    'ib_high': ...,  # current — raw IB
    'ib_low': ...,   # current — raw IB
}
```

### Enhanced Layer 2 (after integration)

```python
structure = {
    'vpoc': ...,
    'vah': ...,
    'val': ...,
    'ib_high': ...,
    'ib_low': ...,
    # NEW from discord_ib_reports:
    'ibu50': discord_levels.ibu50,    # IB upper extension 50%
    'ibu100': discord_levels.ibu100,  # IB upper extension 100%
    'ibd50': discord_levels.ibd50,    # IB lower extension 50%
    'ibd100': discord_levels.ibd100,  # IB lower extension 100%
    'auction_context': discord_levels.auction_context,  # 'balanced'/'imbalanced'/etc.
}
```

### Implementation Steps

1. **Create `engine/discord/ib_levels.py`**
   - Class `IBLevelProvider` — queries `discord_ib_reports` by symbol + trading date
   - Returns structured dict with IBU50/100/IBD50/100 levels
   - Cache by (symbol, date) — IB levels don't change intraday

2. **Modify `engine/backtest/signals.py`**
   - Import `IBLevelProvider`
   - In `compute_signals()` or `_build_structure_map()`, call provider for current bar's date
   - Add proximity checks: `price_near_ibu50 = abs(price - ibu50) / atr < 0.5`
   - Add to Layer 2 output features

3. **Add IB level proximity to Layer 2 vote** in `_compute_bias()` if price is between IB levels (balanced market = reduce position size)

**Files to modify**: `engine/backtest/signals.py`, `engine/discord/ib_levels.py` (new)

---

## Integration 3: Commentary Sentiment → Regime Confidence Weighting (MEDIUM PRIORITY)

**What**: Parse `discord_corey_commentary` content for directional bias/caution keywords and use as a confidence multiplier on JARVIS's regime score.

**Why**: 64,943 messages from 2020–2026 from an expert trader — pre-market calls, market structure assessments, trade plans. Even crude sentiment extraction adds meaningful context about "is the market in good/bad shape for my strategy."

### Sentiment Extraction Approach

**Simple keyword scoring (start here — no LLM needed)**:

```python
BULLISH_KEYWORDS = ['long', 'buy', 'support', 'breakout', 'squeeze', 'auction higher',
                     'accepting', 'initiative buying', 'demand zone', 'above poc', 'above val']
BEARISH_KEYWORDS = ['short', 'sell', 'resistance', 'breakdown', 'distribution',
                     'auction lower', 'rejecting', 'initiative selling', 'supply zone',
                     'below poc', 'below vah']
CAUTION_KEYWORDS = ['choppy', 'balanced', 'inside', 'wait', 'no trade', 'avoid',
                     'tight', 'holiday', 'news', 'fomc', 'cpi', 'jobs']
```

**Output**: `sentiment_score` per trading day — range -1.0 to +1.0

### Integration Point

- Add `discord_daily_sentiment` table (computed, not raw): `date, symbol, sentiment_score, post_count, source`
- Run nightly ETL to compute from new commentary
- Expose via `engine/discord/sentiment_provider.py`
- In `signals.py`, multiply regime confidence by `(1.0 + 0.3 * sentiment_score)` — max ±30% adjustment

**Files**: `engine/discord/sentiment_provider.py` (new), `engine/discord/storage.py` (add table), `engine/backtest/signals.py`

---

## Integration 4: Historical Signal Correlation Study (ANALYSIS PHASE)

**What**: Backtest JARVIS's own signal engine against the 2+ years of Discord bot signals to find where they agree and disagree — and what that predicts about outcome.

**Why**: The Discord bot has real P&L history embedded in `win_rate`, `wins`, `losses`, `mfe`, `mae`. When JARVIS and Discord agree (both long/both short), does that produce higher PF? When they disagree, should JARVIS step aside?

### Analysis Pipeline

```python
# engine/analysis/discord_correlation.py

def analyze_signal_alignment(symbol: str, date_range: tuple) -> pd.DataFrame:
    """
    For each Discord signal, compute what JARVIS's 5-layer system would have output
    at the same timestamp. Categorize:
    - BOTH_LONG, BOTH_SHORT = agreement
    - JARVIS_LONG_BOT_SHORT, etc. = disagreement
    - JARVIS_NEUTRAL = JARVIS had no signal

    Compare win rates by category.
    """
```

### Expected Outputs
- Win rate by alignment category (agreement vs. disagreement)
- PF by symbol when signals align
- Optimal "wait for alignment" threshold
- Time-of-day patterns (when does Discord signal most often precede a winning JARVIS setup?)

### Implementation Steps

1. Run historical 5-layer signals against Discord signal timestamps (use existing backtest engine)
2. Join results on (symbol, timestamp ±15 min)
3. Compute statistics by alignment category
4. Output to `data/discord_correlation_study.csv` + dashboard chart

**New file**: `engine/analysis/discord_correlation.py`

---

## Integration 5: Pattern Extraction — Time/Symbol Profiling (MEDIUM PRIORITY)

**What**: Feed Discord signal timestamps into the PatternExtractor (if Phase 6 Learning System is built) or a standalone analyzer to find optimal trading windows per symbol.

**Why**: 215,887 signals over 2+ years. We can compute:
- Best hours to trade each symbol (NQ vs. GC vs. ES likely differ)
- Day-of-week performance
- Month/quarter seasonality
- Regime-conditional performance windows

### Quick Analysis (pre-Phase 6)

```python
# engine/analysis/discord_time_patterns.py

def compute_time_patterns(symbol: str) -> dict:
    """
    From discord_bot_signals:
    - Group by hour_of_day → avg win_rate, avg gain
    - Group by day_of_week → same
    - Group by month → same
    - Return optimal windows
    """
```

**Output**: `data/discord_time_patterns.json` — consumed by:
- Position size multiplier (scale up during high-probability windows)
- Filter layer (skip entries outside optimal window)

---

## Integration 6: Trade Classifier Feedback Loop (FUTURE)

**What**: When JARVIS closes a trade, query `discord_bot_signals` for same-symbol signals near the entry time. If Discord signal had high win_rate AND JARVIS trade was Grade A (via Trade Classifier), build a "Grade A + Discord alignment" category.

**Why**: Creates a compounding quality filter — not just "was this technically valid" but "did the smart money agree?"

**Dependency**: Requires Trade Classifier (Phase 6) + Discord integration being complete.

---

## Implementation Roadmap

### Phase A — Week 1 (Immediate Value)
| Task | File(s) | Impact | Effort |
|------|---------|--------|--------|
| IB Level Provider | `engine/discord/ib_levels.py` | High | 2h |
| Layer 2 IB extension levels | `engine/backtest/signals.py` | High | 3h |
| Discord Signal Context class | `engine/discord/signal_context.py` | High | 3h |
| RL state space expansion (23 features) | `rl_environment.py` | High | 4h |

### Phase B — Week 2 (Analysis)
| Task | File(s) | Impact | Effort |
|------|---------|--------|--------|
| Signal correlation study | `engine/analysis/discord_correlation.py` | High | 5h |
| Time pattern analysis | `engine/analysis/discord_time_patterns.py` | Medium | 3h |
| Dashboard correlation chart | `dashboard/components/discord/` | Medium | 3h |

### Phase C — Week 3 (Sentiment)
| Task | File(s) | Impact | Effort |
|------|---------|--------|--------|
| Sentiment ETL + table | `engine/discord/sentiment_provider.py` | Medium | 4h |
| Regime confidence weighting | `engine/backtest/signals.py` | Medium | 2h |
| Dashboard sentiment widget | `dashboard/components/discord/` | Low | 2h |

### Phase D — Phase 6+ (Learning System)
| Task | File(s) | Impact | Effort |
|------|---------|--------|--------|
| PatternExtractor Discord feed | `engine/learning/` | High | 6h |
| Trade Classifier feedback loop | `engine/analysis/` | High | 4h |
| Nightly Discord re-import cron | `engine/discord/cli.py` | Medium | 1h |

---

## API Endpoints (Already Live)

The Discord router is already registered at `engine/main.py`. These endpoints are available NOW:

```
GET /discord/signals?symbol=NQ&direction=LONG&limit=100
GET /discord/ib-reports?symbol=ES&limit=10
GET /discord/corey-alerts?symbol=NQ
GET /discord/commentary?channel=market-updates&limit=50
GET /discord/stats
```

---

## Key Data Relationships

```
discord_bot_signals.timestamp + symbol
    → JOIN backtest_results.timestamp + symbol
    → JOIN rl_environment._build_state() via signal_context.py

discord_ib_reports.date + symbol
    → ENRICH engine/backtest/signals.py Layer 2
    → Structure boundaries for entry/exit logic

discord_corey_commentary.timestamp
    → ETL → discord_daily_sentiment (computed)
    → Multiplier on regime confidence score

discord_corey_alerts (68 records)
    → Manually review — Corey's best trades
    → Seed "Grade A entry pattern" training examples
```

---

## Success Metrics

After Phase A+B implementation, measure:

| Metric | Current | Target (Discord-enhanced) |
|--------|---------|--------------------------|
| RL win rate (paper) | baseline | +5% with discord context |
| Backtest PF (ES 1h) | varies | +0.3 PF when discord aligned |
| Max drawdown | varies | -2% when using IB extensions as S/R |
| Signal agreement rate | N/A | Track agreement% (target >40%) |
| False signal reduction | N/A | -15% by filtering vs. discord bias |

---

## Notes

- **Re-import**: The Discord import is idempotent. Run `python -m engine.discord.cli` nightly to capture new signals (the bot runs 24/7).
- **Corey's ID**: `564449478174703646` — only his messages matter in #general. The current filter is correct.
- **Market-updates**: The repaired file has 2,685 tathedog messages stored in `discord_corey_commentary` with `channel = 'market-updates'`.
- **BTC/SPY**: Empty channels (stub files only) — expected, these markets weren't actively traded in the server.
