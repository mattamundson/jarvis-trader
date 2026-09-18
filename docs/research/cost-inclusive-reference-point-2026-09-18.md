# Cost-inclusive reference point — MES, post-ledger-fix (2026-09-18)

Round 3, task 1. Reproduces with:

    env -u PYTHONPATH .venv/Scripts/python.exe backtest/analyze_mes_vix_pctile_economics.py \
        --out ../docs/research/mes-vix-pctile-champion-economics.json

Status: research evidence. No live routing, config, risk, kill-switch or order-path change.

## Why this exists

Until 2026-09-18 no candidate had a correct net-of-cost economics figure. The trade ledger carried no
cost at all (PF/win-rate/Sharpe optimistic) while the equity curve over-charged commission by 1.7465×
(CAGR/drawdown pessimistic) — the two bases disagreed by $1,748.12 and neither was right. PR #879
fixed the ledger; this is the first economics produced on the repaired instrument, and it is the
denominator every future candidate comparison should use.

## The reference point

Fixed-params run over the whole deep sample (43,010 bars, 7.307y), `risk_per_trade=1%`,
`$50,000` initial, deep cache `sha256 e26631c0…`.

| metric | pre-fix (broken ledger) | **post-fix (reference point)** |
|---|---|---|
| champion `block=[]` PF | 1.6952 | **1.6478** |
| win rate | 52.46 % | **52.46 %** |
| trades / trades per year | 122 / 16.696 | **122 / 16.696** |
| CAGR | 2.5361 % | **2.8555 %** |
| max drawdown | 4.4833 % | **4.224 %** |
| engine Sharpe | 0.874 | **0.8283** |
| honest Sharpe (observed tpy) | 0.225 | **0.2132** |
| `total_pnl` | $11,789.49 | **$11,421.57** |
| `final_capital − initial` | $10,041.37 | **$11,421.57** |
| **ledger − equity gap** | **$1,748.12** | **$0.00** |

**The gap closing to exactly zero on a real full-sample run — not just the unit fixture — is the
headline.** The two bases now report the same number, so "which basis did you quote?" is no longer a
live question.

### Reading it

- **CAGR rose while `total_pnl` fell, and both are now the same figure.** CAGR improved because the
  equity curve stopped paying commission 1.7465× over; `total_pnl` fell because the trade ledger now
  pays it once. The pre-fix pair ($10,041 equity vs $11,789 ledger) bracketed the truth; the truth is
  $11,421.57.
- **PF 1.6952 → 1.6478 is a real degradation of measured edge**, not a bug: the earlier figure was
  cost-free. Any comparison against pre-2026-09-18 PFs must account for ~2.8 % of pure optimism.
- **`Crisis` block still worse**: PF 1.4936, CAGR 2.0617 %, DD 4.33 %, honest Sharpe 0.158. The
  pre-registered adaptation remains falsified on this sample.
- **Honest Sharpe 0.2132** at 16.7 trades/yr — for scale, the previously certified live champion
  SMA(50,200)+2×ATR was −0.26 % CAGR, so this is better, but 0.21 is not an institutional edge.

## Deflation, on the same run

`dsr_grid` (4 trials) 0.9705 · `dsr_campaign` (214 trials) ≈ **0.21** — i.e. **below the 0.30 ALT
floor**, and *lower* than the pre-fix 0.2642 because honest costs lower the return series too. The
verdict still reads "PASS via alt" because the ALT conjunction does not reference `dsr` at the
campaign count; that is the open policy question, not a measurement question.

## Prior and current state of the candidate

| basis | value |
|---|---|
| pre-fix verdict | PASS via alt, PF 1.6952, `dsr_campaign` 0.2642 |
| post-fix verdict | PASS via alt, PF 1.6478, `dsr_campaign` 0.1815 |
| PASS classification flipped? | **no** — `p_edge` unchanged at 0.5926, no window's profitability changed |

`p_edge` did not move because it counts windows with PF > 1, and cost entry did not flip any window
from profitable to unprofitable. So for this candidate the ledger fix moves **magnitudes, not
classifications** — which is why no promotion decision unblocks on it alone, but every *economic*
number previously quoted does.

## Limits

1. One candidate family. The mechanism generalises (shared `Backtester`), but reference points for
   other symbols are not tabulated here.
2. `risk_per_trade=1%` and `$50,000` are the analysis conventions, not live sizing.
3. The `dsr_campaign` count (214) is a lower bound derived from the artifact store, deduped by
   content hash — unlogged experiments can only raise it, making deflation stricter.
4. The commission convention is reading A (1.42 = round trip). If a broker statement contradicts it,
   every figure here shifts by the amount quantified in `docs/research/cost-ledger-fix-spec-2026-09-18.md`.
