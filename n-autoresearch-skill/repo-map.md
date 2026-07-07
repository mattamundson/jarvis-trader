# n-autoresearch Repo Map

## File Responsibilities

| File | Editable? | Purpose |
|------|-----------|---------|
| `train.py` | YES — agent's only edit surface | GPT model, MuonAdamW optimizer, training loop, eval |
| `prepare.py` | NO — frozen | Data pipeline, tokenizer training, validation splits |
| `program.md` | Read-only for agent | Human strategy notes, session goals, constraints |
| `iii-config.yaml` | No | Orchestrator wiring (state, API, pubsub, cron, OTel) |
| `workers/orchestrator/orchestrator.py` | No | 22 REST functions — experiment, search, pool, report |
| `workers/gpu/src/main.rs` | No | GPU worker entry point, iii SDK init |
| `workers/gpu/src/functions/train.rs` | No | Spawns `train.py`, parses metrics from stdout |
| `workers/gpu/src/triggers/mod.rs` | No | HTTP trigger registrations for GPU worker |
| `workers/gpu/src/config.rs` | No | GPU worker config (TIME_BUDGET, ports) |
| `workers/gpu/src/state.rs` | No | State KV helpers for Rust worker |

---

## train.py Architecture

```
GPTConfig
  └── n_layer=8, head_dim=128, aspect_ratio=64
  └── seq_len=2048, vocab_size=from tokenizer

GPT(nn.Module)
  └── Embedding(vocab_size, n_embd)
  └── N × TransformerBlock
        └── CausalSelfAttention (Flash Attn 3, RoPE, sliding window)
        └── MLP (GELU)
        └── Value embeddings (alternating layers)
        └── Residual lambdas (learnable scaling)
  └── LM head (unembedding)

MuonAdamW (hybrid optimizer)
  └── Muon  → all transformer weight matrices
  └── AdamW → embeddings, unembedding, biases, scalars

Training loop
  └── Gradient accumulation
  └── bfloat16 autocast
  └── Dynamic LR schedule (warmup + linear cooldown)
  └── Muon momentum 0.85→0.95 over 300 steps
  └── Weight decay decays to 0 over training
  └── TIME_BUDGET exit (5 min)

Eval
  └── val_bpb (bits per byte on validation set)
  └── Logged: peak_vram_gb, mfu, total_tokens, param_count
```

---

## Orchestrator Architecture

```
orchestrator.py
  ├── StateKV           — KV store client (7 scopes)
  ├── register_experiment_functions()   — 7 functions
  ├── register_search_functions()       — 4 functions
  ├── register_pool_functions()         — 7 functions
  └── register_report_functions()       — 4 functions

22 functions total → 21 HTTP routes + 1 cron (pool::list every 30s)
```

---

## GPU Worker Architecture (Rust)

```
workers/gpu/src/
  ├── main.rs          — SDK init, function/trigger registration
  ├── config.rs        — TIME_BUDGET, WS_URL, constants
  ├── state.rs         — KV helpers
  ├── functions/
  │   └── train.rs     — Spawns train.py, streams stdout, parses metrics
  └── triggers/
      └── mod.rs       — HTTP trigger bindings
```

The GPU worker:
1. Receives HTTP trigger from orchestrator (acquire → run → complete/crash)
2. Spawns `python train.py` with GPU index as env var
3. Streams stdout and parses the final metrics line
4. Reports back to orchestrator via state KV

---

## iii Framework Primitives Used

| Primitive | Used For |
|-----------|----------|
| `StateKV` | All experiment/strategy/pool state storage |
| `Function` | Each of the 22 orchestrator endpoints |
| `HTTPTrigger` | Binds functions to REST routes |
| `CronTrigger` | `pool::list` every 30s for stale GPU detection |
| OpenTelemetry | In-memory metrics export |

---

## Data Flow Diagram

```
Agent (Claude/Codex)
    │
    ├─ reads ────────────────────→ program.md
    ├─ edits ────────────────────→ train.py
    ├─ calls REST ───────────────→ Orchestrator (port 3111)
    │                                    │
    │                               StateKV (./data/)
    │
    └─ triggers via orchestrator ─→ GPU Worker (Rust)
                                         │
                                    python train.py
                                         │
                                    stdout metrics
                                         │
                                    POST /api/experiment/complete
```

---

## Quick Start Commands

```bash
# 1. Install Python deps
uv pip install -r pyproject.toml

# 2. Prepare data
python prepare.py

# 3. Start orchestrator
python workers/orchestrator/orchestrator.py

# 4. Start GPU worker (separate terminal)
cd workers/gpu && cargo run

# 5. Initialize a tag
curl -X POST http://127.0.0.1:3111/api/experiment/setup \
  -H "Content-Type: application/json" \
  -d '{"tag": "run-001", "branch": "main"}'

# 6. Run the agent loop (Claude Code with this skill active)
```

---

## Requirements

- Python 3.10+
- `uv` package manager
- NVIDIA GPU (min 8GB VRAM; 24GB+ recommended)
- Rust 1.82+ (for GPU worker)
- `iii` framework (`pip install iii-sdk` or per README)
