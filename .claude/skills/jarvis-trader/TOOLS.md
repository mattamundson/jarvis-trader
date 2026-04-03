# JARVIS TRADER — External Tool Routing Map

JARVIS TRADER is the central orchestrator. Every task — whether codebase work, market
research, data analysis, or process control — has a designated tool or skill. This file
is the single routing authority. When in doubt, check here first.

---

## How to Use This Map

1. Identify the task category (Research, Data/Reporting, Engineering, File/Process)
2. Find the matching tool or skill in the table for that category
3. Use that tool — do not improvise with a different one
4. If multiple tools apply, the PRIMARY column tells you which to reach for first

---

## Category 1 — Research & Intelligence

Use these tools when JARVIS needs external information to feed the pipeline: news,
macro data, earnings, regulatory filings, competitor moves, social sentiment.

### Live Web Research

| Task | PRIMARY Tool | HOW |
|---|---|---|
| Fetch a specific URL (news article, SEC filing, earnings release) | `mcp__Claude_in_Chrome__navigate` + `mcp__Claude_in_Chrome__get_page_text` | Navigate to URL, extract text |
| Scrape real-time market news for a symbol | `mcp__Claude_in_Chrome__navigate` | Load news aggregator, extract headlines |
| Research macro data (CPI, NFP, Fed minutes) | `mcp__Claude_in_Chrome__navigate` | Navigate to FRED, BLS, or Fed website |
| Read earnings call transcript or filing | `mcp__Claude_in_Chrome__navigate` + `mcp__Claude_in_Chrome__get_page_text` | Navigate to SEC EDGAR or earnings site |
| Screenshot a chart or dashboard for visual analysis | `mcp__Claude_in_Chrome__upload_image` or `mcp__Kapture_Browser_Automation__screenshot` | Capture and read |
| Automated form interaction (login, search, filter) | `mcp__Kapture_Browser_Automation__fill` + `mcp__Kapture_Browser_Automation__click` | Fill form fields, submit |
| Read console/network for API data inspection | `mcp__Claude_in_Chrome__read_console_messages` + `mcp__Claude_in_Chrome__read_network_requests` | Intercept live data feeds |
| Open multiple research tabs in parallel | `mcp__Kapture_Browser_Automation__new_tab` + `mcp__Kapture_Browser_Automation__navigate` | Parallel tab research |

### Search Across Stored Intelligence

| Task | PRIMARY Tool | HOW |
|---|---|---|
| Search trade notes, strategy docs in Google Drive | `mcp__c1fc4002-5f49-5f9d-a4e5-93c4ef5d6a75__google_drive_search` | Query: "MCL strategy Q1 2026" |
| Fetch a specific stored document | `mcp__c1fc4002-5f49-5f9d-a4e5-93c4ef5d6a75__google_drive_fetch` | Retrieve by file ID or name |
| Cross-platform search (Drive + other connected sources) | `enterprise-search:search` skill | Use the enterprise search skill |
| Daily digest of research across all connected sources | `enterprise-search:digest` skill | Morning intelligence briefing |

### Pipeline Feed — How External Research Connects to JARVIS

When research is gathered for the LLM pipeline:
- News and earnings data → feeds `NewsAnalystAgent` (`engine/agents/news_analyst.py`)
- Macro data (VIX, DXY, yield curve) → feeds `FundamentalistAgent` + `/macro/snapshot` endpoint
- Social sentiment → feeds `SocialAnalystAgent` (`engine/agents/social_analyst.py`)
- Research docs → store in Google Drive → retrieve via `google_drive_fetch` → pass to pipeline

---

## Category 2 — Data & Reporting

Use these when you need to analyze trade data, build performance reports, run SQL
against the engine database, or generate visualizations.

### Analysis

| Task | PRIMARY Skill | Notes |
|---|---|---|
| Analyze trade history data (CSV, SQLite export) | `data:analyze` | Uploads data, returns insights |
| Explore a new dataset (shape, quality, nulls) | `data:data-exploration` | Run before any analysis |
| Statistical analysis (win rate, Sharpe, drawdown) | `data:statistical-analysis` | Distributions, correlations, significance |
| SQL query against engine SQLite DB | `data:sql-queries` | Targets `engine/*.db` or exported data |
| Validate analysis before sharing | `data:data-validation` | Checks for survivorship bias, logic errors |

### Visualization

| Task | PRIMARY Skill | Notes |
|---|---|---|
| Equity curve chart, P&L plot | `data:data-visualization` | Python + matplotlib/plotly |
| Interactive HTML dashboard (filters, charts) | `data:interactive-dashboard-builder` | Self-contained HTML file, no server needed |

