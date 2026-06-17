"""
BT-10c: Cohen Composite — Long-Only, MAX_HOLD=35, T1=1.5×ATR, stop=0.75×ATR
Key fix from BT-10b root cause: MAX_HOLD was cutting profitable runners mid-run.
All 12 MAX_HOLD exits in BT-10b were profitable (+$125 avg). Extending to 35 bars.
"""
import sys, warnings, json
sys.path.insert(0, '/home/user/workspace/jarvis-repo-fresh')
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
from pathlib import Path
from engine.strategy_c.tos_indicators import SatyATRLevels, PhaseCompression, CoreySinglefinder, apply_tos_gates

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL         = "SPY"
TIMEFRAME      = "1h"
INITIAL_CAP    = 10_000.0
RISK_PCT       = 0.02           # 2% of equity per trade
ATR_TARGET_MUL = 1.50          # T1 = 1.5×ATR  (was 1.0 in BT-10b)
ATR_STOP_MUL   = 0.75          # stop = 0.75×ATR (was 0.5 in BT-10b)
MAX_HOLD       = 35             # bars (was 21 in BT-10b)
ADX_PERIOD     = 14
ADX_THRESHOLD  = 20             # same as BT-10b
USE_TOS_GATES  = True
DIRECTION      = "LONG_ONLY"

data_dir = Path('/home/user/workspace/jarvis-repo-fresh/engine/backtest/data')
df = pd.read_parquet(data_dir / 'SPY_1h.parquet')
df.index = pd.to_datetime(df.index)
if df.index.tz is not None:
    df.index = df.index.tz_localize(None)
df = df[['Open','High','Low','Close','Volume']].dropna()

# ── Indicators ────────────────────────────────────────────────────────────────
# ATR (14-bar)
df['hl'] = df['High'] - df['Low']
df['hc'] = (df['High'] - df['Close'].shift(1)).abs()
df['lc'] = (df['Low']  - df['Close'].shift(1)).abs()
df['TR'] = df[['hl','hc','lc']].max(axis=1)
df['ATR'] = df['TR'].ewm(span=ADX_PERIOD, adjust=False).mean()

# ADX
def calc_adx(df, period=14):
    up   = df['High'].diff()
    down = -df['Low'].diff()
    pdm  = np.where((up > down) & (up > 0), up, 0.0)
    ndm  = np.where((down > up) & (down > 0), down, 0.0)
    atr  = df['ATR']
    pdi  = pd.Series(pdm, index=df.index).ewm(span=period, adjust=False).mean() / atr * 100
    ndi  = pd.Series(ndm, index=df.index).ewm(span=period, adjust=False).mean() / atr * 100
    dx   = ((pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan) * 100).fillna(0)
    adx  = dx.ewm(span=period, adjust=False).mean()
    return adx, pdi, ndi

df['ADX'], df['PDI'], df['NDI'] = calc_adx(df, ADX_PERIOD)

# Base entry signal: ADX trend direction (1=long, -1=short, 0=flat)
df['entry'] = np.where(
    (df['ADX'] > ADX_THRESHOLD) & (df['PDI'] > df['NDI']), 1,
    np.where((df['ADX'] > ADX_THRESHOLD) & (df['NDI'] > df['PDI']), -1, 0)
).astype(int)

# TOS gates — applied on top of base entry
if USE_TOS_GATES:
    df = apply_tos_gates(df, use_compression=True, use_atr_trigger=True, use_singlefinder=True)
    entry_col = 'entry_gated'
else:
    df['entry_gated'] = df['entry']
    entry_col = 'entry_gated'

# Long signal: gated entry == 1
df['long_signal'] = (df[entry_col] == 1)

# ── Backtest ──────────────────────────────────────────────────────────────────
equity       = INITIAL_CAP
trades       = []
position     = None  # {entry_price, stop, target, size, entry_idx, entry_date}
bars_held    = 0

for i in range(ADX_PERIOD + 20, len(df)):
    row = df.iloc[i]
    price = row['Close']
    atr   = row['ATR']

    if position is not None:
        bars_held += 1
        # Check stop
        if price <= position['stop']:
            pnl = (price - position['entry_price']) * position['size']
            equity += pnl
            trades.append({
                'exit_type': 'STOP',
                'entry_date': position['entry_date'],
                'exit_date':  df.index[i],
                'entry_price': position['entry_price'],
                'exit_price': price,
                'pnl': pnl,
                'bars_held': bars_held,
            })
            position = None
            bars_held = 0
            continue

        # Check target
        if price >= position['target']:
            pnl = (price - position['entry_price']) * position['size']
            equity += pnl
            trades.append({
                'exit_type': 'TARGET',
                'entry_date': position['entry_date'],
                'exit_date':  df.index[i],
                'entry_price': position['entry_price'],
                'exit_price': price,
                'pnl': pnl,
                'bars_held': bars_held,
            })
            position = None
            bars_held = 0
            continue

        # MAX_HOLD
        if bars_held >= MAX_HOLD:
            pnl = (price - position['entry_price']) * position['size']
            equity += pnl
            trades.append({
                'exit_type': 'MAX_HOLD',
                'entry_date': position['entry_date'],
                'exit_date':  df.index[i],
                'entry_price': position['entry_price'],
                'exit_price': price,
                'pnl': pnl,
                'bars_held': bars_held,
            })
            position = None
            bars_held = 0
            continue

    else:
        # Entry
        if row['long_signal'] and atr > 0:
            stop   = price - ATR_STOP_MUL * atr
            target = price + ATR_TARGET_MUL * atr
            risk_per_share = price - stop
            if risk_per_share > 0:
                size = max(1, int((equity * RISK_PCT) / risk_per_share))
                position = {
                    'entry_price': price,
                    'stop': stop,
                    'target': target,
                    'size': size,
                    'entry_date': df.index[i],
                }
                bars_held = 0

