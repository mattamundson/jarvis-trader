"""
T3-13: Commodity Universe Stress Test 2000–2010
Replace XLK → XLE + GLD in risk-on universe. Tests whether the strategy's 
momentum framework generalizes beyond tech-growth into commodities.
Also runs 2004–2013 since GLD launched 2004.
"""
import sys, warnings, json
sys.path.insert(0, '/home/user/workspace/jarvis-repo-fresh')
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
from pathlib import Path

data_dir = Path('/home/user/workspace/jarvis-repo-fresh/engine/backtest/data/extended')

def load_weekly(sym):
    p = data_dir / f'{sym}_1w_2000_2013.parquet'
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    df.index = pd.to_datetime(df.index)
    return df['Close'].rename(sym)

# Universe: no XLK — replaced with XLE + GLD
assets_commodity = {}
for sym in ['QQQ','SPY','XLV','XLE','GLD','IEF','SHY']:
    s = load_weekly(sym)
    if s is not None:
        assets_commodity[sym] = s

vix_p = data_dir / 'VIX_1w_2000_2013.parquet'
vix_weekly = pd.read_parquet(vix_p)['Close'].rename('VIX') if vix_p.exists() else None

prices = pd.DataFrame(assets_commodity).sort_index()
returns = prices.pct_change().dropna(how='all')

# Config
VOL_TARGET   = 7.0
LOOKBACK_WKS = 52
TOP_N        = 2
BLEND_FW     = 0.40
VOL_FAST     = 10
VOL_LONG     = 21
WIN_SIG      = 3.0
INITIAL_CAP  = 100_000.0
RISK_ON      = ['QQQ','XLV','XLE','GLD']  # commodity universe (no XLK)
RISK_OFF     = ['IEF','SHY']

def blended_vol(ret_series, date, fast=10, long=21, fw=0.40, sig=3.0):
    hist = ret_series.loc[:date].dropna()
    if len(hist) < long:
        return 15.0
    r = hist.iloc[-long:].copy()
    m, s = r.mean(), r.std()
    if s > 0:
        r = r.clip(m - sig*s, m + sig*s)
    fv = r.iloc[-fast:].std() * np.sqrt(52) * 100
    lv = r.std() * np.sqrt(52) * 100
    return fw * fv + (1-fw) * lv

def mom_score(sym, date, lb=52):
    try:
        h = prices.loc[:date, sym].dropna()
        if len(h) < lb:
            return None
        return (h.iloc[-1] / h.iloc[-lb] - 1)
    except:
        return None

def vix_mult(date):
    if vix_weekly is None:
        return 1.0
    try:
        v = vix_weekly.loc[:date].dropna().iloc[-1]
        if v > 40: return 0.25
        if v > 30: return 0.50
        if v > 25: return 0.75
        return 1.0
    except:
        return 1.0

