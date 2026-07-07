---
name: n-autoresearch
description: >
  Autonomous ML research loop that modifies train.py, registers experiments via
  the iii REST API, runs 5-minute GPU training sessions, and iterates toward the
  lowest validation bits-per-byte (val_bpb). Supports multi-GPU parallelism,
  adaptive search strategy (explore→exploit→combine→ablation), crash recovery,
  and lineage tracking. Use when asked to run autoresearch, tune a training run,
  or orchestrate GPU experiments on this repo.
triggers:
  - autoresearch
  - n-autoresearch
  - run experiments
  - tune train.py
  - optimize val_bpb
  - iii experiment
---

# n-autoresearch Skill

You are operating the **n-autoresearch** autonomous ML experiment loop.
Your job is to iteratively modify `train.py`, register and run 5-minute
GPU training experiments, and work toward the lowest possible
**validation bits-per-byte (val_bpb)**.

---

## The Three Laws

1. **Only edit `train.py`.** `prepare.py` is frozen — never touch it.
2. **Every experiment must be registered before training starts.** No
   untracked runs.
3. **Elegance beats marginal gains.** A small improvement that adds
   ugly complexity is not worth it.

---

## Repo Layout (what matters)

```
n-autoresearch/
├── train.py          ← YOUR ONLY EDIT SURFACE
├── prepare.py        ← READ ONLY — data prep & tokenizer
├── program.md        ← Human-authored strategy notes (read first)
├── iii-config.yaml   ← Orchestrator config (port 3111, state at ./data/)
└── workers/
    ├── orchestrator/
    │   └── orchestrator.py   ← Python worker — 22 API functions
    └── gpu/src/              ← Rust GPU worker — executes training
```

---

## The Experiment Loop (repeat until done)

```
1. READ   program.md  — understand current goals and constraints
2. CALL   POST /api/search/suggest  — get recommended direction
3. THINK  Form a hypothesis; pick a category from the 14 categories
4. EDIT   train.py   — one focused change
5. COMMIT git commit -m "<category>: <short description>"
6. CALL   POST /api/experiment/register  (hypothesis, description, category, sha)
          → returns experiment_id
7. WAIT   GPU worker runs training (~5 min, TIME_BUDGET seconds)
8. CALL   POST /api/experiment/complete  (experiment_id + metrics from logs)
          → returns { improved: bool, action: "keep_commit" | "git_reset" }
9. ACT    If "keep_commit": keep changes. If "git_reset": git reset --hard HEAD~1
10. CALL  POST /api/search/adapt  — let engine update strategy
11. GOTO  1
```

---

## API Quick Reference

**Base URL**: `http://127.0.0.1:3111`

### Setup (once per tag)
```
POST /api/experiment/setup
Body: { "tag": "<run-tag>", "branch": "<git-branch>" }
```

### Core Loop Calls

| Step | Method | Endpoint | Key Fields |
|------|--------|----------|------------|
| Get suggestion | POST | `/api/search/suggest` | `{ "tag": "..." }` |
| Register | POST | `/api/experiment/register` | `{ "tag", "hypothesis", "description", "category", "sha" }` |
| Complete | POST | `/api/experiment/complete` | `{ "experiment_id", "val_bpb", "peak_vram_gb", "mfu", "total_tokens", "param_count" }` |
| Crash | POST | `/api/experiment/crash` | `{ "experiment_id", "error_msg" }` |
| Adapt strategy | POST | `/api/search/adapt` | `{ "tag": "..." }` |

### Inspection Calls

| Purpose | Method | Endpoint |
|---------|--------|----------|
| Current strategy | POST | `/api/search/strategy` |
| Best result so far | POST | `/api/experiment/best` |
| Near misses | POST | `/api/experiment/near-misses` |
| Full history | POST | `/api/experiment/history` |
| Summary report | POST | `/api/report/summary` |
| TSV export | POST | `/api/report/tsv` |
| Compare two runs | POST | `/api/report/diff` |

### GPU Pool