# ── Stats ─────────────────────────────────────────────────────────────────────
df_trades = pd.DataFrame(trades)
if df_trades.empty:
    print("No trades generated.")
    sys.exit(1)

n_trades   = len(df_trades)
wins       = df_trades[df_trades['pnl'] > 0]
losses     = df_trades[df_trades['pnl'] <= 0]
win_rate   = len(wins) / n_trades * 100
avg_win    = wins['pnl'].mean() if len(wins) else 0
avg_loss   = losses['pnl'].mean() if len(losses) else 0
gross_win  = wins['pnl'].sum()
gross_loss = losses['pnl'].sum()
profit_factor = gross_win / abs(gross_loss) if gross_loss != 0 else float('inf')

total_return = (equity - INITIAL_CAP) / INITIAL_CAP * 100
n_years = (df.index[-1] - df.index[ADX_PERIOD + 20]).days / 365.25
cagr = ((equity / INITIAL_CAP) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0

# Equity curve (approximate)
eq_series = [INITIAL_CAP]
running = INITIAL_CAP
for _, t in df_trades.iterrows():
    running += t['pnl']
    eq_series.append(running)
eq_arr = np.array(eq_series)
roll_max = np.maximum.accumulate(eq_arr)
dd = (eq_arr - roll_max) / roll_max
max_dd = dd.min() * 100

# Sharpe (weekly returns approx)
weekly_pnl = df_trades.set_index('exit_date')['pnl'].resample('W').sum()
weekly_ret = weekly_pnl / INITIAL_CAP
sharpe = (weekly_ret.mean() / weekly_ret.std() * np.sqrt(52)) if weekly_ret.std() > 0 else 0

# Exit type breakdown
exit_counts = df_trades['exit_type'].value_counts()

print('='*65)
print('  BT-10c: Cohen Composite Long-Only (MAX_HOLD=35, T1=1.5×ATR)')
print('='*65)
print(f'  Trades:          {n_trades}')
print(f'  Win Rate:        {win_rate:.1f}%')
print(f'  Profit Factor:   {profit_factor:.3f}')
print(f'  Sharpe:          {sharpe:.3f}')
print(f'  CAGR:            {cagr:.2f}%')
print(f'  Max DD:          {max_dd:.2f}%')
print(f'  Avg Win:         ${avg_win:.2f}')
print(f'  Avg Loss:        ${avg_loss:.2f}')
print(f'  R:R (avg):       {abs(avg_win/avg_loss):.3f}x' if avg_loss != 0 else '  R:R:            N/A')
print(f'  Final Equity:    ${equity:,.2f}')
print(f'  Total Return:    {total_return:.1f}%')
print(f'  CAGR:            {cagr:.2f}%')
print()
print('  Exit Breakdown:')
for et, cnt in exit_counts.items():
    et_trades = df_trades[df_trades['exit_type'] == et]
    et_wr = len(et_trades[et_trades['pnl'] > 0]) / len(et_trades) * 100
    et_avg = et_trades['pnl'].mean()
    et_bars = et_trades['bars_held'].mean()
    print(f'    {et:<12} {cnt:>4} trades  WR:{et_wr:.0f}%  avg PnL:${et_avg:>7.2f}  avg bars:{et_bars:.1f}')

print()
print('  10-Gate Assessment:')
gates_v = {
    'Sharpe ≥ 1.50':      (sharpe,      sharpe >= 1.50),
    'Win Rate ≥ 55%':     (win_rate,    win_rate >= 55.0),
    'Profit Factor ≥ 1.275': (profit_factor, profit_factor >= 1.275),
    'CAGR ≥ 8%':          (cagr,        cagr >= 8.0),
    'Max DD ≤ 15%':       (max_dd,      max_dd >= -15.0),  # max_dd is negative
}
for label, (val, ok) in gates_v.items():
    print(f'    {"✅" if ok else "❌"}  {label:<35} {val:.3f}')

# Save results
out_dir = Path('/home/user/workspace/jarvis-repo-fresh/engine/validation_reports')
out_dir.mkdir(exist_ok=True)
df_trades.to_csv(out_dir / 'BT10c_LongOnly_trades.csv', index=False)

summary = {
    'bt': 'BT-10c',
    'config': {'max_hold': MAX_HOLD, 'atr_target_mul': ATR_TARGET_MUL, 'atr_stop_mul': ATR_STOP_MUL},
    'n_trades': n_trades,
    'win_rate': round(win_rate, 2),
    'profit_factor': round(profit_factor, 3),
    'sharpe': round(sharpe, 3),
    'cagr': round(cagr, 2),
    'max_dd': round(max_dd, 2),
    'avg_win': round(avg_win, 2),
    'avg_loss': round(avg_loss, 2),
    'rr_ratio': round(abs(avg_win / avg_loss), 3) if avg_loss != 0 else None,
    'final_equity': round(equity, 2),
    'exit_breakdown': exit_counts.to_dict(),
}
with open(out_dir / 'BT10c_LongOnly_validation.json', 'w') as f:
    json.dump(summary, f, indent=2)
print(f'\n  Results saved → engine/validation_reports/BT10c_LongOnly_*')
