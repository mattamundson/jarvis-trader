# Repository map

## Core files

### `train.py`
The only file the agent is expected to edit during normal experiment execution.

Contains:
- model architecture
- optimizer logic
- training loop
- experiment knobs that affect `val_bpb`

### `prepare.py`
Read-only setup and evaluation support.

Contains:
- data preparation
- tokenizer-related setup
- evaluation harness support

Do not modify this file during normal autoresearch runs.

### `program.md`
The original agent operating instructions shipped with the repository.

It defines:
- the setup steps
- the experiment loop
- the allowed vs forbidden changes
- the iii REST API usage pattern

## Infrastructure

### `iii-config.yaml`
Starts the local iii runtime modules:
- state storage
- REST API
- pubsub
- cron
- observability

Default REST API host/port in this repo:
- host: `127.0.0.1`
- port: `3111`

### `workers/orchestrator/orchestrator.py`
Python orchestrator worker.

Primary responsibilities:
- experiment tracking
- search strategy state
- near-miss detection
- keep/discard logic
- GPU pool coordination
- reporting

### `workers/gpu/`
Rust GPU worker.

Primary responsibilities:
- self-register to GPU pool
- detect GPU metadata
- run `uv run train.py`
- parse metrics
- handle timeouts and health checks

## Functional architecture

The repo is best understood as four layers:

1. **Experiment surface**
   - `train.py`
2. **Runbook/instructions**
   - `program.md`
3. **Coordination plane**
   - orchestrator + iii state + search adaptation
4. **Execution plane**
   - one GPU worker per GPU

## Important repository design decisions

- single-file experiment surface
- fixed training budget for comparability
- structured state instead of git-only history
- multi-GPU parallelism through pooled workers
- automatic keep/reset recommendation from server-side logic

## Conversion note for Claude Code

When packaging this repository as a skill, the correct abstraction is:

- **Skill** = operational procedure for working inside the repo
- **Reference files** = repo architecture and API contract
- **Templates** = registration/completion payload skeletons

It is usually a mistake to flatten the entire codebase into a single instruction file.
