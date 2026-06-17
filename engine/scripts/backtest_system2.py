"""
BT-S2: System 2 — TOS Intraday Sequential Signal Backtest
==========================================================
Instruments:  SPY 1h + QQQ 1h
Signal stack: Phase Compression → ATR Trigger (within 6 bars) → Singlefinder (within 3 bars)
Direction:    Long only (initial pass)
Exit:         Scaled — 50% at T1=1.0×ATR, 50% runner to T2=2.0×ATR
Stop:         0.75×ATR from entry, moved to breakeven after T1
Backstop:     8 bars no T1 hit → exit full
Risk:         2% of initial capital per trade ($200 on $10k)
Session tags: OPEN (9:30–11:30), MID (11:30–14:30), CLOSE (14:30–16:00)
"""
import sys, warnings, json
sys.path.insert(0, '/home/user/workspace/jarvis-repo-fresh')
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import time
from engine.strategy_c.tos_indicators import SatyATRLevels, PhaseCompression, CoreySinglefinder

# ── Config ────────────────────────────────────────────────────────────────────
INITIAL_CAP      = 10_000.0
RISK_PCT         = 0.02          # 2% risk per trade
ATR_STOP_MUL     = 0.75          # stop = 0.75×ATR below entry
ATR_T1_MUL       = 1.00          # T1 = 1.0×ATR (take 50%)
ATR_T2_MUL       = 2.00          # T2 = 2.0×ATR (runner exits here)
BACKSTOP_BARS    = 8             # max bars in trade before forced exit
COMP_WINDOW      = 6             # ATR trigger must fire within 6 bars of compression
SF_WINDOW        = 3             # Singlefinder must confirm within 3 bars of ATR trigger
MAX_TRADES_DAY   = 3             # max concurrent/daily setups tracked
COMMISSION_RT    = 0.02          # round-trip commission per share ($0.01 each way)

# Session window boundaries (ET hour, 24h)
OPEN_START   = 9
OPEN_END     = 11
MID_START    = 11
MID_END      = 14
CLOSE_START  = 14
CLOSE_END    = 16

# ── Data loader ───────────────────────────────────────────────────────────────
def load_1h(sym):
    p = Path(f'/home/user/workspace/jarvis-repo-fresh/engine/backtest/data/{sym}_1h.parquet')
    df = pd.read_parquet(p)
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.columns = [c.lower() for c in df.columns]
    df = df[['open','high','low','close','volume']].dropna()
    return df

# ── Signal computation ────────────────────────────────────────────────────────
def compute_signals(df):
    df2 = df.copy()
    df2 = SatyATRLevels().compute(df2)
    df2 = PhaseCompression().compute(df2)
    df2 = CoreySinglefinder().compute(df2)
    return df2

# ── Session tagger ────────────────────────────────────────────────────────────
def tag_session(dt):
    h = dt.hour
    if OPEN_START <= h < OPEN_END:
        return 'OPEN'
    elif MID_START <= h < MID_END:
        return 'MID'
    elif CLOSE_START <= h < CLOSE_END:
        return 'CLOSE'
    else:
        return 'AFTER'

