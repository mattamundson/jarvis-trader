# JARVIS TRADER — Strategy mathematics (equation reference)

**Companion:** [TRADING_RULES.md](./TRADING_RULES.md) (operational rules).  
**Source of truth:** Python implementations in [`engine/backtest/indicators.py`](../../engine/backtest/indicators.py) and [`engine/backtest/signals.py`](../../engine/backtest/signals.py); composite in [`engine/backtest/composite_signals.py`](../../engine/backtest/composite_signals.py).

Notation: bar \(t\) uses OHLCV \((O_t,H_t,L_t,C_t,V_t)\). Series use pandas conventions; EWM uses `adjust=False` (standard α = 2/(span+1) recurrence).

---

## 1. True Range and ATR variants

### 1.1 True Range (per bar)

\[
\mathrm{TR}_t = \max\bigl(H_t - L_t,\ |H_t - C_{t-1}|,\ |L_t - C_{t-1}|\bigr)
\]

### 1.2 Wilder ATR (period \(n\), default \(n=14\))

Used in phase oscillator and (via different smoothing) contrasted with SMA ATR below.

- Initialize at index \(n-1\): \(\mathrm{ATR}_{n-1} = \frac{1}{n}\sum_{i=0}^{n-1} \mathrm{TR}_i\).
- For \(t \ge n\):

\[
\mathrm{ATR}^{\mathrm{W}}_t = \frac{(n-1)\,\mathrm{ATR}^{\mathrm{W}}_{t-1} + \mathrm{TR}_t}{n}
\]

**Code:** `wilder_atr(..., period=14)`.

### 1.3 SMA ATR (period \(n\), default \(n=20\) in Keltner)

\[
\mathrm{ATR}^{\mathrm{SMA}}_t = \frac{1}{n}\sum_{i=t-n+1}^{t} \mathrm{TR}_i
\]

**Code:** `sma_atr` (rolling mean of TR).

---

## 2. Kaufman Adaptive Moving Average (KAMA)

Period \(n=10\), fast span 2, slow span 30 (defaults).

- **Direction change over \(n\) bars:** \(\Delta_t = |C_t - C_{t-n}|\).
- **Volatility:** \(V_t = \sum_{i=t-n+1}^{t} |C_i - C_{i-1}|\).
- **Efficiency ratio:** \(\mathrm{ER}_t = \Delta_t / V_t\) if \(V_t>0\), else \(0\).
- **Smoothing constant:** \(sc_t = \bigl(\mathrm{ER}_t(\alpha_f - \alpha_s) + \alpha_s\bigr)^2\) with \(\alpha_f = 2/(2+1)\), \(\alpha_s = 2/(30+1)\) from fast/slow periods.

Recurrence for \(t \ge n\):

\[
\mathrm{KAMA}_t = \mathrm{KAMA}_{t-1} + sc_t\,(C_t - \mathrm{KAMA}_{t-1})
\]

**Signal:** long if \(C_t > \mathrm{KAMA}_t\), short if \(C_t < \mathrm{KAMA}_t\), else neutral.

**Code:** `kama`.

---

## 3. Schaff Trend Cycle (STC)

Parameters: fast \(=23\), slow \(=50\), \(K=10\), \(D=3\).

1. **MACD line:** \(\mathrm{MACD}_t = \mathrm{EMA}_{23}(C)_t - \mathrm{EMA}_{50}(C)_t\) (pandas `ewm(span=..., adjust=False)`).

2. **Stochastic of a series \(X\) over \(K\) bars:**

\[
\mathrm{Stoch}_K(X)_t = \begin{cases}
100 \cdot \dfrac{X_t - \min_{[t-K+1,t]} X}{\max_{[t-K+1,t]} X - \min_{[t-K+1,t]} X} & \text{if denom} \neq 0 \\
50 & \text{otherwise}
\end{cases}
\]