| Purpose | Method | Endpoint |
|---------|--------|----------|
| List GPUs | GET | `/api/pool/list` |
| Acquire GPU | POST | `/api/pool/acquire` |
| Release GPU | POST | `/api/pool/release` |

---

## train.py — What You Can Change

The model is a **GPT-based transformer** with:

| Component | Default | Notes |
|-----------|---------|-------|
| Layers | 8 | `n_layer` |
| Attention | Multi-head + GQA optional | Flash Attention 3 |
| Position embedding | RoPE | |
| Attention pattern | Sliding window ("SSSL") | |
| Value embeddings | Alternating layers | |

**Optimizer: MuonAdamW** (hybrid)
- AdamW for embeddings/unembedding/scalars
- Muon for transformer weight matrices

**Key hyperparameters to experiment with:**

```python
# Learning rates
emb_lr     = 0.6       # embedding LR
unemb_lr   = 0.004     # unembedding LR
matrix_lr  = 0.04      # Muon matrix LR
scalar_lr  = 0.5       # scalar param LR

# Regularization
weight_decay = 0.2
adam_betas   = (0.8, 0.95)

# Batch / sequence
device_batch_size = 128
total_batch_size  = 2**19
seq_len           = 2048

# Architecture
n_layer      = 8
aspect_ratio = 64
head_dim     = 128

# Schedule
warmup_ratio   = 0.0
cooldown_ratio = 0.5
```

**Training exits automatically** after `TIME_BUDGET` seconds (~5 min).
**Metrics logged** → val_bpb, peak_vram_gb, mfu, tokens/sec, param_count.

---

## Experiment Categories (use exactly one per experiment)

```
architecture    optimizer       hyperparams     activation
attention       normalization   regularization  initialization
data            tokenizer       schedule        ablation
combine         other
```

---

## Search Strategy States

| State | Behavior |
|-------|----------|
| `explore` | Try diverse categories, high temperature |
| `exploit` | Focus on best-performing category, low temperature |
| `combine` | Combine top near-miss experiments |
| `ablation` | Remove components to test necessity |

Strategy auto-advances via `/api/search/adapt` based on:
- Keep rate < 20% → shift toward exploit
- 3 consecutive crashes → abort tag
- Plateau detection → switch to combine/ablation

---

## Multi-GPU Parallel Operation

Each parallel agent:
1. Calls `POST /api/pool/acquire` → gets assigned a GPU index
2. Runs its own experiment loop independently
3. Calls `POST /api/pool/release` after completing/crashing

GPUs report heartbeats every 30s; stale workers (>60s) are marked offline
automatically by the cron trigger.

---

## Crash Handling

If training crashes:
```
POST /api/experiment/crash
{ "experiment_id": "...", "error_msg": "OOM / CUDA error / ..." }
```
Then `git reset --hard HEAD~1` to restore a known-good state.
After 3 consecutive crashes the tag is aborted — call `/api/search/adapt`
to assess.

---

## Reading Metrics from Logs

The GPU worker (Rust) parses stdout from `train.py`. Look for lines like:
```
val_bpb=1.2345 peak_vram_gb=18.2 mfu=0.412 total_tokens=1234567890 param_count=124000000
```
Pass these values verbatim into `POST /api/experiment/complete`.

---

## Session Startup Checklist

Before running the loop, verify:
- [ ] `iii-config.yaml` is present (orchestrator config)
- [ ] Orchestrator is running: `python workers/orchestrator/orchestrator.py`
- [ ] GPU worker is running: `cargo run` in `workers/gpu/`
- [ ] `prepare.py` has been run and data is ready
- [ ] Tag initialized: `POST /api/experiment/setup`
- [ ] Current best known: `POST /api/experiment/best`

---

## Philosophy

> "Make it work, make it right, make it fast — in that order.
> A small improvement that adds ugly complexity is not worth it."

Prefer changes that are:
- **Principled** — grounded in a clear hypothesis
- **Isolated** — one variable at a time
- **Reversible** — git reset is your undo
- **Legible** — another researcher can read the diff and understand why
