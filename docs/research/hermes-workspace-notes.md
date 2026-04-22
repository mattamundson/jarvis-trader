# Hermes Workspace Reference Notes

**Fetch Date:** 2026-04-10  
**Source:** https://github.com/outsourc-e/hermes-workspace  
**Commit SHA:** `2e69f58` (feat: v1.0.0 — profiles, knowledge browser, MCP settings, skills hub, eslint)  
**Fetch Method:** `git clone --depth 1` (succeeded)  
**License:** MIT

---

## 1. Repository Overview

**Hermes Workspace** is a **frontend desktop application** — not the supervisor agent pattern itself, but the orchestration layer that a supervisor agent would control. It provides a unified interface for multi-agent collaboration:

- **Tech stack:** React 19 + TanStack Start/Router + Vite 7 + Tailwind CSS 4 + xterm.js + Monaco Editor
- **Files:** ~50 TypeScript components, ~3,100 LOC in `src/`
- **Purpose:** Command center for Hermes Agent — real-time chat, memory browser, skills registry, terminal, file explorer
- **Backend:** Connects to any **OpenAI-compatible backend** (vanilla hermes-agent, Ollama, vLLM, etc.)

**Key insight for JARVIS:** Hermes Workspace is **platform-agnostic** — it sends chat to `/v1/chat/completions` (portable) or Hermes-specific `/api/sessions` (enhanced). This mirrors JARVIS's two-mode design: the supervisor uses lightweight markers + JSON, not prose, allowing different transports (WhatsApp, Discord, future OpenClaw broadcast).

---

## 2. File Tree (Top 2 Levels)

```
hermes-workspace/
├── .devcontainer/          # Docker dev setup
├── .github/                # CI/CD workflows
├── .vscode/                # VS Code settings
├── docker/                 # Docker Compose (agent + workspace containers)
├── docs/                   # Architecture specs (hermes-openai-compat-spec.md)
├── public/                 # Static assets, manifest.json
├── scripts/                # Build/deploy scripts
├── src/
│   ├── components/         # React UI components (avatars, file-explorer, inspector, memory-viewer, onboarding, settings, usage-meter)
│   ├── hooks/              # Custom React hooks (use-chat-mode, use-chat-settings, use-chat-stream)
│   ├── lib/                # Utilities (workspace checkpoints, strip queued messages, etc.)
│   ├── routes/             # TanStack Router page definitions
│   ├── screens/            # Full-page views (chat, dashboard, files, terminal, memory, skills)
│   ├── server/             # Node.js backend (SSE streaming, PTY terminal, file I/O)
│   ├── stores/             # Zustand state management
│   ├── types/              # TypeScript type definitions
│   └── utils/              # Helper functions
├── .env.example            # Environment template
├── .eslintignore, .prettierignore
├── docker-compose.yml      # Workspace + hermes-agent orchestration
├── Dockerfile              # Workspace container
├── ESLint + Prettier config
├── package.json            # pnpm dependencies (React 19, Monaco, xterm, Zustand, etc.)
├── tsconfig.json
├── vite.config.ts
├── LICENSE                 # MIT
├── README.md               # Quick start guide
├── CONTRIBUTING.md
├── FEATURES-INVENTORY.md   # ~31KB comprehensive features list
├── FUTURE-FEATURES.md      # Roadmap (knowledge graph, automated agents, etc.)
└── SECURITY.md             # Auth middleware, CSP headers, exec approval, etc.
```

---

## 3. Architecture: OpenAI-Compat + Hermes Enhancement

The workspace operates in **two modes**, with graceful degradation:

### Mode A — Portable (OpenAI-compatible)
- Minimum backend: `POST /v1/chat/completions` + optional `GET /v1/models`
- Works with: hermes-agent, Ollama, LM Studio, vLLM, OpenAI
- Features: basic chat, streaming, model selection, file attachments
- **No session history, no memory browser, no skills registry**

