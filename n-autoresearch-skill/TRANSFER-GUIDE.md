# n-autoresearch → Claude Code Skill: Transfer Guide

## What This Package Is

A portable Claude Code skill that teaches Claude the complete operational
contract of the `iii-hq/n-autoresearch` repository — so Claude can run
the autonomous ML research loop without manual re-explanation every session.

---

## Files in This Package

| File | Purpose |
|------|---------|
| `SKILL.md` | **Main skill** — loaded by Claude Code on activation |
| `api-reference.md` | Complete REST API contract (all 22 endpoints) |
| `repo-map.md` | File structure, architecture diagrams, quick-start commands |
| `TRANSFER-GUIDE.md` | This file |

---

## Installation Options

### Option A — Project Skill (only active in this repo)
Copy the folder into the repo you're working in:
```
n-autoresearch/
└── .claude/
    └── skills/
        └── n-autoresearch/     ← paste here
            ├── SKILL.md
            ├── api-reference.md
            ├── repo-map.md
            └── TRANSFER-GUIDE.md
```

### Option B — Global Skill (active in any Claude Code session)
```
~/.claude/
└── skills/
    └── n-autoresearch/         ← paste here
        ├── SKILL.md
        └── ...
```

### Option C — Cowork / Desktop App
Drop the folder into the skills directory of your active plugin, or import
via the plugin manager if available.

---

## Activating the Skill

After placing the folder, restart Claude Code (or run `/reload` if supported).
Then invoke with:

```
/n-autoresearch
```

Or reference it implicitly by asking Claude to "run autoresearch", "optimize
val_bpb", or "run the experiment loop."

---

## What Claude Can Do With This Skill

- Follow the full 11-step experiment loop autonomously
- Form hypotheses, choose categories, edit `train.py`, commit, register, wait, and act on results
- Read strategy suggestions from `/api/search/suggest` and adapt behavior accordingly
- Handle crashes: log them, reset git, continue
- Manage multi-GPU pool (acquire → run → release)
- Generate session summaries via `/api/report/summary`
- Know which files to touch (only `train.py`) and which to leave alone

---

## What Claude Cannot Do With This Skill

- Start the orchestrator or GPU worker processes (those are infrastructure — you run them)
- Access the actual `./data/state_store.db` directly (all state is via REST)
- Make decisions that require reading `program.md` content (Claude reads this from disk at session start)

---

## Recommended Session Opener

Paste this into Claude Code at the start of a session:

```
/n-autoresearch

Tag: run-2024-01-15
Branch: feat/rope-experiments
Orchestrator: running at localhost:3111
GPU: 1x RTX 4090 (24GB)
Goal: minimize val_bpb below 1.20

Begin the experiment loop. Read program.md first.
```

---

## Design Rationale

### Why a skill, not a README paste?
Skills load once and persist across the session without consuming prompt
context on every turn. The agent stays focused on the task rather than
re-parsing documentation.

### Why three files instead of one big SKILL.md?
`SKILL.md` is the operating procedure — what to do and when.
`api-reference.md` is the reference — exact field names and response shapes.
`repo-map.md` is the map — where things live and how they connect.
Claude retrieves these as needed rather than loading everything upfront.

### Why not include train.py verbatim?
`train.py` changes with every experiment. Including it in the skill would
create a stale snapshot. Claude reads the live file from disk.

### Why not include the Rust GPU worker?
The GPU worker is infrastructure. Claude doesn't modify it. The skill teaches
Claude to interact with it via the REST API, which is the correct abstraction.

---

## Version History

| Version | Date | Notes |
|---------|------|-------|
| 1.0.0 | 2026-04-02 | Initial packaging from iii-hq/n-autoresearch main |

---

## Source Repo

`https://github.com/iii-hq/n-autoresearch`
Apache-2.0 License