### Financial Reporting

| Task | PRIMARY Skill | Notes |
|---|---|---|
| Trading P&L statement (income statement format) | `finance:financial-statements` | Period-over-period, GAAP-style presentation |
| Variance analysis (budget vs actual, period-over-period) | `finance:variance-analysis` | Waterfall decomposition with narrative |
| Reconcile broker statement vs internal tracker | `finance:reconciliation` | GL-to-subledger style comparison |
| Monthly close review for paper trading period | `finance:close-management` | Close calendar, blocker tracking |

### Reporting Workflow for JARVIS

Standard performance report cadence:
1. Export trade data: `GET /trades` + `GET /performance/7d` + `GET /analytics/performance/rolling`
2. Analyze: `data:analyze` skill
3. Visualize: `data:data-visualization` or `data:interactive-dashboard-builder`
4. Financial summary: `finance:financial-statements`
5. Store: `mcp__c1fc4002-5f49-5f9d-a4e5-93c4ef5d6a75__google_drive_fetch` → save to Drive

---

## Category 3 — Engineering Workflows

Use these for all codebase work. JARVIS routes engineering tasks to the right skill
rather than attempting everything inline.

### Codebase Work

| Task | PRIMARY Tool/Skill | Notes |
|---|---|---|
| Debug a pipeline failure or agent error | `engineering:debug` skill | Structured: reproduce → isolate → fix → verify |
| Code review before merging safety-critical changes | `engineering:code-review` skill | Required for `safety_layer.py` changes |
| Design a new module or architecture decision | `engineering:system-design` skill | Use before implementing anything large |
| Create or evaluate an ADR | `engineering:architecture` skill | `gstack /review` also available |
| Improve test coverage | `engineering:testing-strategy` skill | Use alongside local `playbooks/test.md` |
| Identify and prioritize technical debt | `engineering:tech-debt` skill | Quarter-level cleanup planning |
| Triage a production incident | `engineering:incident-response` skill | `gstack /investigate` for pipeline failures |
| Generate standup from recent git activity | `engineering:standup` skill | Daily dev update |
| Write technical documentation | `engineering:documentation` skill | API docs, runbooks, onboarding |

### gstack Skills (Already Vendored at `.claude/skills/gstack/`)

| gstack Skill | When to Use |
|---|---|
| `/review` | **REQUIRED** before any PR touching `engine/risk/safety_layer.py` |
| `/investigate` | Debug agent pipeline failures — traces full execution path |
| `/qa` | Test dashboard at `http://localhost:3010` with real browser |
| `/ship` | Full release workflow: tests → review → push → PR |
| `/cso` | OWASP + STRIDE security audit of FastAPI engine |
| `/benchmark` | Pipeline latency regression detection |
| `/office-hours` | Product reframe before designing new trading features |

### Tool Routing by Code Area

| Code Area | Primary Engineering Tool |
|---|---|
| `engine/risk/safety_layer.py` | `engineering:code-review` + gstack `/review` (both required) |
| `engine/agents/pipeline.py` | `engineering:debug` → `engineering:system-design` |
| `engine/backtest/signals.py` | `engineering:code-review` + walk-forward validation |
| `engine/routers/` | `engineering:documentation` for new endpoints |
| `dashboard/` | gstack `/qa` for visual verification |
| New feature design | `engineering:system-design` → `engineering:feature-spec` (via `product-management:feature-spec`) |
| Test gaps | `engineering:testing-strategy` |
| Security audit | gstack `/cso` |
| Performance regression | gstack `/benchmark` |

---

## Category 4 — File & Process Control

Use these for operating the JARVIS TRADER system: starting/stopping processes,
reading logs, managing files, storing outputs.

### Process Management

| Task | PRIMARY Tool | Command |
|---|---|---|
| Start the engine (if not running) | `mcp__Desktop_Commander__start_process` | `cd engine && .venv/Scripts/python -m uvicorn main:app --port 8010` |
| Start the dashboard | `mcp__Desktop_Commander__start_process` | `cd dashboard && pnpm dev` |
| Check if engine is running on port 8010 | `mcp__Desktop_Commander__list_processes` | Filter for uvicorn / port 8010 |
| Kill a hung process | `mcp__Desktop_Commander__kill_process` | By PID |
| Read live engine output | `mcp__Desktop_Commander__read_process_output` | Stream stdout/stderr |
| Run tests and capture output | `mcp__Desktop_Commander__start_process` | `cd engine && .venv/Scripts/python -m pytest tests/ -v` |
| Restart engine after config change | `mcp__Desktop_Commander__start_process` | Run `.\restart_engine.ps1` |