# ── Sequential signal detector ────────────────────────────────────────────────
def find_setups(df):
    """
    Strict sequential scan:
      Step 1: compressed == True  → anchor bar
      Step 2: atr_trigger_bull == True within COMP_WINDOW bars of anchor
      Step 3: bullish_single == True within SF_WINDOW bars of step 2
    
    Returns list of setup dicts with entry bar index.
    No overlapping setups — once a setup fires, next compression
    anchor must be after the SF bar.
    """
    setups = []
    n = len(df)
    i = 0
    last_entry_i = -1

    while i < n - BACKSTOP_BARS - 2:
        # Step 1: find compression bar
        if not df.iloc[i]['compressed']:
            i += 1
            continue

        # Skip if too close to last entry (avoid overlapping trades)
        if i <= last_entry_i:
            i += 1
            continue

        comp_i = i

        # Step 2: scan for ATR trigger bull within COMP_WINDOW bars
        atr_i = None
        for j in range(comp_i + 1, min(comp_i + COMP_WINDOW + 1, n)):
            if df.iloc[j]['atr_trigger_bull']:
                atr_i = j
                break

        if atr_i is None:
            i += 1
            continue

        # Step 3: scan for bullish singlefinder within SF_WINDOW bars of ATR trigger
        sf_i = None
        for k in range(atr_i, min(atr_i + SF_WINDOW + 1, n)):
            if df.iloc[k]['bullish_single']:
                sf_i = k
                break

        if sf_i is None:
            i = atr_i + 1
            continue

        # Valid setup — entry is the close of the SF bar
        entry_bar   = sf_i
        entry_price = df.iloc[entry_bar]['close']
        atr_val     = df.iloc[entry_bar]['atr14'] if 'atr14' in df.columns else None

        if atr_val is None or atr_val <= 0 or np.isnan(atr_val):
            i = sf_i + 1
            continue

        stop   = entry_price - ATR_STOP_MUL * atr_val
        t1     = entry_price + ATR_T1_MUL * atr_val
        t2     = entry_price + ATR_T2_MUL * atr_val
        size   = max(1, int((INITIAL_CAP * RISK_PCT) / (entry_price - stop)))

        setups.append({
            'comp_i':      comp_i,
            'atr_i':       atr_i,
            'entry_i':     entry_bar,
            'entry_date':  df.index[entry_bar],
            'entry_price': entry_price,
            'atr':         atr_val,
            'stop':        stop,
            't1':          t1,
            't2':          t2,
            'size':        size,
            'session':     tag_session(df.index[entry_bar]),
            'bars_comp_to_atr': atr_i - comp_i,
            'bars_atr_to_sf':   sf_i - atr_i,
        })

        last_entry_i = entry_bar
        i = sf_i + 1

    return setups

