"""
BT-S2b: System 2 — ES/NQ Futures, Refined Signal Filter
=========================================================
Refinements from BT-S2 diagnostic:
  1. 6-bar compression-to-ATR only (highest PF=2.719, WR=65.7%)
  2. Singlefinder fires at +1 bar after ATR trigger only (WR=58.7%, PF=1.762)
  3. Full 24h session on futures (extended hours IS the alpha source)
  4. RTH (9:30–16:00) run as separate sub-cut for comparison

Futures specifics vs ETFs:
  - ES point value = $50/point, tick = 0.25 = $12.50
  - NQ point value = $20/point, tick = 0.25 = $5.00
  - Commission: $4.50 round-trip per contract (standard retail)
  - Slippage: 1 tick ($12.50 ES, $5.00 NQ) each way = $25/$10 RT
  - Margin: ~$15,000 ES / ~$21,000 NQ (not binding — we size by risk)
"""
import sys, warnings, json
sys.path.insert(0, '/home/user/workspace/jarvis-repo-fresh')
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
from pathlib import Path
from engine.strategy_c.tos_indicators import SatyATRLevels, PhaseCompression, CoreySinglefinder

# ── Config ────────────────────────────────────────────────────────────────────
INITIAL_CAP      = 50_000.0   # realistic futures account
RISK_PCT         = 0.01       # 1% risk per trade (futures = higher notional)
ATR_STOP_MUL     = 0.75
ATR_T1_MUL       = 1.00
ATR_T2_MUL       = 2.00
BACKSTOP_BARS    = 8
COMP_WINDOW_ONLY = 6          # ONLY accept 6-bar comp-to-ATR setups
SF_DELAY_ONLY    = 1          # ONLY accept SF firing at exactly +1 bar after ATR

# Futures contract specs
CONTRACT_SPECS = {
    'ES': {'point_value': 50,  'tick_size': 0.25, 'commission_rt': 4.50, 'slippage_ticks': 1},
    'NQ': {'point_value': 20,  'tick_size': 0.25, 'commission_rt': 4.50, 'slippage_ticks': 1},
}

# Session definitions (24h futures)
SESSION_MAP = {
    'OVERNIGHT': (0, 9),       # midnight to 9:30am
    'OPEN':      (9, 11),      # 9:30–11:30
    'MID':       (11, 14),     # 11:30–14:30
    'CLOSE':     (14, 16),     # 14:30–16:00
    'AFTER':     (16, 24),     # 16:00–midnight
}

def tag_session(dt):
    h = dt.hour
    if 0 <= h < 9:   return 'OVERNIGHT'
    if 9 <= h < 11:  return 'OPEN'
    if 11 <= h < 14: return 'MID'
    if 14 <= h < 16: return 'CLOSE'
    return 'AFTER'

# ── Data loader ───────────────────────────────────────────────────────────────
def load_futures(sym):
    p = Path(f'/home/user/workspace/jarvis-repo-fresh/engine/backtest/data/{sym}_1h.parquet')
    df = pd.read_parquet(p)
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.columns = [c.lower() for c in df.columns]
    df = df[['open','high','low','close','volume']].dropna()
    # Remove zero-volume bars (rollover artifacts, market closed)
    df = df[df['volume'] > 0].copy()
    # Remove weekend bars
    df = df[df.index.dayofweek < 5].copy()
    return df

# ── Signal computation ────────────────────────────────────────────────────────
def compute_signals(df):
    df2 = df.copy()
    df2 = SatyATRLevels().compute(df2)
    df2 = PhaseCompression().compute(df2)
    df2 = CoreySinglefinder().compute(df2)
    return df2