### File Management

| Task | PRIMARY Tool | Notes |
|---|---|---|
| Read engine logs | `mcp__Desktop_Commander__read_file` | `engine/logs/*.log` or `engine_error.log` |
| Read multiple log files at once | `mcp__Desktop_Commander__read_multiple_files` | Pass array of log paths |
| List contents of a directory | `mcp__Desktop_Commander__list_directory` | Prefer `Glob` tool for pattern matching |
| Move a misplaced root file to correct location | `mcp__Desktop_Commander__move_file` | See CLAUDE.md "Root Directory Misplaced Files" |
| Search within files | `mcp__Desktop_Commander__start_search` | Use for large log files |
| Write a new config or data file | `mcp__Desktop_Commander__write_file` | For files outside the skill pack |
| Edit a block within a large file | `mcp__Desktop_Commander__edit_block` | When `Edit` tool would be unwieldy |

### Google Drive — Storage and Retrieval

| Task | PRIMARY Tool | Notes |
|---|---|---|
| Save a performance report to Drive | `mcp__c1fc4002-5f49-5f9d-a4e5-93c4ef5d6a75__google_drive_fetch` | After generating, upload the file |
| Retrieve a stored strategy doc | `mcp__c1fc4002-5f49-5f9d-a4e5-93c4ef5d6a75__google_drive_fetch` | By file ID |
| Search for a stored document by topic | `mcp__c1fc4002-5f49-5f9d-a4e5-93c4ef5d6a75__google_drive_search` | Full-text search |

### Standard File Locations

| Content Type | Location |
|---|---|
| Engine logs | `engine/logs/` or `engine_error.log`, `engine_output.log` at root |
| Trade journal (SQLite) | `engine/*.db` |
| Strategy documents | Google Drive (search: "JARVIS strategy") |
| Performance reports | Google Drive (search: "JARVIS performance") |
| Backtest results | `engine/backtest/` output files |
| Session logs | `docs/session-logs/` |
| Ops scripts | `scripts/` (canonical) or root `.ps1` files (convenience copies) |

---

## Master Routing Decision Tree

```
Incoming task
│
├── Needs external information? (news, macro, earnings, web data)
│   └── → Category 1: Research & Intelligence
│       ├── Live web data → Claude in Chrome / Kapture
│       └── Stored docs   → Google Drive search / enterprise-search
│
├── Needs data analysis or reporting?
│   └── → Category 2: Data & Reporting
│       ├── Trade analysis      → data:analyze / data:statistical-analysis
│       ├── Visualization       → data:data-visualization / data:interactive-dashboard-builder
│       └── Financial report    → finance:financial-statements / finance:variance-analysis
│
├── Needs codebase work?
│   └── → Category 3: Engineering
│       ├── Bug / failure       → engineering:debug + playbooks/debug.md
│       ├── New feature         → engineering:system-design + playbooks/add-feature.md
│       ├── Safety-critical PR  → engineering:code-review + gstack /review (BOTH)
│       ├── QA dashboard        → gstack /qa
│       └── Ship a release      → gstack /ship + playbooks/release.md
│
└── Needs system operation or file management?
    └── → Category 4: File & Process Control
        ├── Start/stop services → Desktop Commander start_process / kill_process
        ├── Read logs           → Desktop Commander read_file
        └── Store/retrieve docs → Google Drive fetch / search
```

---

## Tool Availability Notes

- **Claude in Chrome** and **Kapture Browser Automation**: both available; prefer Chrome for
  reading-heavy research, Kapture for interaction-heavy automation
- **Desktop Commander**: full filesystem + process access to your Windows machine — use
  for starting the engine, reading logs, managing files outside the workspace folder
- **Google Drive**: search and fetch; use for retrieving stored strategy and performance docs
- **gstack skills**: already vendored at `.claude/skills/gstack/` — invoke with `/skill-name`
- **enterprise-search skills**: unified search across all connected platforms
- **data:* and finance:* skills**: Cowork skills that run inline — invoke via the Skill tool

---

## What JARVIS Does NOT Use External Tools For

- Modifying `safety_layer.py` risk parameters (Tier 3 only, no tool substitutes for that)
- Making live trading decisions (always stays in the LLM pipeline)
- Overriding kill switch logic (hardcoded Python, not accessible via any tool)
- Accessing IB Gateway port 4001 (permanently blocked, no workaround)