# ── Trade simulator ───────────────────────────────────────────────────────────
def simulate_trades(df, setups):
    """
    For each setup, walk forward bar-by-bar:
    - Check stop hit (low crosses stop)
    - Check T1 hit (high reaches t1) → take 50%, move stop to BE
    - Check T2 hit after T1 (high reaches t2) → take remaining 50%
    - Backstop: 8 bars without T1 → exit full at close
    """
    trades = []
    n = len(df)

    for s in setups:
        entry_i     = s['entry_i']
        entry_price = s['entry_price']
        stop        = s['stop']
        t1          = s['t1']
        t2          = s['t2']
        size        = s['size']
        atr         = s['atr']

        t1_hit      = False
        be_stop     = entry_price  # breakeven stop after T1
        half_size   = size // 2
        remain_size = size - half_size

        exit_type   = None
        exit_price_half   = None
        exit_price_runner = None
        exit_date   = None
        bars_held   = 0
        pnl         = 0.0

        for fwd in range(entry_i + 1, min(entry_i + BACKSTOP_BARS + 20, n)):
            bar = df.iloc[fwd]
            bars_held += 1

            if not t1_hit:
                # Check stop first (stop > low on the bar)
                if bar['low'] <= stop:
                    exit_type = 'STOP'
                    exit_price_half   = stop
                    exit_price_runner = stop
                    exit_date = df.index[fwd]
                    pnl = (stop - entry_price) * size - COMMISSION_RT * size
                    break

                # Check T1 hit
                if bar['high'] >= t1:
                    t1_hit = True
                    exit_price_half = t1
                    # Move stop to breakeven for runner
                    stop = be_stop  # already set to entry_price

                    # Check backstop on runner
                    if bars_held >= BACKSTOP_BARS:
                        exit_type = 'T1_THEN_BACKSTOP'
                        exit_price_runner = bar['close']
                        exit_date = df.index[fwd]
                        pnl = ((t1 - entry_price) * half_size +
                               (bar['close'] - entry_price) * remain_size
                               - COMMISSION_RT * size)
                        break
                    continue

                # Backstop — 8 bars with no T1
                if bars_held >= BACKSTOP_BARS:
                    exit_type = 'BACKSTOP'
                    exit_price_half   = bar['close']
                    exit_price_runner = bar['close']
                    exit_date = df.index[fwd]
                    pnl = (bar['close'] - entry_price) * size - COMMISSION_RT * size
                    break

            else:
                # T1 already hit — managing runner
                # Check BE stop (stop is now entry_price)
                if bar['low'] <= stop:
                    exit_type = 'T1_THEN_BE_STOP'
                    exit_price_runner = stop
                    exit_date = df.index[fwd]
                    pnl = ((exit_price_half - entry_price) * half_size +
                           (stop - entry_price) * remain_size
                           - COMMISSION_RT * size)
                    break

                # Check T2 hit
                if bar['high'] >= t2:
                    exit_type = 'T1_T2'
                    exit_price_runner = t2
                    exit_date = df.index[fwd]
                    pnl = ((exit_price_half - entry_price) * half_size +
                           (t2 - entry_price) * remain_size
                           - COMMISSION_RT * size)
                    break

                # Backstop on runner (separate counter after T1)
                runner_bars = fwd - entry_i
                if runner_bars >= BACKSTOP_BARS + 4:  # give runner extra room
                    exit_type = 'T1_RUNNER_BACKSTOP'
                    exit_price_runner = bar['close']
                    exit_date = df.index[fwd]
                    pnl = ((exit_price_half - entry_price) * half_size +
                           (bar['close'] - entry_price) * remain_size
                           - COMMISSION_RT * size)
                    break

        else:
            # Hit loop end without exit — exit at last bar
            last_bar = df.iloc[min(entry_i + BACKSTOP_BARS + 19, n-1)]
            exit_type = 'END_OF_DATA'
            exit_price_half = last_bar['close']
            exit_price_runner = last_bar['close']
            exit_date = df.index[min(entry_i + BACKSTOP_BARS + 19, n-1)]
            if t1_hit:
                pnl = ((exit_price_half - entry_price) * half_size +
                       (exit_price_runner - entry_price) * remain_size
                       - COMMISSION_RT * size)
            else:
                pnl = (exit_price_runner - entry_price) * size - COMMISSION_RT * size
            bars_held = min(BACKSTOP_BARS + 19, n - 1 - entry_i)

        trades.append({
            'entry_date':        s['entry_date'],
            'exit_date':         exit_date,
            'symbol':            s.get('symbol', 'UNK'),
            'session':           s['session'],
            'entry_price':       round(entry_price, 4),
            'stop':              round(s['stop'], 4),
            't1':                round(t1, 4),
            't2':                round(t2, 4),
            'atr':               round(atr, 4),
            'size':              size,
            'exit_type':         exit_type,
            'exit_price_half':   round(exit_price_half or 0, 4),
            'exit_price_runner': round(exit_price_runner or 0, 4),
            'pnl':               round(pnl, 2),
            'bars_held':         bars_held,
            't1_hit':            t1_hit,
            'bars_comp_to_atr':  s['bars_comp_to_atr'],
            'bars_atr_to_sf':    s['bars_atr_to_sf'],
            'rr_achieved':       round((exit_price_runner - entry_price) / (entry_price - s['stop']), 3)
                                 if (entry_price - s['stop']) > 0 else 0,
        })

    return trades