3. **First smooth:** \(D^{(1)}_t = \mathrm{EMA}_{D}(\mathrm{Stoch}_K(\mathrm{MACD}))_t\) with \(D=3\).

4. **Second stochastic:** \(K^{(2)}_t = \mathrm{Stoch}_K(D^{(1)})_t\).

5. **STC output:** \(\mathrm{STC}_t = \mathrm{EMA}_{D}(K^{(2)})_t\), clipped to \([0,100]\).

**Cross definitions** (after optional per-symbol oversold \(S_{\mathrm{OS}}\) / overbought \(S_{\mathrm{OB}}\) from `INSTRUMENT_PARAMS`):

- **Cross up:** \(\mathrm{STC}_t > S_{\mathrm{OS}}\) and \(\mathrm{STC}_{t-1} \le S_{\mathrm{OS}}\).
- **Cross down:** \(\mathrm{STC}_t < S_{\mathrm{OB}}\) and \(\mathrm{STC}_{t-1} \ge S_{\mathrm{OB}}\).

**Code:** `stc`, `generate_signals` (threshold overrides).

---

## 4. Phase oscillator and compression

EMA length 21, Wilder ATR 14, Bollinger length 21, std multiplier 2.

\[
\mathrm{EMA}^{(21)}_t = \mathrm{EMA}_{21}(C)_t,\quad \mathrm{ATR}_t = \mathrm{ATR}^{\mathrm{W}}_{14,t}
\]

\[
\mathrm{Phase}_t = \mathrm{clip}_{[-100,100]}\left( \frac{C_t - \mathrm{EMA}^{(21)}_t}{3\,\mathrm{ATR}_t + \varepsilon} \cdot 100 \right)
\]

Bollinger on close: mid \(M_t = \mathrm{SMA}_{21}(C)_t\), \(\sigma_t = \mathrm{std}_{21}(C)_t\), band width \(W^{\mathrm{BB}}_t = (M_t + 2\sigma_t) - (M_t - 2\sigma_t)\). ATR band width \(W^{\mathrm{ATR}}_t = 2\,\mathrm{ATR}_t\).

**Compression:** \(\mathrm{Compression}_t = \mathbb{1}[W^{\mathrm{BB}}_t < W^{\mathrm{ATR}}_t]\).

**Code:** `phase_oscillator`.

---

## 5. Volume stack (buy/sell split)

Let \(\mathrm{rng}_t = H_t - L_t\) (if 0, code uses 50/50 split).

\[
\mathrm{BuyVol}_t = V_t \cdot \frac{C_t - L_t}{\mathrm{rng}_t},\quad
\mathrm{SellVol}_t = V_t \cdot \frac{H_t - C_t}{\mathrm{rng}_t}
\]

\[
\mathrm{BuyPct}_t = 100 \cdot \frac{\mathrm{BuyVol}_t}{\mathrm{BuyVol}_t + \mathrm{SellVol}_t}
\]

**Signals:** buyer_dominant if \(\mathrm{BuyPct}>60\), seller_dominant if \(<40\), else balanced.

**Code:** `volume_stack`.

---

## 6. Keltner channels

Basis (default SMA 20 on close), ATR = SMA of TR over 20, factor \(f \in \{1.5, 2.0, 3.0\}\) for inner/outer/extreme:

\[
\mathrm{Basis}_t = \mathrm{SMA}_{20}(C)_t,\quad
\mathrm{Upper}_t = \mathrm{Basis}_t + f \cdot \mathrm{ATR}^{\mathrm{SMA}}_{20,t},\quad
\mathrm{Lower}_t = \mathrm{Basis}_t - f \cdot \mathrm{ATR}^{\mathrm{SMA}}_{20,t}
\]

**Code:** `keltner_channels`.

---

## 7. CCI (period 50)

Typical price \(T_t = (H_t + L_t + C_t)/3\), \(\mu_t = \mathrm{SMA}_{50}(T)_t\), mean deviation \(\mathrm{MD}_t = \frac{1}{50}\sum_{i=t-49}^{t} |T_i - \bar T_{t,50}|\) (implementation uses rolling apply).

