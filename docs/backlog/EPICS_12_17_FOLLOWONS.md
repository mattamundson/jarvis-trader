# Follow-on epics (12–17) — tracking

Consolidated backlog from the comprehensive plan. Execute after paper-phase signals stabilize.

| Epic | Theme | Next actions |
|------|--------|----------------|
| 12 | Options activation | Confirm flags in `config.py`; paper dry-run SPY/QQQ paths; safety review on options risk module. |
| 13 | LLM cost metrics | Token counts per pipeline stage → SQLite or Prometheus; optional `ANTHROPIC_MONTHLY_BUDGET_USD` soft warning. |
| 14 | Learning promotion | Criteria in `learning/_experimental/README.md`; feature-flag modules in `learning_router` + dashboard flags panel. |
| 15 | KAIROS | `kairos_router` + widgets; optional regime input behind `enable_kairos` flag; WFE regression before default-on. |
| 16 | Data feeds | `POLYGON_API_KEY` / `FINNHUB_API_KEY` in `.env.example` (present); startup WARN already in `startup_checks._check_polygon_key`. |
| 17 | Root cleanup | Move stray root `*.md` session files to `docs/session-logs/` or `docs/archive/` in a **docs-only** commit. |
