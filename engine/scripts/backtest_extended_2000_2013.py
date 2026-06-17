"""
T2-9: Extended backtest 2000–2013 — dot-com, 9/11, 2008, recovery
Uses weekly ETF data via yfinance. Simplified v2 engine logic (no COT, no Kalman
due to data constraints) — tests core momentum + vol targeting framework.

Key challenge: MTUM didn't exist; GLD launched 2004; IEF/SHY launched 2002.
Universe adapts by period:
  2000–2002: XLK, QQQ, SPY, XLV, XLE (SHY proxy = T-bill 0.08% weekly)
  2002–2004: + IEF, SHY
  2004–2013: + GLD
"""
import sys, warnings, json
sys.path.insert(0, '/home/user/workspace/jarvis-repo-fresh')
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
from pathlib import Path

data_dir = Path('/home/user/workspace/jarvis-repo-fresh/engine/backtest/data/extended')

# ── Load all data ──────────────────────────────────────────────────────────────
def load_weekly(sym):
    p = data_dir / f'{sym}_1w_2000_2013.parquet'
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    df.index = pd.to_datetime(df.index)
    return df['Close'].rename(sym)

assets = {}
for sym in ['XLK','QQQ','SPY','XLV','XLE','IEF','SHY','GLD']:
    s = load_weekly(sym)
    if s is not None:
        assets[sym] = s

# VIX
vix_p = data_dir / 'VIX_1w_2000_2013.parquet'
vix_weekly = pd.read_parquet(vix_p)['Close'].rename('VIX') if vix_p.exists() else None

# Build price matrix — align on common index
prices = pd.DataFrame(assets).sort_index()

# Use SHY as cash proxy; if not available, use synthetic 0.08%/wk
if 'SHY' not in prices.columns:
    prices['SHY'] = np.nan  # will be filled with 1.0 returns

# ── Configs ────────────────────────────────────────────────────────────────────
VOL_TARGET      = 7.0   # %
LOOKBACK_WEEKS  = 52    # annual momentum
TOP_N           = 2
VOL_LOOKBACK    = 10    # days (use weeks here as proxy)
BLEND_FAST_W    = 0.40
VOL_LONG_LBK    = 21
WIN_SIGMA       = 3.0
INITIAL_CAP     = 100_000.0

# ── Per-period risk-on universe ─────────────────────────────────────────────
def get_risk_on(date):
    """Return available risk-on ETFs for the date."""
    avail = []
    for sym in ['XLK','QQQ','XLV','XLE','GLD']:
        if sym in prices.columns and not pd.isna(prices.loc[prices.index >= date, sym].iloc[0] if len(prices.loc[prices.index >= date]) > 0 else np.nan):
            avail.append(sym)
    return avail[:4]  # cap at 4 options

def get_risk_off(date):
    """Return available risk-off ETFs for the date."""
    for sym in ['IEF','SHY']:
        col = prices.loc[prices.index >= date, sym] if sym in prices.columns else pd.Series()
        if not col.empty and not pd.isna(col.iloc[0]):
            return sym
    return None  # cash

# ── Compute returns ────────────────────────────────────────────────────────────
returns = prices.pct_change().dropna(how='all')

# ── Blended vol estimator ──────────────────────────────────────────────────────
def blended_vol(ret_series, date, lookback_fast=10, lookback_long=21, fast_w=0.40, win_sigma=3.0):
    """Compute blended realized vol at a date."""
    hist = ret_series.loc[:date].dropna()
    if len(hist) < lookback_long:
        return 15.0  # default
    
    # Winsorize
    r = hist.iloc[-lookback_long:].copy()
    m, s = r.mean(), r.std()
    if s > 0:
        r = r.clip(m - win_sigma*s, m + win_sigma*s)
    
    fast_vol = r.iloc[-lookback_fast:].std() * np.sqrt(52) * 100
    long_vol = r.std() * np.sqrt(52) * 100
    return fast_w * fast_vol + (1 - fast_w) * long_vol

# ── Momentum score ─────────────────────────────────────────────────────────────
def momentum_score(sym, date, lookback=52):
    try:
        hist = prices.loc[:date, sym].dropna()
        if len(hist) < lookback:
            return None
        return (hist.iloc[-1] / hist.iloc[-lookback] - 1)
    except:
        return None

# ── VIX multiplier ─────────────────────────────────────────────────────────────
def vix_mult(date):
    if vix_weekly is None:
        return 1.0
    try:
        vix_hist = vix_weekly.loc[:date].dropna()
        if vix_hist.empty:
            return 1.0
        vix_val = vix_hist.iloc[-1]
        if vix_val > 40:  return 0.25
        if vix_val > 30:  return 0.50
        if vix_val > 25:  return 0.75
        return 1.0
    except:
        return 1.0