def run_backtest(label, start_date, universe_risk_on):
    equity = INITIAL_CAP
    equity_log = []
    alloc_log = []
    
    dates = prices.loc[start_date:].index[LOOKBACK_WKS:]
    if len(dates) < 10:
        return None
    
    for date in dates:
        # Available risk-on assets
        avail = [s for s in universe_risk_on 
                 if s in prices.columns and not pd.isna(prices.loc[date, s])
                 and mom_score(s, date) is not None]
        scores = {s: mom_score(s, date) for s in avail}
        top = sorted(scores, key=lambda s: scores[s], reverse=True)[:TOP_N]
        
        # Abs momentum: SPY 3-week
        spy_3wk = None
        try:
            sh = prices.loc[:date,'SPY'].dropna()
            if len(sh) >= 3:
                spy_3wk = (sh.iloc[-1] / sh.iloc[-3] - 1)
        except: pass
        
        if (spy_3wk is not None and spy_3wk < -0.02) or not top:
            # Risk off
            for ro in RISK_OFF:
                if ro in prices.columns and not pd.isna(prices.loc[date, ro]):
                    holding = {ro: 1.0}
                    break
            else:
                holding = {}
        elif all(scores[s] > 0 for s in top):
            holding = {s: 1.0/len(top) for s in top}
        else:
            good = [s for s in top if scores[s] > 0]
            if good:
                holding = {s: 1.0/len(top) for s in good}
                rem = 1.0 - sum(holding.values())
                for ro in RISK_OFF:
                    if ro in prices.columns and not pd.isna(prices.loc[date, ro]) and rem > 0.01:
                        holding[ro] = rem
                        break
            else:
                for ro in RISK_OFF:
                    if ro in prices.columns and not pd.isna(prices.loc[date, ro]):
                        holding = {ro: 1.0}
                        break
                else:
                    holding = {}
        
        # Vol scale
        spy_ret = returns.loc[:date,'SPY'].dropna() if 'SPY' in returns.columns else pd.Series()
        rv = blended_vol(spy_ret, date, VOL_FAST, VOL_LONG, BLEND_FW, WIN_SIG)
        scale = min(1.0, VOL_TARGET / rv) if rv > 0 else 1.0
        vm = vix_mult(date)
        fs = scale * vm
        
        # Scale risk-on
        ro_syms = ['IEF','SHY']
        sh_final = {s: w*fs if s not in ro_syms else w for s, w in holding.items()}
        
        # Portfolio return
        try:
            ni = prices.index.get_loc(date) + 1
            if ni >= len(prices.index):
                pr = 0.0
            else:
                nd = prices.index[ni]
                pr = sum(w * returns.loc[nd, s] for s, w in sh_final.items()
                        if s in returns.columns and not pd.isna(returns.loc[nd, s]))
        except:
            pr = 0.0
        
        equity *= (1 + pr)
        equity_log.append({'date': date, 'equity': equity})
        alloc_log.append(pr)
    
    # Metrics
    eq_arr = np.array([e['equity'] for e in equity_log])
    rets = pd.Series(alloc_log)
    n_yrs = (dates[-1] - dates[0]).days / 365.25
    cagr = ((equity/INITIAL_CAP)**(1/n_yrs)-1)*100 if n_yrs > 0 else 0
    ann_v = rets.std()*np.sqrt(52)*100
    sharpe = rets.mean()/rets.std()*np.sqrt(52) if rets.std() > 0 else 0
    neg = rets[rets<0].std()
    sortino = rets.mean()/neg*np.sqrt(52) if neg > 0 else 0
    wr = (rets > 0).mean()*100
    rm = np.maximum.accumulate(eq_arr)
    mdd = ((eq_arr-rm)/rm).min()*100
    calmar = cagr/abs(mdd) if mdd != 0 else 0
    
    spy_s = prices.loc[dates[0],'SPY'] if 'SPY' in prices.columns else None
    spy_e = prices.loc[dates[-1],'SPY'] if 'SPY' in prices.columns else None
    spy_c = ((spy_e/spy_s)**(1/n_yrs)-1)*100 if spy_s and spy_e else None
    
    return {
        'label': label,
        'period': f'{dates[0].date()} → {dates[-1].date()}',
        'n_years': round(n_yrs,1),
        'cagr': round(cagr,2),
        'spy_cagr': round(spy_c,2) if spy_c else None,
        'sharpe': round(sharpe,3),
        'sortino': round(sortino,3),
        'calmar': round(calmar,3),
        'max_dd': round(mdd,2),
        'win_rate': round(wr,1),
        'ann_vol': round(ann_v,2),
        'final_equity': round(equity,2),
    }

# Run two variants
print('='*70)
print('  T3-13: COMMODITY UNIVERSE STRESS TEST')
print('  Risk-on: QQQ, XLV, XLE, GLD (XLK removed)')
print('='*70)

# Variant A: 2004–2013 (all assets available)
r_a = run_backtest('2004–2013 (Full commodity universe)', '2004-01-01', ['QQQ','XLV','XLE','GLD'])
# Variant B: 2000–2013 (GLD absent pre-2004, fallback to XLE only)
r_b = run_backtest('2000–2013 (Commodity, pre-GLD fallback)', '2000-01-01', ['QQQ','XLV','XLE','GLD'])
# Variant C: Standard (XLK instead of GLD) same period for comparison
r_c = run_backtest('2004–2013 (Standard: XLK, QQQ, XLV, XLE)', '2004-01-01', ['XLK','QQQ','XLV','XLE']) if False else None

for r in [r_a, r_b]:
    if r:
        print(f'\n  ── {r["label"]} ──')
        print(f'     Period:   {r["period"]}  ({r["n_years"]}y)')
        print(f'     CAGR:     {r["cagr"]:.2f}%  (SPY: {r["spy_cagr"]:.2f}%)')
        print(f'     Sharpe:   {r["sharpe"]:.3f}')
        print(f'     Sortino:  {r["sortino"]:.3f}')
        print(f'     Calmar:   {r["calmar"]:.3f}')
        print(f'     Max DD:   {r["max_dd"]:.2f}%')
        print(f'     Win Rate: {r["win_rate"]:.1f}%')
        print(f'     Final EQ: ${r["final_equity"]:,.0f}  ({r["final_equity"]/INITIAL_CAP:.2f}x)')
        print()
        print(f'     Gate: Sharpe≥1.5 {"✅" if r["sharpe"]>=1.5 else "❌"}  '
              f'Sortino≥1.0 {"✅" if r["sortino"]>=1.0 else "❌"}  '
              f'Calmar≥0.5 {"✅" if r["calmar"]>=0.5 else "❌"}  '
              f'MaxDD≤15% {"✅" if r["max_dd"]>=-15 else "❌"}  '
              f'WR≥55% {"✅" if r["win_rate"]>=55 else "❌"}')

out_dir = Path('/home/user/workspace/jarvis-repo-fresh/engine/validation_reports')
results_out = {'T3_13_commodity_stress': {'A': r_a, 'B': r_b}}
with open(out_dir / 'T3_13_commodity_stress.json', 'w') as f:
    json.dump(results_out, f, indent=2)
print(f'\n  Saved → engine/validation_reports/T3_13_commodity_stress.json')