\[
\mathrm{CCI}_t = \frac{T_t - \mu_t}{0.015 \cdot \mathrm{MD}_t}
\]

**Code:** `cci`.

---

## 8. ATR range consumed (%)

Used in Layer 1 regime.

\[
\mathrm{Consumed}_t = \min\left(200,\ \frac{|C_t - C_{t-1}|}{\mathrm{ATR}_t} \cdot 100\right)
\]

(0 if \(\mathrm{ATR}_t \le 0\).)

**Code:** `range_consumed_pct` in `indicators.py`; column `atr_consumed_pct` in `compute_all_indicators`.

---

## 9. EMA ribbon (8 / 21 / 34)

\[
E^{(s)}_t = \mathrm{EMA}_s(C)_t,\quad s \in \{8,21,34\}
\]

**Trend:** bullish if \(E^{(8)} > E^{(21)} > E^{(34)}\), bearish if all reversed, else neutral.

**Code:** `ema_ribbon`.

---

## 10. Structure proxies (Layer 2 inputs)

Rolling window \(W=20\) (from `signals.compute_all_indicators`):

- **VPOC proxy (VWAP of window):** \(\mathrm{VPOC}_t = \sum_{i=t-19}^{t} C_i V_i \big/ \sum_{i=t-19}^{t} V_i\).
- **VAH / VAL proxies:** 85th percentile of recent highs, 15th percentile of recent lows over \(W\).
- **IB high/low proxy (per bar):** \(\mathrm{IBHigh}_t = H_{t-1}\), \(\mathrm{IBLow}_t = L_{t-1}\).

Boolean structure flags: above_vah, below_val, above_ib_high, below_ib_low from close vs those levels.

**Code:** `signals.py` inside `compute_all_indicators`.

---

## 11. Layer 1 regime (piecewise)

Let \(c=\mathrm{Consumed}_t\), phase \(=\mathrm{Phase}_t\), compression flag, `ema_trend` \(\in\) {bullish, bearish, neutral}.

1. If \(c > 90\) → **EXHAUSTED**
2. Else if compression and \(c < 50\) → **COMPRESSION**
3. Else if `ema_trend` bullish and \(c < 70\) and phase \(> 0\) → **TRENDING_BULL**
4. Else if `ema_trend` bearish and \(c < 70\) and phase \(< 0\) → **TRENDING_BEAR**
5. Else → **RANGE_BOUND**

If `regime_filter` is False in `generate_signals`, **EXHAUSTED** and **COMPRESSION** are relabeled **RANGE_BOUND** before Layer 4.

**Code:** `layer1_regime`.

---

## 12. Layer 3 bias (scoring)

Integer votes from four components (KAMA, STC signal category, volume_signal, ema_trend). Count bull vs bear; thresholds:

- \(\mathrm{bull} \ge 4\) → STRONG_BULL; \(\mathrm{bull} \ge 3\) or \((\mathrm{bull}=2\) and ema bullish) → LEAN_BULL
- Symmetric for bear
- Else NEUTRAL

**Code:** `layer3_bias`.

---

## 13. Stop and target levels (standard `generate_signals`)

Let \(\mathrm{ATR}_t\) be Wilder ATR(14), \(s_s,t_s,t_1,t_2,t_3\) from `INSTRUMENT_PARAMS[symbol]` (stop and target ATR multipliers). Define long side from **bias** (not entry direction): `is_long` = bias in {STRONG_BULL, LEAN_BULL}.

**Long:**

\[
\mathrm{Stop}_t = C_t - s_s \cdot \mathrm{ATR}_t,\quad
T^{(k)}_t = C_t + t_k \cdot \mathrm{ATR}_t,\ k \in \{1,2,3\}
\]

**Short** (LEAN/STRONG bear):