### Mode B — Enhanced (Hermes full)
- Additional endpoints: `/api/sessions`, `/api/skills`, `/api/memory`, `/api/config`, `/api/jobs`
- Unlocks: named sessions, memory browser/search/edit, 2,000+ skills, config editor
- **Capability detection:** UI probes endpoints at startup and progressively enhances

**JARVIS Parallel:** JARVIS's supervisor operates in fail-open mode (like Mode A). Kill switch + IB disconnect always escalate. Normal signals only escalate on low confidence or regime mismatch. Failure to reach LLM → defaults to ESCALATE (never swallows user-critical events).

---

## 4. Core Product Principle: Chat is the Base

From `docs/hermes-openai-compat-spec.md`:

> **Chat is the base product. Everything else is optional enhancement.**
> 
> If a user points Hermes Workspace at a valid OpenAI-compatible backend, they should be able to send a message and receive a streamed response without caring whether the backend is Hermes, OpenAI, OpenRouter, Ollama, vLLM, or something else.

**Message rendering:**
- Markdown + GFM (remark-gfm, remark-breaks)
- Syntax highlighting (Shiki)
- Tool call pill rendering with expandable details
- Streaming text with progressive reveal
- Context meter showing token usage percentage
- Real-time SSE streaming with tool call rendering

**JARVIS Parallel:** JARVIS's supervisor reduces to one job: **classify, don't generate**. Just like Hermes chat strips complexity to `/v1/chat/completions`, the supervisor strips decision-making to: `{"marker": "ACK|REVIEW|ESCALATE|HOLD_FOR_INFO", "reason": "<=25 words"}`.

---

## 5. Hermes Agent Gateway Integration

The workspace connects to **Hermes Agent gateway** (sibling repo: `github.com/outsourc-e/hermes-agent`):

```env
# From .env.example
HERMES_API_URL=http://127.0.0.1:8642           # Gateway HTTP API (opt-in)
HERMES_AGENT_PATH=/path/to/hermes-agent        # Auto-detected if sibling
ANTHROPIC_API_KEY=...                          # Backend provider key
```

**Feature detection:** Workspace probes `HERMES_API_URL` at startup. If reachable, it enables:
- Session persistence (`/api/sessions`)
- Memory search (`/api/memory/search`)
- Skills registry (`/api/skills/list`, `/api/skills/install`)
- Config editor (`/api/config/get`, `/api/config/set`)
- Job monitoring (`/api/jobs/list`, `/api/cron/jobs`)

If unreachable, it degrades to portable mode.

**JARVIS Parallel:** JARVIS's supervisor checks `SUPERVISOR_ENABLED` env var. If false, all events ESCALATE (fail-open). If true, supervisor LLM is consulted. All supervisor decisions record to `supervisor_decisions` table with latency + cost metrics.

---

## 6. Security Hardening

From `SECURITY.md`:

- **Auth middleware** on all API routes (API key validation)
- **CORS + CSP headers** (Content Security Policy)
- **Exec approval prompts** — before running arbitrary shell commands
- **Path traversal prevention** — sandboxed to workspace root
- **Token rate limiting** — context meter warns before hitting limits
- **Ignored directories:** `node_modules`, `.git`, `.next`, `.turbo`, `.cache`, `__pycache__`, `.venv`, `dist`

**JARVIS Parallel:** JARVIS supervisor requires `X-API-Key` header (same as all engine endpoints). ACK is terminal — once a signal is swallowed, no ping to Matt. Kill switch / IB disconnect bypass LLM (always ESCALATE in config, not in prompt).

---

## 7. Features Inventory (Selective Highlights)

### Chat Features
- Multi-session management (create, rename, delete, fork, pin)
- Auto-generated session titles
- Slash command menu (`/new`, `/clear`, `/model`, `/save`, `/skills`, `/skin`, `/help`)
- File attachment support (images via base64, multimodal)
- Voice input (Web Speech API)
- Inline provider selection dialog
- Connection status messaging