# ── Metrics engine ────────────────────────────────────────────────────────────
def compute_metrics(trades, label=''):
    if not trades:
        return {}
    df_t = pd.DataFrame(trades)
    n = len(df_t)
    wins = df_t[df_t['pnl'] > 0]
    losses = df_t[df_t['pnl'] <= 0]

    win_rate  = len(wins) / n * 100
    avg_win   = wins['pnl'].mean() if len(wins) else 0
    avg_loss  = losses['pnl'].mean() if len(losses) else 0
    gw        = wins['pnl'].sum()
    gl        = losses['pnl'].sum()
    pf        = gw / abs(gl) if gl != 0 else float('inf')
    total_pnl = df_t['pnl'].sum()
    rr        = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    # T1 hit rate
    t1_rate = df_t['t1_hit'].mean() * 100
    # T2 rate among T1 hits
    t1_hits = df_t[df_t['t1_hit']]
    t2_rate = (t1_hits['exit_type'] == 'T1_T2').mean() * 100 if len(t1_hits) else 0

    # Sharpe (per-trade basis, annualized approx)
    daily_pnl = df_t.set_index('entry_date')['pnl'].resample('D').sum()
    sharpe = (daily_pnl.mean() / daily_pnl.std() * np.sqrt(252)) if daily_pnl.std() > 0 else 0

    # Equity curve
    eq = INITIAL_CAP + df_t['pnl'].cumsum()
    eq_arr = np.concatenate([[INITIAL_CAP], eq.values])
    roll_max = np.maximum.accumulate(eq_arr)
    dd = (eq_arr - roll_max) / roll_max
    max_dd = dd.min() * 100
    final_eq = eq_arr[-1]

    # Exit breakdown
    exit_counts = df_t['exit_type'].value_counts().to_dict()

    # Session breakdown
    sess_stats = {}
    for sess in ['OPEN', 'MID', 'CLOSE']:
        sub = df_t[df_t['session'] == sess]
        if len(sub) == 0:
            continue
        sess_stats[sess] = {
            'n': len(sub),
            'win_rate': round(len(sub[sub['pnl'] > 0]) / len(sub) * 100, 1),
            'pf': round(sub[sub['pnl']>0]['pnl'].sum() / abs(sub[sub['pnl']<=0]['pnl'].sum()), 3)
                  if sub[sub['pnl']<=0]['pnl'].sum() != 0 else float('inf'),
            'avg_pnl': round(sub['pnl'].mean(), 2),
            'total_pnl': round(sub['pnl'].sum(), 2),
        }

    return {
        'label':       label,
        'n_trades':    n,
        'win_rate':    round(win_rate, 2),
        'profit_factor': round(pf, 3),
        'sharpe':      round(sharpe, 3),
        'avg_win':     round(avg_win, 2),
        'avg_loss':    round(avg_loss, 2),
        'rr_ratio':    round(rr, 3),
        't1_hit_rate': round(t1_rate, 1),
        't2_hit_rate': round(t2_rate, 1),
        'total_pnl':   round(total_pnl, 2),
        'final_equity': round(final_eq, 2),
        'max_dd':      round(max_dd, 2),
        'exit_breakdown': exit_counts,
        'session_breakdown': sess_stats,
    }

# ── Gate evaluator ────────────────────────────────────────────────────────────
def eval_gates(m):
    gates = [
        ('Win Rate ≥ 58%',       m['win_rate'],      m['win_rate']      >= 58.0),
        ('Profit Factor ≥ 1.50', m['profit_factor'], m['profit_factor'] >= 1.50),
        ('Sharpe ≥ 1.20',        m['sharpe'],        m['sharpe']        >= 1.20),
        ('T1 Hit Rate ≥ 55%',    m['t1_hit_rate'],   m['t1_hit_rate']   >= 55.0),
        ('N ≥ 30 trades',        m['n_trades'],      m['n_trades']      >= 30),
        ('Max DD ≤ 20%',         m['max_dd'],        m['max_dd']        >= -20.0),
        ('R:R ≥ 1.0',            m['rr_ratio'],      m['rr_ratio']      >= 1.0),
    ]
    return gates