# ── Main backtest loop ─────────────────────────────────────────────────────────
equity      = INITIAL_CAP
equity_log  = []
alloc_log   = []
holding     = {}  # {symbol: weight}

dates = prices.index[LOOKBACK_WEEKS:]

for date in dates:
    # 1. Get risk-on candidates
    risk_on = [s for s in ['XLK','QQQ','XLV','XLE','GLD'] 
               if s in prices.columns and not pd.isna(prices.loc[date, s]) 
               and momentum_score(s, date) is not None]
    
    # 2. Score momentum
    scores = {s: momentum_score(s, date) for s in risk_on}
    scores = {s: v for s, v in scores.items() if v is not None}
    
    # 3. Top N by momentum
    top = sorted(scores, key=lambda s: scores[s], reverse=True)[:TOP_N]
    
    # 4. Absolute momentum filter: if SPY below -2% over 3 weeks → risk off
    spy_3wk = None
    try:
        spy_hist = prices.loc[:date, 'SPY'].dropna()
        if len(spy_hist) >= 3:
            spy_3wk = (spy_hist.iloc[-1] / spy_hist.iloc[-3] - 1)
    except: pass
    
    if spy_3wk is not None and spy_3wk < -0.02:
        # Absolute mom breach — go risk off
        risk_off_sym = get_risk_off(date)
        if risk_off_sym:
            new_holding = {risk_off_sym: 1.0}
        else:
            new_holding = {}
    elif not top:
        risk_off_sym = get_risk_off(date)
        new_holding = {risk_off_sym: 1.0} if risk_off_sym else {}
    else:
        # All assets positive momentum?
        if all(scores[s] > 0 for s in top):
            # Equal weight among top
            w = 1.0 / len(top)
            new_holding = {s: w for s in top}
        else:
            # Mixed: move partial to risk off
            good = [s for s in top if scores[s] > 0]
            if good:
                w = 1.0 / len(top)
                new_holding = {s: w for s in good}
                remaining = 1.0 - sum(new_holding.values())
                ro = get_risk_off(date)
                if ro and remaining > 0.01:
                    new_holding[ro] = remaining
            else:
                ro = get_risk_off(date)
                new_holding = {ro: 1.0} if ro else {}
    
    # 5. Vol targeting scale
    spy_ret = returns.loc[:date, 'SPY'].dropna() if 'SPY' in returns.columns else pd.Series()
    rv = blended_vol(spy_ret, date, VOL_LOOKBACK, VOL_LONG_LBK, BLEND_FAST_W, WIN_SIGMA)
    scale = min(1.0, VOL_TARGET / rv) if rv > 0 else 1.0
    
    # 6. VIX scale
    vm = vix_mult(date)
    final_scale = scale * vm
    
    # Apply scale: risk-off assets get full weight, risk-on assets scaled
    ro_syms = ['IEF','SHY']
    scaled_holding = {}
    for s, w in new_holding.items():
        if s in ro_syms:
            scaled_holding[s] = w
        else:
            scaled_holding[s] = w * final_scale
    
    # Cash residual earns 0
    total_w = sum(scaled_holding.values())
    
    # 7. Compute portfolio return this week
    try:
        next_idx = prices.index.get_loc(date) + 1
        if next_idx >= len(prices.index):
            portfolio_ret = 0.0
        else:
            next_date = prices.index[next_idx]
            port_ret = 0.0
            for s, w in scaled_holding.items():
                if s in returns.columns and not pd.isna(returns.loc[next_date, s]):
                    port_ret += w * returns.loc[next_date, s]
            portfolio_ret = port_ret
    except:
        portfolio_ret = 0.0
    
    equity *= (1 + portfolio_ret)
    equity_log.append({'date': date, 'equity': equity, 'scale': final_scale,
                       'vol_pct': rv, 'holdings': str(scaled_holding)})
    alloc_log.append({'date': date, 'holdings': scaled_holding, 'return': portfolio_ret})

# ── Performance metrics ────────────────────────────────────────────────────────
eq_df = pd.DataFrame(equity_log).set_index('date')
eq_arr = eq_df['equity'].values
rets = pd.Series([a['return'] for a in alloc_log])

n_years = (dates[-1] - dates[0]).days / 365.25
cagr = ((equity / INITIAL_CAP) ** (1/n_years) - 1) * 100 if n_years > 0 else 0
ann_vol = rets.std() * np.sqrt(52) * 100
sharpe = (rets.mean() / rets.std() * np.sqrt(52)) if rets.std() > 0 else 0
sortino_neg = rets[rets < 0].std()
sortino = (rets.mean() / sortino_neg * np.sqrt(52)) if sortino_neg > 0 else 0
win_rate = (rets > 0).mean() * 100

