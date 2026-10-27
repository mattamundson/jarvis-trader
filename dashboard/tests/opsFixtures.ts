// Synthetic Hermes files in the real formats. Account ids here are invented.
export const TRACKER = `# Rebuild ladder tracker
## Current state
| Field | Value |
|-------|-------|
| Step | **1 → 2**: paper step done (10/10 clean). Account U1234567 |
| Clean paper sessions | **10 / 10** for Step 2 |
| Running count toward 20 clean (needed before 1R options) | **12 / 20** (10/21 counted) |
| Scored paper setups | **6/20 scored setups, avg R = +0.20** (approx., delayed data) |
| Live (any product, incl. shares ≤0.5R) | **ILLEGAL** until the checklist |
| Strikes (30d) | **17 confirmed** (10/5–10/9) → **5-day strike lockout ACTIVE Wed 10/21–Tue 10/27** |
| Lockout | **ON**: 5-day strike lockout **10/21–10/27** + weekly 3R from 10/6 (never released). |
| Session log through | **2026-10-23** |

## Session log (compliant paper = +1)
| Date | Bias | Journaled? | Regime flip yelled? | Rule breaks | Notes |
|------|------|------------|---------------------|-------------|-------|
| 2026-10-20 | watch | yes | yes | LIVE 0DTE in lockout | **Not clean.** Strike confirmed. |
| 2026-10-21 | watch | yes | yes | none | **Clean, counted** (Matt) |
| 2026-10-22 | watch | yes | yes | LIVE options | something else |

## Unlock checklist
- [x] Exact E pasted (acct 12345678)
- [ ] Go-live proof bar: 6/20 scored

## E1 paper calls
| Date | Call |
|---|---|
`;

export const STRIKES = `# Strike log
## Confirmed strikes
| # | Date | Logged | Bans broken (from journal LIVE review rows) | Confirmed by |
|---|------|--------|---------------------------------------------|--------------|
| 1 | 2026-10-19 | 2026-10-20 | Live 0DTE options while blocked; averaged down | Matt's yes |
| 2 | 2026-10-20 | 2026-10-20 | Over the 1R cap | Matt's yes |

## Count (30 days, updated 2026-10-26)
- **Confirmed: 17** (one per day would give 14).
- **5-day strike lockout: ACTIVE Wed 2026-10-21 through Tue 2026-10-27** (paper + rules review only).

## Pending strikes (need Matt's yes to confirm)
| Date | Logged | Bans broken (from journal LIVE review rows) | Status |
|------|--------|---------------------------------------------|--------|
| 2026-10-26 | 2026-10-26 (Hermes 3:40) | Live 1DTE puts; Robinhood acct ••1804 | pending |
`;

export const CHECKLIST = `# Lockout release checklist
## Active as of 2026-10-20
- Trading lockout: weekly 3R lockout from 10/6, never released.

## Conditions (all required)
- [ ] **Days served:** through Tue 2026-10-27.
- [x] **Flat:** account DU7654321 shows no positions.

## Release record
| Date | Lockout | Matt's yes (quote) | Recorded by |
|------|---------|--------------------|-------------|
`;

export const JOURNAL = `# Paper journal
## Column definitions
- stuff | not a table

| Date | Session | Bias | Squeeze | GEX flip/walls | Level | Invalidation | Paper if/then | Live legal? | Starter R | Result | Regime flip? | Call grade | Notes | R result | EM band |
|------|---------|------|---------|----------------|-------|--------------|---------------|-------------|-----------|--------|--------------|------------|-------|----------|---------|
| 2026-09-22 | RTH 8am CT | watch (paper-only) | OFF | flip 7672 | lvl | inv | if/then | NO | 0 | open | n/a | n/a | early row | +1.2R target | — |

## Flow column
| Date | Session | Bias | Squeeze | GEX flip/walls | Level | Invalidation | Paper if/then | Live legal? | Starter R | Result | Regime flip? | Call grade | Notes | R result | Flow | EM band |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-26 | **LIVE review** (Hermes 3:40) | watch | — | — | SPY 759P | — | — | NO | 26.0R | closed | — | — | Robinhood main individual acct ••1804, user-placed. IB DU1234567 | −2.91R realized | n/a | n/a |
`;
