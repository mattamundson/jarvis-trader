# Operator concepts

## Core idea

This repository separates the autoresearch loop into four practical layers:

1. **Experiment surface** — `train.py`
2. **Instruction layer** — `program.md`
3. **Coordination plane** — orchestrator + iii state + search adaptation
4. **Execution plane** — one GPU worker per GPU

That separation is why the repo is more valuable than a simple bash loop.

## Why the single-file edit surface matters

Constraining normal edits to `train.py` gives you:

- small diffs
- reviewable lineage
- fewer accidental harness breaks
- easier keep/reset behavior

## Why near-misses matter

A run that does not beat the best score can still be useful when:

- it improved a different sub-mechanism
- it reduced complexity with near-equal quality
- it can be combined with another direction later

Near-miss retention makes `combine` mode possible.

## Why the search modes matter

The orchestrator adapts between:

- `explore`
- `exploit`
- `combine`
- `ablation`

The operator should treat these as default posture recommendations, not absolute laws.

## Team operating principle

In team mode, optimize for **inheritability** as much as metric quality.

A slightly worse experiment record with a perfect handoff is usually more valuable than a marginally better result with unclear local state.