### Files Screen
- Full workspace file browser with directory tree
- Monaco Editor integration (full code editing)
- Create, read, write, rename, delete, mkdir
- Image preview (base64 rendering)
- Glob pattern filtering
- Max depth/entries limits

### Terminal Screen
- Full PTY terminal via Python pty-helper + xterm.js
- 256-color support (TERM=xterm-256color, COLORTERM=truecolor)
- Persistent shell sessions
- SSE-based streaming
- Platform-aware default shell (zsh/bash/PowerShell)

### Memory Browser
- Browse agent memory files in `~/.hermes/` (MEMORY.md, memory/, memories/)
- Text search across memory (max 200 matches, line-level results)
- Live Markdown editing
- Memory file list sorted (MEMORY.md first, daily files by date)

### Skills Browser
- 2,000+ skills from Hermes skill registry
- Search, filter, install, manage
- Skill metadata display

---

## 8. Relationship to Graeme's Supervisor Pattern

The X post by @gkisokay (https://x.com/gkisokay/status/2037902655016804496) describes a **supervisor agent pattern** using four markers and two Discord bots:

1. **Supervisor Agent** — classifies events (no generation, no trading)
2. **Markers:** `[STATUS_REQUEST]`, `[REVIEW_REQUEST]`, `[ESCALATION_NOTICE]`, `[ACK]`
3. **Discord Transport:** Two bots communicate via intent markers in Discord threads
4. **Terminal Rule:** Once ACK, the event is dropped; no further action

**JARVIS's Adaptation:**

- **Markers:** `"ACK"`, `"REVIEW"`, `"ESCALATE"`, `"HOLD_FOR_INFO"` (Enum in `SupervisorMarker`)
- **Transport:** In-process Python `SupervisorAgent` → OpenClaw WhatsApp notifier (no Discord, no threading)
- **Terminal Rule:** ACK is terminal — notification dropped, Matt not pinged
- **Fail-Open:** If supervisor LLM times out or returns invalid JSON, default to ESCALATE (never swallow unknown events)
- **Always-Escalate Events:** kill_switch, ib_disconnect (hardcoded in config, not in prompt)

**Hermes Workspace's Role:**
- Provides a **working example** of capability-aware UI (Mode A vs. Mode B)
- Shows how to **degrade gracefully** when APIs are unavailable
- Demonstrates **streaming + real-time updates** (SSE patterns JARVIS can adopt for supervisor decision notifications)

---

## 9. Prompt Refinement Proposals for `supervisor_prompts.py`

Current `supervisor_prompts.py` is **solid** and already incorporates Graeme's core principles. Proposed improvements:

### Proposed Enhancement #1: Confidence Scoring Clarity

**Current (line 48-49):**
```python
4. If the event is a BUY/SELL signal with confidence >= 0.75 in-regime
   and not a duplicate of the last 4h, ACK (Matt trusts clean signals).
```

**Proposed:**
```python
4. For BUY/SELL signals:
   a. Check confidence >= 0.75 AND in-regime AND not duplicate (last 4h).
   b. If all three true: ACK (Matt trusts clean signals, no need to review).
   c. If any false: ESCALATE (ambiguous or low-confidence signals merit review).
```

**Rationale:** Current phrasing could be misread as "ACK only if 0.75+". Explicit step-through prevents false ACKs on regime mismatch or duplicates.

---

### Proposed Enhancement #2: Regime Mismatch Handling

**Current (line 47):**
```python
3. If confidence < {floor} or regime mismatches the stated bias, ESCALATE.
```

**Proposed:**
```python
3. Regime validation:
   a. Extract stated bias (bullish/bearish/neutral) from event.payload.bias.
   b. Compare against current regime (from event.payload.regime).
   c. If regime ≠ bias (e.g., signal is bearish but regime is bullish): ESCALATE.
   d. If confidence < {floor}: ESCALATE regardless of regime.
```

**Rationale:** Makes the regime check executable—supervisor can validate `payload.bias` presence and mismatch logic without guessing.

---

### Proposed Enhancement #3: Duplicate Detection

**Current (line 49):**
```python
and not a duplicate of the last 4h, ACK
```

**Proposed:**
```python
and symbol is not in (previous 4h window trades) [from payload.recent_trades list or query supervisor_decisions table], ACK
```

**Rationale:** Current prompt assumes Matt will provide `recent_trades` in payload. Clarify whether supervisor.py should:
- Expect the engine to pass `recent_trades: [...]` in the payload, OR
- Query `supervisor_decisions` table itself for the last 4h of trades

**Recommendation:** Pass `recent_trades` from the engine (faster, no DB query in hot path). Update `build_user_prompt()` to include `"recent_trades": event.payload.get("recent_trades", [])`.

---

### Proposed Enhancement #4: HOLD_FOR_INFO Use Case

**Current (line 42):**
```python
{{"marker": "HOLD_FOR_INFO", "reason": "<=25 words"}}  -- log only, do not notify
```

**Question:** When should supervisor choose HOLD_FOR_INFO vs. ACK?

**Proposed:**
- **ACK:** Clean signal, high confidence, in-regime → swallow, do not notify
- **REVIEW:** Medium confidence OR slightly out-of-regime → notify with warning banner
- **ESCALATE:** Ambiguous, low confidence, regime mismatch, kill_switch, IB disconnect → notify unchanged
- **HOLD_FOR_INFO:** Informational events (morning brief, regime shift, cron job update) → log to table, no push notification

**Rationale:** Helps distinguish operational noise (cron status, regime changes—important for Matt's records but not urgent) from trading signals (urgent, needs review or action).

---

### Proposed Enhancement #5: Failure Mode Clarity

**Current:** No explicit statement about LLM failure handling.

**Proposed (add before line 37):**
```python
Failure modes:
  - If you cannot parse the event_type or payload, ESCALATE with reason "unparseable event".
  - If the marker JSON is invalid, the engine will default to ESCALATE.
  - Never return prose or free-form replies. Always return exactly two JSON fields.
  - If you're uncertain, ESCALATE. Your false-positive is cheap; Matt's missed kill switch is not.
```

**Rationale:** supervisor.py already has `fail-open ESCALATE on invalid JSON` logic. Making this explicit in the prompt reinforces the boundary: supervisor should never be complex or fragile.

---

## 10. Implementation Status & Integration Points

### Files to Wire (from manifest S01–S10)

1. **engine/notifications/supervisor.py** (S01 — pending)
   - SupervisorMarker enum: ACK, REVIEW, ESCALATE, HOLD_FOR_INFO
   - SupervisorEvent dataclass (event_type, payload, correlation_id, ts)
   - SupervisorDecision dataclass (marker, reason, pass_through, event, latency_ms, cost_usd)
   - SupervisorAgent class (enabled property, async review(event), async scan_cron_jobs(), stats(), is_available())
   - Singleton get_supervisor() / reset_supervisor()

2. **engine/routers/supervisor_router.py** (S02 — pending)
   - GET /supervisor/stats
   - GET /supervisor/decisions?limit=N
   - POST /supervisor/replay/{id}

3. **engine/database/migrations.py** (S03 — pending)
   - Migration 020: add supervisor_decisions table

4. **engine/notifications/openclaw_notifier.py** (S04 — pending)
   - Gate notify_signal, notify_approval_required, notify_trade_closed, notify_target via supervisor.review()

5. **engine/main.py** (S05 — pending)
   - Gate morning brief send_raw via supervisor.review()
   - Register supervisor_router
   - Register 5-min CronTrigger for supervisor.scan_cron_jobs()

6. **Tests** (S06–S07, S10 — pending)
   - test_supervisor.py: 15+ cases (ACK, ESCALATE, kill_switch always escalate, timeout fail-open, correlation_id threading, stats, etc.)
   - test_supervisor_cron_watcher.py: scan_cron_jobs() with mock jobs.json
   - test_supervisor_notifier_integration.py: full E2E with monkeypatched LLMCallResult

7. **Docs** (S08 — pending)
   - Append SUPERVISOR_ENABLED, SUPERVISOR_MODEL, SUPERVISOR_LLM_TIMEOUT_SECONDS, SUPERVISOR_ESCALATE_CONFIDENCE_FLOOR to engine/.env.example
   - Write docs/session-logs/supervisor-phase1-spec.md (architecture, file map, rollback, verification)

### Current State
- **supervisor_prompts.py** ✅ (already exists, locked-in reference to Graeme's pattern)
- **Hermes Workspace** ✅ (frontend/UI reference, shows capability-aware degradation)
- **S01–S10** ⏳ (awaiting implementation agents S01–S10)

---

## 11. Key Differences from Hermes Workspace

| Aspect | Hermes Workspace | JARVIS Supervisor |
|--------|------------------|-------------------|
| **Purpose** | Multi-agent orchestration UI | Event classification + routing |
| **Transport** | HTTP + SSE (frontend → backend) | In-process Python + WhatsApp/OpenClaw |
| **Modes** | Mode A (portable) vs. Mode B (enhanced) | Fail-open (always escalate on error) |
| **Markers** | N/A (not applicable, UI layer) | 4 enum values + JSON output |
| **State** | Session history, memory, skills | supervisor_decisions table only |
| **User Loop** | Human ↔ chat ↔ agent | Engine event → supervisor → Matt (WhatsApp) |
| **Degradation** | UI features hide/show based on API availability | All non-kill_switch events respect confidence floor |
| **Licensing** | MIT (reusable, no attribution required) | JARVIS trainer (internal) |

---

## 12. Licensing & Attribution

**Hermes Workspace:** MIT License (full text in LICENSE file)

```
MIT License

Copyright (c) 2026 Eric (@outsourc-e)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
...
```

**JARVIS Usage:** You can freely adopt patterns from Hermes Workspace (capability-aware degradation, streaming architecture, PWA design) without attribution. No commercialization restrictions.

---

## 13. Top 3 Insights for JARVIS Supervisor

1. **Fail-Open Degradation:** Hermes Workspace's Mode A/Mode B pattern teaches us that **disabling advanced features is better than hard-failing on missing APIs**. JARVIS's supervisor should follow the same principle: if the LLM is unavailable or returns invalid JSON, default to ESCALATE (never swallow events). The supervisor is a *filter*, not a *generator*.

2. **Minimal State, Maximum Reliability:** Hermes keeps only two concepts: (a) conversations (from backend), (b) capabilities (probed at startup). Similarly, JARVIS supervisor should keep only three pieces of state: (a) the marker enum, (b) the correlation_id for thread tracking, (c) the supervisor_decisions table for audit. No complex state machine = no hidden bugs.

3. **Transport Agnostic:** Hermes Workspace doesn't care if the backend is OpenAI, Ollama, or Anthropic. JARVIS supervisor doesn't care if the transport is WhatsApp, Discord, or a future OpenClaw broadcast channel. **Decouple the classification logic from the delivery mechanism.** supervisor.py returns `SupervisorDecision`; openclaw_notifier.py decides how to send it. If openclaw is down, the engine still logs the decision.

---

## 14. Document Generation Date & Handoff

**Generated:** 2026-04-10 15:30 CT  
**Manifest Task:** S09  
**Output File:** `C:\Users\mattm\ThinkorSwim\jarvis-trader\docs\research\hermes-workspace-notes.md`  
**Next Steps:** S01–S10 implementation agents can reference this doc for:
- Hermes Workspace's capability-aware architecture (inform supervisor fail-open design)
- OpenAI-compat spec (inform supervisor JSON output shape)
- Streaming patterns (future: real-time supervisor decision push to dashboard)