\[
\mathrm{Stop}_t = C_t + s_s \cdot \mathrm{ATR}_t,\quad
T^{(k)}_t = C_t - t_k \cdot \mathrm{ATR}_t
\]

**Code:** `generate_signals` after layer loop.

---

## 14. Optional volume gate

\(\overline{V}_t = \frac{1}{N}\sum_{i=t-N+1}^{t} V_i\) (default \(N=20\)). Entry allowed only if \(V_t > \overline{V}_t\) when `volume_filter=True`.

**Code:** `generate_signals`.

---

## 15. Layer 5 — risk scaling

Inputs: `bias`, `regime` (trending bull/bear vs other), `structure_position`, `base_risk_pct`.

Let \(m \in \{1.0,\ 0.8,\ 0.5,\ 0.25\}\) per the branching in `compute_position_size` (strong+ trending + directional structure → 1.0; strong + trending → 0.8; lean or not trending → 0.5; else 0.25).

\[
\mathrm{risk\_pct}_t = \mathrm{round}(m \cdot \mathrm{base\_risk\_pct}, 6)
\]

**Code:** `compute_position_size`, constants `SIZING_*`.

---

## 16. Composite signals (`composite_signals.py`)

### 16.1 Regime weights

For each bar, \(r \in\) {TRENDING, RANGING, VOLATILE} with weights \((w_{\mathrm{stc}}, w_{\mathrm{orb}}, w_{\mathrm{vwap}})\):

- TRENDING: \((0.60, 0.30, 0.10)\)
- RANGING: \((0.50, 0.20, 0.30)\)
- VOLATILE: \((0,0,0)\)

### 16.2 Encoded legs (0/1)

\(L_{\mathrm{stc}}, S_{\mathrm{stc}}\) from STC cross up/down; ORB LONG/SHORT; VWAP LONG/SHORT as booleans.

### 16.3 Scores

\[
\mathrm{LongScore}_t = w_{\mathrm{stc}} L_{\mathrm{stc}} + w_{\mathrm{orb}} L_{\mathrm{orb}} + w_{\mathrm{vwap}} L_{\mathrm{vwap}}
\]
\[
\mathrm{ShortScore}_t = w_{\mathrm{stc}} S_{\mathrm{stc}} + w_{\mathrm{orb}} S_{\mathrm{orb}} + w_{\mathrm{vwap}} S_{\mathrm{vwap}}
\]

**Entry (long)** if \(\mathrm{LongScore}_t \ge \theta\) (default \(\theta=0.35\)), **STC long fires**, and regime ≠ VOLATILE; symmetric for short; tie-break if both.

### 16.4 Composite stop / targets (fixed ATR multiples on composite branch)

Constants `COMP_STOP_ATR = 1.0`, `COMP_T1_ATR = 2.5`, `COMP_T2_ATR = 4.0`.

Long: \(\mathrm{Stop} = C_t - 1.0 \cdot \mathrm{ATR}_t\), \(T_1 = C_t + 2.5 \cdot \mathrm{ATR}_t\), \(T_2 = C_t + 4.0 \cdot \mathrm{ATR}_t\); short mirrored.

### 16.5 Composite reward-to-risk at T1

Long: \(\mathrm{RR} = \dfrac{T_1 - C_t}{C_t - \mathrm{Stop}}\) (if risk \(>0\)). Entries with \(\mathrm{RR} < \mathrm{MIN\_RR}\) (code: **1.2**) are removed.

**Code:** `generate_composite_signals`.

---

## 17. Symbol parameters (ATR multipliers and STC thresholds)

Per-symbol tuple \((S_{\mathrm{OS}}, S_{\mathrm{OB}}, s_s, t_1, t_2, t_3, \mathrm{regime\_filter})\) in `INSTRUMENT_PARAMS` — see [TRADING_RULES.md §4](./TRADING_RULES.md) for MCL/MNQ numeric values.

---

*Document generated to mirror `indicators.py` / `signals.py` / `composite_signals.py` as of repo state; if code changes, update this file in the same PR.*
