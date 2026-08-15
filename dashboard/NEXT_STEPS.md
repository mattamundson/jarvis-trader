# Jarvis Dashboard Split - Complete

## What's Done
The monolithic dashboard has been split into 3 focused apps under `apps/`:

### 1. trading-desk (port 3010)
- command-center
- trades/*
- portfolio
- paper
- parallel-paper
- atr-trail

### 2. research-lab (port 3020)
- analysis
- backtest
- screener
- watchlist
- scorecard
- performance
- regime
- hidden-pivots
- journal-review

### 3. ops-console (port 3030)
- settings
- config
- health
- validation
- master/*
- trust-pane
- discord
- jarvis

## How to Run

```bash
# Terminal 1 - Trading Desk
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\dashboard\apps\trading-desk
pnpm dev

# Terminal 2 - Research Lab
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\dashboard\apps\research-lab
pnpm dev

# Terminal 3 - Ops Console
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\dashboard\apps\ops-console
pnpm dev
```

Each app is a standalone Next.js 15 app. Shared components, hooks, and lib are in each app's local `app/components`, `app/hooks`, `app/lib`.

## Next Steps
1. Test each app individually: `pnpm dev`
2. Fix any import paths in pages that reference `~/components`, `~/lib`, `~/hooks`
3. Merge overlapping pages (today + mission-control + command-center → command-center)
4. Cut unused pages (kairos, strategy-research, framing-brief, etc.)
5. Set up reverse proxy in engine to route /research/* and /ops/* to the appropriate app