# ── Refined sequential detector ───────────────────────────────────────────────
def find_setups_refined(df, sym,
                         comp_window=COMP_WINDOW_ONLY,
                         sf_delay=SF_DELAY_ONLY,
                         session_filter=None):
    """
    Strict refined sequencer:
      Step 1: compressed == True (anchor)
      Step 2: atr_trigger_bull fires at exactly comp_window bars later
              (or within comp_window if comp_window is a range)
      Step 3: bullish_single fires at exactly +sf_delay bars after ATR trigger
    
    session_filter: list of session tags to include, None = all
    """
    setups = []
    n = len(df)
    last_entry_i = -1

    for i in range(len(df) - comp_window - sf_delay - BACKSTOP_BARS - 2):
        if not df.iloc[i]['compressed']:
            continue
        if i <= last_entry_i:
            continue

        comp_i = i

        # Scan for ATR trigger within comp_window
        atr_i = None
        for j in range(comp_i + 1, min(comp_i + comp_window + 1, n)):
            if df.iloc[j]['atr_trigger_bull']:
                atr_i = j
                break

        if atr_i is None:
            continue

        bars_comp_to_atr = atr_i - comp_i

        # SF must fire at exactly atr_i + sf_delay
        sf_target_i = atr_i + sf_delay
        if sf_target_i >= n:
            continue
        if not df.iloc[sf_target_i]['bullish_single']:
            continue

        sf_i = sf_target_i
        entry_bar   = sf_i
        entry_price = df.iloc[entry_bar]['close']
        atr_val     = df.iloc[entry_bar].get('atr14', np.nan)

        if pd.isna(atr_val) or atr_val <= 0:
            continue

        # Session tag
        sess = tag_session(df.index[entry_bar])
        if session_filter and sess not in session_filter:
            last_entry_i = entry_bar  # still advance to avoid re-triggering same comp
            continue

        stop = entry_price - ATR_STOP_MUL * atr_val
        t1   = entry_price + ATR_T1_MUL * atr_val
        t2   = entry_price + ATR_T2_MUL * atr_val

        # Futures sizing: risk 1% of capital
        spec = CONTRACT_SPECS.get(sym, CONTRACT_SPECS['ES'])
        risk_dollars  = INITIAL_CAP * RISK_PCT
        risk_per_contract = (entry_price - stop) * spec['point_value']
        n_contracts = max(1, int(risk_dollars / risk_per_contract)) if risk_per_contract > 0 else 1

        setups.append({
            'sym':              sym,
            'comp_i':           comp_i,
            'atr_i':            atr_i,
            'entry_i':          entry_bar,
            'entry_date':       df.index[entry_bar],
            'entry_price':      entry_price,
            'atr':              atr_val,
            'stop':             stop,
            't1':               t1,
            't2':               t2,
            'n_contracts':      n_contracts,
            'session':          sess,
            'bars_comp_to_atr': bars_comp_to_atr,
            'bars_atr_to_sf':   sf_delay,
            'point_value':      spec['point_value'],
            'commission_rt':    spec['commission_rt'],
            'slippage_pts':     spec['slippage_ticks'] * spec['tick_size'],
        })

        last_entry_i = entry_bar

    return setups