# Max drawdown
roll_max = np.maximum.accumulate(eq_arr)
dd = (eq_arr - roll_max) / roll_max
max_dd = dd.min() * 100
calmar = cagr / abs(max_dd) if max_dd != 0 else 0

# SPY benchmark
spy_start = prices.loc[dates[0], 'SPY'] if 'SPY' in prices.columns else None
spy_end   = prices.loc[dates[-1], 'SPY'] if 'SPY' in prices.columns else None
spy_cagr  = ((spy_end / spy_start) ** (1/n_years) - 1) * 100 if spy_start and spy_end else None

# Period sub-splits
def period_metrics(start, end, label):
    mask = (dates >= start) & (dates <= end)
    if mask.sum() < 4:
        return None
    sub_rets = pd.Series([alloc_log[i]['return'] for i in range(len(dates)) if mask[i]])
    sub_eq = eq_df.loc[start:end, 'equity']
    if sub_eq.empty:
        return None
    sub_eq_arr = sub_eq.values
    sub_n = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    sub_cagr = ((sub_eq_arr[-1]/sub_eq_arr[0]) ** (1/sub_n) - 1) * 100 if sub_n > 0 else 0
    roll = np.maximum.accumulate(sub_eq_arr)
    sub_dd = ((sub_eq_arr - roll) / roll).min() * 100
    sub_sh = (sub_rets.mean() / sub_rets.std() * np.sqrt(52)) if sub_rets.std() > 0 else 0
    return {'label': label, 'cagr': round(sub_cagr,2), 'sharpe': round(sub_sh,3),
            'max_dd': round(sub_dd,2), 'n_weeks': int(mask.sum())}

periods = [
    period_metrics('2000-01-01','2002-12-31','Dot-com bust (2000–2002)'),
    period_metrics('2003-01-01','2007-12-31','Recovery bull (2003–2007)'),
    period_metrics('2008-01-01','2009-03-31','GFC bear (2008–Q1\'09)'),
    period_metrics('2009-04-01','2013-12-31','Recovery bull (2009–2013)'),
]

print('='*70)
print('  T2-9: EXTENDED BACKTEST — 2000 to 2013')
print('  (Dot-com, 9/11, GFC, Recovery)')
print('='*70)
print(f'  Period: {dates[0].date()} → {dates[-1].date()}  ({n_years:.1f} years)')
print(f'  CAGR:        {cagr:.2f}%  (SPY: {spy_cagr:.2f}%)')
print(f'  Sharpe:      {sharpe:.3f}')
print(f'  Sortino:     {sortino:.3f}')
print(f'  Ann Vol:     {ann_vol:.2f}%')
print(f'  Max DD:      {max_dd:.2f}%')
print(f'  Calmar:      {calmar:.3f}')
print(f'  Win Rate:    {win_rate:.1f}%')
print(f'  Final EQ:    ${equity:,.0f}  ({equity/INITIAL_CAP:.2f}x)')
print()
print('  Sub-Period Breakdown:')
for p in periods:
    if p:
        print(f'    {p["label"]:<35}  CAGR:{p["cagr"]:>7.2f}%  Sharpe:{p["sharpe"]:>6.3f}  MDD:{p["max_dd"]:>7.2f}%')

print()
print('  Gate Assessment vs 10-Gate thresholds:')
gate_map = [
    ('Sharpe ≥ 1.50', sharpe, sharpe >= 1.50),
    ('Sortino ≥ 1.00', sortino, sortino >= 1.00),
    ('Calmar ≥ 0.50', calmar, calmar >= 0.50),
    ('Win Rate ≥ 55%', win_rate, win_rate >= 55.0),
    ('Max DD ≤ 15%', max_dd, max_dd >= -15.0),
]
for label, val, ok in gate_map:
    print(f'    {"✅" if ok else "❌"}  {label:<35}  {val:.3f}')

# Save
out_dir = Path('/home/user/workspace/jarvis-repo-fresh/engine/validation_reports')
result = {
    'bt': 'T2-9-Extended-2000-2013',
    'period': f'{dates[0].date()} → {dates[-1].date()}',
    'cagr': round(cagr,2),
    'sharpe': round(sharpe,3),
    'sortino': round(sortino,3),
    'calmar': round(calmar,3),
    'max_dd': round(max_dd,2),
    'win_rate': round(win_rate,1),
    'ann_vol': round(ann_vol,2),
    'final_equity': round(equity,2),
    'spy_cagr': round(spy_cagr,2) if spy_cagr else None,
    'sub_periods': [p for p in periods if p],
}
with open(out_dir / 'T2_9_extended_2000_2013.json', 'w') as f:
    json.dump(result, f, indent=2)
print(f'\n  Saved → engine/validation_reports/T2_9_extended_2000_2013.json')
