# JARVIS Research Note — tradingview-mcp (mattamundson/tradingview-mcp)

**Source:** `mattamundson/tradingview-mcp`, default branch `main`, 85 files, fork (archived: no, private: no), pushed 2026-09-10.
**What it is:** AI-assisted TradingView chart analysis — connects Claude Code to TradingView Desktop for personal workflow automation.

## Reusable patterns for JARVIS

### 1. MCP/agent bridge as a discretionary-review tool (the core transferable pattern)
- The repo's value is as a **discretionary chart review bridge**: an agent/Claude layer talks to TradingView Desktop to capture charts, run Pine prototypes, and produce screenshot-based journal entries.
- JARVIS' audit already flags this: *"Use TradingView MCP for chart capture/Pine prototyping and screenshot-based journal entries."* This repo is the concrete proof point. The JARVIS add is to make the **chart-review runbook** explicit in `docs/research/chart-review-runbook.md` — when to pull a chart, what to capture, how to fold it into the strategy journal, and the safety boundary (chart review informs discretion; it does not place orders).

### 2. RESEARCH.md + SETUP_GUIDE.md as doc packaging
- The repo separates research (`RESEARCH.md`) from setup (`SETUP_GUIDE.md`) from security (`SECURITY.md`). JARVIS research docs can adopt the same three-bucketing: what we tried/learned, how to reproduce, safety/security notes. This is a doc hygiene pattern.

### 3. Windows launch tooling (`.bat` + `.vbs`)
- Ships Windows launch helpers. JARVIS runs on Windows; the transferable note is that any agent-driven chart-capture workflow on Windows needs a non-interactive launch path (the `.vbs` wrapper pattern from the audit's Windows-shell-ops rules). This is operational, not a code import.

### What NOT to import
- Do not vendor the MCP server code into JARVIS' engine/dashboard. It's a separate tool the user runs alongside JARVIS; JARVIS just needs the runbook.
- No execution wiring; no risk limit changes.

## Recommended JARVIS doc add (small, doc-only)
- `docs/research/chart-review-runbook.md` — when to pull a chart, what to capture, how to fold into the strategy journal, safety boundary (discretion-informing only), and the Windows non-interactive launch note.

**Safety class:** S0 — doc-only research note. No code, no config, no execution wiring.