# ── Main runner ───────────────────────────────────────────────────────────────
def run_bt(sym):
    print(f"\n{'='*65}")
    print(f"  BT-S2: {sym} 1h — TOS Sequential Signal Backtest")
    print(f"{'='*65}")

    df = load_1h(sym)
    print(f"  Data: {len(df)} bars  {df.index[0].date()} → {df.index[-1].date()}")

    print(f"  Computing signals...")
    df_sig = compute_signals(df)

    # Check ATR column name
    atr_col = 'atr14' if 'atr14' in df_sig.columns else None
    if atr_col is None:
        print("  ERROR: ATR column not found")
        return None, None

    print(f"  Finding setups (strict sequential)...")
    setups = find_setups(df_sig)
    for s in setups:
        s['symbol'] = sym

    print(f"  Found {len(setups)} setups")

    if not setups:
        print("  No setups found — check signal parameters")
        return None, None

    # Session distribution of setups
    from collections import Counter
    sess_dist = Counter(s['session'] for s in setups)
    print(f"  Setup sessions: {dict(sess_dist)}")

    print(f"  Simulating trades...")
    trades = simulate_trades(df_sig, setups)

    m = compute_metrics(trades, label=sym)

    print(f"\n  ── Results ──")
    print(f"  Trades:          {m['n_trades']}")
    print(f"  Win Rate:        {m['win_rate']:.1f}%")
    print(f"  Profit Factor:   {m['profit_factor']:.3f}")
    print(f"  Sharpe:          {m['sharpe']:.3f}")
    print(f"  R:R (avg):       {m['rr_ratio']:.3f}x")
    print(f"  T1 Hit Rate:     {m['t1_hit_rate']:.1f}%")
    print(f"  T2 Hit Rate:     {m['t2_hit_rate']:.1f}%  (of T1 hits)")
    print(f"  Avg Win:         ${m['avg_win']:.2f}")
    print(f"  Avg Loss:        ${m['avg_loss']:.2f}")
    print(f"  Total PnL:       ${m['total_pnl']:.2f}")
    print(f"  Final Equity:    ${m['final_equity']:,.2f}")
    print(f"  Max DD:          {m['max_dd']:.2f}%")

    print(f"\n  ── Exit Breakdown ──")
    for et, cnt in sorted(m['exit_breakdown'].items(), key=lambda x: -x[1]):
        sub = [t for t in trades if t['exit_type'] == et]
        sub_wr = len([t for t in sub if t['pnl'] > 0]) / len(sub) * 100
        sub_avg = np.mean([t['pnl'] for t in sub])
        print(f"    {et:<28} {cnt:>4}  WR:{sub_wr:.0f}%  avg:${sub_avg:>7.2f}")

    print(f"\n  ── Session Breakdown ──")
    for sess, ss in m['session_breakdown'].items():
        print(f"    {sess:<8}  n={ss['n']:>3}  WR:{ss['win_rate']:.1f}%  "
              f"PF:{ss['pf']:.3f}  avg:${ss['avg_pnl']:.2f}  total:${ss['total_pnl']:.2f}")

    print(f"\n  ── Gate Scorecard ──")
    passed = 0
    gates = eval_gates(m)
    for label, val, ok in gates:
        if ok: passed += 1
        print(f"    {'✅' if ok else '❌'}  {label:<30}  got {val:.3f}")
    print(f"\n  Gates passed: {passed}/{len(gates)}")

    return trades, m

# ── Run both instruments ──────────────────────────────────────────────────────
if __name__ == '__main__':
    all_results = {}
    all_trades  = {}

    for sym in ['SPY', 'QQQ']:
        trades, metrics = run_bt(sym)
        if metrics:
            all_results[sym] = metrics
            all_trades[sym]  = trades

    # Combined stats
    if len(all_results) == 2:
        combined_trades = all_trades['SPY'] + all_trades['QQQ']
        cm = compute_metrics(combined_trades, label='COMBINED')
        print(f"\n{'='*65}")
        print(f"  COMBINED (SPY + QQQ)")
        print(f"{'='*65}")
        print(f"  Trades:          {cm['n_trades']}")
        print(f"  Win Rate:        {cm['win_rate']:.1f}%")
        print(f"  Profit Factor:   {cm['profit_factor']:.3f}")
        print(f"  Sharpe:          {cm['sharpe']:.3f}")
        print(f"  R:R (avg):       {cm['rr_ratio']:.3f}x")
        print(f"  T1 Hit Rate:     {cm['t1_hit_rate']:.1f}%")
        print(f"  T2 Hit Rate:     {cm['t2_hit_rate']:.1f}%")
        print(f"  Total PnL:       ${cm['total_pnl']:.2f}")
        print(f"  Max DD:          {cm['max_dd']:.2f}%")
        print(f"\n  ── Combined Gate Scorecard ──")
        passed = 0
        for label, val, ok in eval_gates(cm):
            if ok: passed += 1
            print(f"    {'✅' if ok else '❌'}  {label:<30}  {val:.3f}")
        print(f"\n  Gates passed: {passed}/7")
        all_results['COMBINED'] = cm

    # Save
    out_dir = Path('/home/user/workspace/jarvis-repo-fresh/engine/validation_reports')
    out_dir.mkdir(exist_ok=True)
    with open(out_dir / 'BT_S2_results.json', 'w') as f:
        json.dump(all_results, f, indent=2, default=str)

    # Save trade logs
    for sym, trades in all_trades.items():
        pd.DataFrame(trades).to_csv(out_dir / f'BT_S2_{sym}_trades.csv', index=False)

    print(f"\n  Saved → engine/validation_reports/BT_S2_*")