# ── Trade simulator ───────────────────────────────────────────────────────────
def simulate_trades(df, setups):
    trades = []
    n = len(df)

    for s in setups:
        entry_i     = s['entry_i']
        entry_price = s['entry_price']
        stop        = s['stop']
        t1          = s['t1']
        t2          = s['t2']
        nc          = s['n_contracts']
        pv          = s['point_value']
        comm        = s['commission_rt'] * nc
        slip        = s['slippage_pts'] * nc * pv  # slippage in dollars

        half_nc     = max(1, nc // 2)
        remain_nc   = nc - half_nc
        t1_hit      = False
        be_stop     = entry_price
        exit_type   = None
        exit_half   = None
        exit_runner = None
        exit_date   = None
        bars_held   = 0
        pnl         = 0.0

        for fwd in range(entry_i + 1, min(entry_i + BACKSTOP_BARS + 20, n)):
            bar = df.iloc[fwd]
            bars_held += 1

            if not t1_hit:
                # Stop
                if bar['low'] <= stop:
                    exit_type   = 'STOP'
                    exit_half   = stop
                    exit_runner = stop
                    exit_date   = df.index[fwd]
                    pnl = (stop - entry_price) * nc * pv - comm - slip
                    break

                # T1
                if bar['high'] >= t1:
                    t1_hit    = True
                    exit_half = t1
                    stop      = be_stop  # move to breakeven

                    if bars_held >= BACKSTOP_BARS:
                        exit_type   = 'T1_THEN_BACKSTOP'
                        exit_runner = bar['close']
                        exit_date   = df.index[fwd]
                        pnl = ((t1 - entry_price) * half_nc * pv +
                               (bar['close'] - entry_price) * remain_nc * pv
                               - comm - slip)
                        break
                    continue

                # Backstop
                if bars_held >= BACKSTOP_BARS:
                    exit_type   = 'BACKSTOP'
                    exit_half   = bar['close']
                    exit_runner = bar['close']
                    exit_date   = df.index[fwd]
                    pnl = (bar['close'] - entry_price) * nc * pv - comm - slip
                    break

            else:
                # BE stop
                if bar['low'] <= stop:
                    exit_type   = 'T1_THEN_BE_STOP'
                    exit_runner = stop
                    exit_date   = df.index[fwd]
                    pnl = ((exit_half - entry_price) * half_nc * pv +
                           (stop - entry_price) * remain_nc * pv
                           - comm - slip)
                    break

                # T2
                if bar['high'] >= t2:
                    exit_type   = 'T1_T2'
                    exit_runner = t2
                    exit_date   = df.index[fwd]
                    pnl = ((exit_half - entry_price) * half_nc * pv +
                           (t2 - entry_price) * remain_nc * pv
                           - comm - slip)
                    break

                if bars_held >= BACKSTOP_BARS + 4:
                    exit_type   = 'T1_RUNNER_BACKSTOP'
                    exit_runner = bar['close']
                    exit_date   = df.index[fwd]
                    pnl = ((exit_half - entry_price) * half_nc * pv +
                           (bar['close'] - entry_price) * remain_nc * pv
                           - comm - slip)
                    break
        else:
            last = df.iloc[min(entry_i + BACKSTOP_BARS + 19, n - 1)]
            exit_type   = 'END_OF_DATA'
            exit_half   = last['close']
            exit_runner = last['close']
            exit_date   = df.index[min(entry_i + BACKSTOP_BARS + 19, n - 1)]
            if t1_hit:
                pnl = ((exit_half - entry_price) * half_nc * pv +
                       (exit_runner - entry_price) * remain_nc * pv
                       - comm - slip)
            else:
                pnl = (exit_runner - entry_price) * nc * pv - comm - slip
            bars_held = min(BACKSTOP_BARS + 19, n - 1 - entry_i)

        trades.append({
            'symbol':       s['sym'],
            'entry_date':   s['entry_date'],
            'exit_date':    exit_date,
            'session':      s['session'],
            'entry_price':  round(entry_price, 2),
            'stop':         round(s['stop'], 2),
            't1':           round(t1, 2),
            't2':           round(t2, 2),
            'atr':          round(s['atr'], 2),
            'n_contracts':  nc,
            'exit_type':    exit_type,
            'exit_half':    round(exit_half or 0, 2),
            'exit_runner':  round(exit_runner or 0, 2),
            'pnl':          round(pnl, 2),
            'bars_held':    bars_held,
            't1_hit':       t1_hit,
            'bars_comp_to_atr': s['bars_comp_to_atr'],
            'rr_achieved':  round((exit_runner - entry_price) / (entry_price - s['stop']), 3)
                            if (entry_price - s['stop']) > 0 and exit_runner else 0,
        })

    return trades

# ── Metrics ───────────────────────────────────────────────────────────────────
def metrics(trades, label=''):
    if len(trades) < 3:
        return {'label': label, 'n_trades': len(trades), 'note': 'insufficient data'}
    df_t = pd.DataFrame(trades)
    n    = len(df_t)
    wins = df_t[df_t['pnl'] > 0]
    loss = df_t[df_t['pnl'] <= 0]
    wr   = len(wins) / n * 100
    gw   = wins['pnl'].sum()
    gl   = loss['pnl'].sum()
    pf   = gw / abs(gl) if gl != 0 else float('inf')
    aw   = wins['pnl'].mean() if len(wins) else 0
    al   = loss['pnl'].mean() if len(loss) else 0
    rr   = abs(aw / al) if al != 0 else 0
    t1r  = df_t['t1_hit'].mean() * 100
    t1h  = df_t[df_t['t1_hit']]
    t2r  = (t1h['exit_type'] == 'T1_T2').mean() * 100 if len(t1h) else 0

    daily = df_t.set_index('entry_date')['pnl'].resample('D').sum()
    sh    = daily.mean() / daily.std() * np.sqrt(252) if daily.std() > 0 else 0

    eq    = INITIAL_CAP + df_t['pnl'].cumsum().values
    arr   = np.concatenate([[INITIAL_CAP], eq])
    roll  = np.maximum.accumulate(arr)
    mdd   = ((arr - roll) / roll).min() * 100
    total = df_t['pnl'].sum()

    # Session breakdown
    sess_stats = {}
    for sess in ['OVERNIGHT', 'OPEN', 'MID', 'CLOSE', 'AFTER']:
        sub = df_t[df_t['session'] == sess]
        if not len(sub): continue
        sw = sub[sub['pnl'] > 0]
        sl = sub[sub['pnl'] <= 0]
        sess_stats[sess] = {
            'n':         len(sub),
            'win_rate':  round(len(sw) / len(sub) * 100, 1),
            'pf':        round(sw['pnl'].sum() / abs(sl['pnl'].sum()), 3)
                         if sl['pnl'].sum() != 0 else float('inf'),
            'avg_pnl':   round(sub['pnl'].mean(), 2),
            'total_pnl': round(sub['pnl'].sum(), 2),
        }

    exit_counts = df_t['exit_type'].value_counts().to_dict()

    return {
        'label':        label,
        'n_trades':     n,
        'win_rate':     round(wr, 2),
        'profit_factor': round(pf, 3),
        'sharpe':       round(sh, 3),
        'rr_ratio':     round(rr, 3),
        'avg_win':      round(aw, 2),
        'avg_loss':     round(al, 2),
        't1_hit_rate':  round(t1r, 1),
        't2_hit_rate':  round(t2r, 1),
        'total_pnl':    round(total, 2),
        'max_dd':       round(mdd, 2),
        'final_equity': round(INITIAL_CAP + total, 2),
        'session_breakdown': sess_stats,
        'exit_breakdown':    exit_counts,
    }

def print_metrics(m):
    if 'note' in m:
        print(f"  {m['label']}: {m['note']}")
        return
    print(f"  Trades:          {m['n_trades']}")
    print(f"  Win Rate:        {m['win_rate']:.1f}%")
    print(f"  Profit Factor:   {m['profit_factor']:.3f}")
    print(f"  Sharpe:          {m['sharpe']:.3f}")
    print(f"  R:R:             {m['rr_ratio']:.3f}x")
    print(f"  T1 Hit Rate:     {m['t1_hit_rate']:.1f}%")
    print(f"  T2 Hit Rate:     {m['t2_hit_rate']:.1f}%")
    print(f"  Avg Win:         ${m['avg_win']:,.2f}")
    print(f"  Avg Loss:        ${m['avg_loss']:,.2f}")
    print(f"  Total PnL:       ${m['total_pnl']:,.2f}")
    print(f"  Max DD:          {m['max_dd']:.2f}%")
    print(f"  Final Equity:    ${m['final_equity']:,.2f}")

def print_sessions(m):
    if 'session_breakdown' not in m: return
    for sess, ss in m['session_breakdown'].items():
        print(f"    {sess:<12} n={ss['n']:>3}  WR:{ss['win_rate']:.1f}%  "
              f"PF:{ss['pf']:.3f}  avg:${ss['avg_pnl']:>8.2f}  total:${ss['total_pnl']:>10.2f}")

def print_exits(m, trades):
    if 'exit_breakdown' not in m: return
    df_t = pd.DataFrame(trades)
    for et, cnt in sorted(m['exit_breakdown'].items(), key=lambda x: -x[1]):
        sub = df_t[df_t['exit_type'] == et]
        swr = len(sub[sub['pnl'] > 0]) / len(sub) * 100
        print(f"    {et:<28} n={cnt:>3}  WR:{swr:.0f}%  avg:${sub['pnl'].mean():>8.2f}")

def eval_gates(m):
    if 'note' in m:
        return [], 0
    g = [
        ('Win Rate ≥ 58%',        m['win_rate'],        m['win_rate']        >= 58.0),
        ('Profit Factor ≥ 1.50',  m['profit_factor'],   m['profit_factor']   >= 1.50),
        ('Sharpe ≥ 1.20',         m['sharpe'],          m['sharpe']          >= 1.20),
        ('T1 Hit Rate ≥ 55%',     m['t1_hit_rate'],     m['t1_hit_rate']     >= 55.0),
        ('N ≥ 20 trades',         m['n_trades'],        m['n_trades']        >= 20),
        ('Max DD ≤ 20%',          m['max_dd'],          m['max_dd']          >= -20.0),
        ('R:R ≥ 1.0',             m['rr_ratio'],        m['rr_ratio']        >= 1.0),
    ]
    return g, sum(ok for _, _, ok in g)

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    all_results = {}
    out_dir = Path('/home/user/workspace/jarvis-repo-fresh/engine/validation_reports')

    for sym in ['ES', 'NQ']:
        print(f"\n{'='*65}")
        print(f"  BT-S2b: {sym} 1h Futures — Refined TOS Signal")
        print(f"  Filter: 6-bar compression + SF at +1 bar")
        print(f"{'='*65}")

        df = load_futures(sym)
        print(f"  Data: {len(df)} bars  {df.index[0].date()} → {df.index[-1].date()}")
        print(f"  RTH bars: {len(df[(df.index.hour>=9)&(df.index.hour<16)])}  "
              f"Extended: {len(df[(df.index.hour>=16)|(df.index.hour<9)])}")

        print(f"  Computing signals...")
        df_sig = compute_signals(df)

        # ── Run A: All sessions (24h) ──────────────────────────────────────────
        print(f"\n  ── Cut A: All sessions (24h), 6-bar + SF+1 ──")
        setups_all = find_setups_refined(df_sig, sym, comp_window=6, sf_delay=1, session_filter=None)
        print(f"  Setups found: {len(setups_all)}")
        if setups_all:
            sess_dist = pd.Series([s['session'] for s in setups_all]).value_counts()
            print(f"  Session dist: {sess_dist.to_dict()}")
            trades_all = simulate_trades(df_sig, setups_all)
            m_all = metrics(trades_all, f'{sym} All Sessions')
            print_metrics(m_all)
            print(f"\n  Sessions:")
            print_sessions(m_all)
            print(f"\n  Exits:")
            print_exits(m_all, trades_all)
            gates, passed = eval_gates(m_all)
            print(f"\n  Gates: {passed}/7")
            for label, val, ok in gates:
                print(f"    {'✅' if ok else '❌'}  {label:<30}  {val:.3f}")
            pd.DataFrame(trades_all).to_csv(out_dir / f'BT_S2b_{sym}_all_trades.csv', index=False)
            all_results[f'{sym}_all'] = m_all

        # ── Run B: After-hours only ────────────────────────────────────────────
        print(f"\n  ── Cut B: After-hours only (16:00–24:00), 6-bar + SF+1 ──")
        setups_ah = find_setups_refined(df_sig, sym, comp_window=6, sf_delay=1,
                                         session_filter=['AFTER'])
        print(f"  Setups found: {len(setups_ah)}")
        if setups_ah:
            trades_ah = simulate_trades(df_sig, setups_ah)
            m_ah = metrics(trades_ah, f'{sym} After-Hours')
            print_metrics(m_ah)
            gates, passed = eval_gates(m_ah)
            print(f"\n  Gates: {passed}/7")
            for label, val, ok in gates:
                print(f"    {'✅' if ok else '❌'}  {label:<30}  {val:.3f}")
            pd.DataFrame(trades_ah).to_csv(out_dir / f'BT_S2b_{sym}_ah_trades.csv', index=False)
            all_results[f'{sym}_ah'] = m_ah

        # ── Run C: RTH only (9:30–16:00) ──────────────────────────────────────
        print(f"\n  ── Cut C: RTH only (9:30–16:00), 6-bar + SF+1 ──")
        setups_rth = find_setups_refined(df_sig, sym, comp_window=6, sf_delay=1,
                                          session_filter=['OPEN','MID','CLOSE'])
        print(f"  Setups found: {len(setups_rth)}")
        if setups_rth:
            trades_rth = simulate_trades(df_sig, setups_rth)
            m_rth = metrics(trades_rth, f'{sym} RTH')
            print_metrics(m_rth)
            gates, passed = eval_gates(m_rth)
            print(f"\n  Gates: {passed}/7")
            for label, val, ok in gates:
                print(f"    {'✅' if ok else '❌'}  {label:<30}  {val:.3f}")
            all_results[f'{sym}_rth'] = m_rth

        # ── Run D: Overnight session (0:00–9:30) ──────────────────────────────
        print(f"\n  ── Cut D: Overnight (00:00–09:30), 6-bar + SF+1 ──")
        setups_on = find_setups_refined(df_sig, sym, comp_window=6, sf_delay=1,
                                         session_filter=['OVERNIGHT'])
        print(f"  Setups found: {len(setups_on)}")
        if setups_on:
            trades_on = simulate_trades(df_sig, setups_on)
            m_on = metrics(trades_on, f'{sym} Overnight')
            print_metrics(m_on)
            gates, passed = eval_gates(m_on)
            print(f"\n  Gates: {passed}/7  ", end='')
            print('  '.join(f"{'✅' if ok else '❌'}" for _,_,ok in gates))
            all_results[f'{sym}_overnight'] = m_on

    # ── Bonus: broad filter comparison (any comp_window, sf_delay 0-3) ─────────
    print(f"\n\n{'='*65}")
    print(f"  COMPARISON: Broad filter (any window) vs Refined (6-bar+SF+1)")
    print(f"{'='*65}")
    from engine.scripts.backtest_system2 import find_setups as find_broad, simulate_trades as sim_broad, compute_metrics as metrics_broad, load_1h

    for sym_etf, fut_sym in [('SPY','ES'), ('QQQ','NQ')]:
        # Already have ETF broad results from BT-S2 — load them
        try:
            etf_t = pd.read_csv(f'/home/user/workspace/jarvis-repo-fresh/engine/validation_reports/BT_S2_{sym_etf}_trades.csv')
            etf_ah = etf_t[etf_t['session'] == 'AFTER']
            if len(etf_ah) > 0:
                m = metrics_broad(etf_ah.to_dict('records'), label=f'{sym_etf} ETF AH broad')
                gates, p = eval_gates(m) if hasattr(m, '__contains__') else ([], 0)
                print(f"\n  {sym_etf} ETF after-hours (broad filter):  "
                      f"n={m['n_trades']}  WR:{m['win_rate']:.1f}%  PF:{m['profit_factor']:.3f}  Sh:{m['sharpe']:.3f}")
        except:
            pass

    # Save all results
    with open(out_dir / 'BT_S2b_results.json', 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n\n  All results saved → engine/validation_reports/BT_S2b_*")
