# JARVIS Morning Alpha — Historical Data Acquisition Plan v1

## Objective

Build a point-in-time, survivorship-aware U.S. equity research corpus that satisfies the Morning Alpha `research_manifest.json` v1.1 evidence contract and is suitable for the frozen six-family research campaign.

This plan separates **live/paper operation** from **historical certification**. A vendor that is excellent for current trading is not automatically authoritative for point-in-time backtesting.

## Recommended source roles

| Artifact | Preferred source | Why | Secondary / cross-check |
| --- | --- | --- | --- |
| `daily_bars` | Massive U.S. Stocks | Deep U.S. exchange history, broad listed-stock coverage, REST/flat-file access | Databento historical bars |
| `intraday_bars` | Massive U.S. Stocks | Intraday aggregates/trades with premarket/RTH/after-hours coverage | Databento historical market data |
| `premarket_bars` | Massive U.S. Stocks | Session-aware historical aggregates/trades | Databento historical market data |
| `universe_membership` | Databento Reference Security Master | PIT `ts_record`/`ts_effective`, listed + delisted securities, stable identifiers | Massive ticker reference as a cross-check |
| `delisted_symbols` | Databento Reference Security Master | PIT listing status, listing/delisting dates | Massive `active=false` reference cross-check |
| `corporate_actions` | Databento Reference Corporate Actions | PIT event history with record timestamps and historical revisions | Sharadar actions / Massive splits-dividends cross-check |
| `sector_history` | Databento Reference Security Master | PIT GICS/SIC/NAICS fields tied to effective timestamps | Separate dated classification source if GICS coverage is incomplete |
| `earnings_events` | Zacks Data historical EPS/Sales Surprises | Report date, entry date, actual, consensus on report date, surprise %, revisions | Finnhub earnings calendar for date cross-check |
| `macro_context` | FRED + Cboe + Federal Reserve/BLS calendars | DGS10, WTI, VIX plus official scheduled event timestamps | Direct source mirrors / archived calendars |

## Verified documentation references

- Databento Security Master: https://databento.com/docs/schemas-and-data-formats/security-master
- Databento Corporate Actions: https://databento.com/docs/venues-and-datasets/corporate-actions
- Massive Stocks Overview: https://massive.com/docs/rest/stocks/overview
- Massive Stocks Flat Files: https://massive.com/docs/flat-files/stocks/overview
- Zacks historical database: https://www.zackspro.com/historical.asp
- Finnhub earnings/calendar capabilities: https://finnhub.io/
- FRED: https://fred.stlouisfed.org/
- Cboe VIX historical data: https://www.cboe.com/tradable-products/vix/vix-historical-data
- Federal Reserve FOMC calendars: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- BLS release calendar: https://www.bls.gov/schedule/

## Required normalized schemas

### Daily bars

```text
symbol
timestamp
open
high
low
close
volume
source
ingested_at
```

Store raw/unadjusted market history. Apply corporate-action adjustments through a separately versioned transformation so raw source bytes and adjustment policy remain reproducible.

### Intraday / premarket bars

```text
symbol
timestamp
open
high
low
close
volume
session        # premarket | rth | after_hours
source
ingested_at
```

Five-minute-or-better history is required for ORB 5m/15m/30m, VWAP and breakout/retest sequencing.

### Point-in-time universe

```text
stable_id
symbol
ts_record
ts_effective
listing_status
listing_date
delisting_date
primary_exchange
security_type
```

Never derive a historical universe from today's symbols.

### Delisted symbols

```text
stable_id
symbol
ts_record
ts_effective
delisting_date
listing_status
```

### Corporate actions

```text
stable_id
event_unique_id
event_type
ts_record
effective_date
```

Preserve PIT revisions. Adjustment factors should be retained when the source provides them.

### Sector history

```text
stable_id
ts_record
ts_effective
gics
sic
naics
```

Use the classification effective at the historical decision timestamp. Do not use today's sector classification for earlier sessions.

**Open research policy:** sector benchmark availability must be explicit. The modern 11 Select Sector SPDR ETFs do not all share identical inception histories. Before campaign execution, define a versioned sector-proxy policy for dates where a canonical ETF is unavailable; never synthesize missing ETF history silently.

### Earnings events

```text
symbol
report_date
entry_date
fiscal_period
actual_eps
consensus_on_report_date
eps_surprise_pct
actual_revenue
revenue_consensus
```

The critical field is the consensus **known on the report date**. A current consensus or revised historical estimate creates lookahead bias and is not acceptable for PEAD certification.

### Macro context

```text
timestamp
vix
dgs10
wti
scheduled_event_type
scheduled_event_timestamp
```

Market series do not replace release calendars. Scheduled event risk should be reconstructed from official FOMC/BLS publication calendars.

## Acquisition and certification workflow

For every acquired artifact:

```text
Acquire raw artifact
    ↓
Preserve immutable source file
    ↓
Normalize to research schema (separate output)
    ↓
Generate artifact receipt
    ↓
Store provider + relative path + SHA-256 + counts + coverage
    ↓
Build manifest from receipts
    ↓
Run research-data-check
```

CLI example:

```bash
python -m morning_alpha.cli research-source-plan --json

python -m morning_alpha.cli research-receipt-create \
  --data-root ./data/morning_alpha \
  --kind universe_membership \
  --path evidence/universe.csv \
  --provider "Databento Reference" \
  --row-count 1000000 \
  --symbol-count 20000 \
  --earliest 2005-01-01T00:00:00Z \
  --latest 2026-09-15T00:00:00Z \
  --point-in-time \
  --json

python -m morning_alpha.cli research-manifest-build \
  --data-root ./data/morning_alpha --json

python -m morning_alpha.cli research-data-check \
  --data-root ./data/morning_alpha --json
```

## Research-ready minimums

```text
daily symbols       >= 500
intraday symbols    >= 100
daily history       >= 8 years
```

Required evidence:

```text
point-in-time universe
listed + delisted coverage
corporate actions
historical sector/classification data
earnings events with report-date consensus
macro/regime series
scheduled event calendars
source lineage
premarket history
SHA-256 artifact integrity
```

## Recommended acquisition order

1. Databento PIT security master.
2. Databento PIT corporate actions/adjustment evidence.
3. Massive daily U.S. stock history.
4. Massive 5-minute-or-better intraday history for the research universe.
5. Zacks historical EPS/sales surprise data.
6. FRED DGS10 + daily WTI.
7. Cboe VIX history.
8. Federal Reserve FOMC calendars and BLS CPI/jobs release calendars.
9. Build receipts and manifest.
10. Run readiness certification.
11. Only after `READY`, execute the frozen campaign.

## Cost-control recommendation

Do not download tick-level history for the entire U.S. market initially. Start with daily history for the full survivorship-safe universe, use it to generate historical candidates, then obtain/replay high-resolution intraday data only for candidate/session windows when provider licensing and API design permit. This preserves trigger fidelity while substantially reducing storage/API costs.

This optimization must not change the candidate-generation information set: intraday data may resolve execution after a candidate is created, but it may not retroactively influence the prior daily candidate decision.
