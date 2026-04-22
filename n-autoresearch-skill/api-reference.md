# n-autoresearch API Reference

**Orchestrator base URL**: `http://127.0.0.1:3111`
**State store**: `./data/state_store.db` (SQLite-backed KV)
**Version**: 0.1.0

---

## Experiment Endpoints

### POST /api/experiment/setup
Initialize a new experiment tag (run this once per research session).

**Request**
```json
{
  "tag": "run-2024-01-15",
  "branch": "feat/rope-experiments"
}
```
**Response**: `{ "ok": true, "tag": "run-2024-01-15" }`

---

### POST /api/experiment/register
Register an experiment before training begins. Returns the experiment ID.

**Request**
```json
{
  "tag": "run-2024-01-15",
  "hypothesis": "Increasing head_dim from 128 to 256 may improve attention resolution",
  "description": "head_dim 128→256, n_layer stays 8",
  "category": "architecture",
  "sha": "a1b2c3d4"
}
```
**Response**
```json
{
  "ok": true,
  "experiment_id": "exp_1705123456_ab12cd34",
  "parent_id": "exp_previous_id_or_null"
}
```

---

### POST /api/experiment/complete
Submit results after training finishes.

**Request**
```json
{
  "experiment_id": "exp_1705123456_ab12cd34",
  "val_bpb": 1.2345,
  "peak_vram_gb": 18.2,
  "mfu": 0.412,
  "total_tokens": 1234567890,
  "param_count": 124000000
}
```
**Response**
```json
{
  "ok": true,
  "improved": true,
  "action": "keep_commit",
  "delta_bpb": -0.0123,
  "new_best": 1.2345
}
```
`action` is either `"keep_commit"` or `"git_reset"`.

---

### POST /api/experiment/crash
Log a crashed experiment.

**Request**
```json
{
  "experiment_id": "exp_1705123456_ab12cd34",
  "error_msg": "CUDA out of memory. Tried to allocate 4.2 GiB"
}
```
**Response**: `{ "ok": true, "consecutive_crashes": 1 }`
If `consecutive_crashes >= 3` the tag is aborted.

---

### POST /api/experiment/history
List experiments for a tag with optional status filter.

**Request**
```json
{
  "tag": "run-2024-01-15",
  "status": "completed"
}
```
`status` is optional. Omit to get all.

---

### POST /api/experiment/best
Get the best experiment for a tag.

**Request**: `{ "tag": "run-2024-01-15" }`
**Response**: Full experiment record with val_bpb, sha, description, metrics.

---

### POST /api/experiment/near-misses
Get experiments within `NEAR_MISS_THRESHOLD` (0.002 BPB) of the best.

**Request**: `{ "tag": "run-2024-01-15" }`
**Response**: List of near-miss experiment records sorted by val_bpb.

---

## Search Strategy Endpoints

### POST /api/search/suggest
Get a recommendation for what to try next. **Call this before each experiment.**

**Request**: `{ "tag": "run-2024-01-15" }`
**Response**
```json
{
  "ok": true,
  "mode": "explore",
  "suggestions": [
    { "category": "optimizer", "reason": "Only 2 optimizer experiments so far" },
    { "category": "attention", "reason": "Near-miss at exp_xyz used sliding window variant" }
  ]
}
```

---

### POST /api/search/strategy
Get the current strategy state.

**Request**: `{ "tag": "run-2024-01-15" }`
**Response**
```json
{
  "ok": true,
  "mode": "explore",
  "temperature": 1.0,
  "explore_ratio": 0.8
}
```

---

### POST /api/search/set-strategy
Manually override the strategy.

**Request**
```json
{
  "tag": "run-2024-01-15",
  "mode": "ablation",
  "temperature": 0.3,
  "explore_ratio": 0.2
}
```

---

### POST /api/search/adapt
Auto-update strategy based on recent results. **Call after each complete/crash.**

**Request**: `{ "tag": "run-2024-01-15" }`
**Response**: Updated strategy state.

---

## GPU Pool Endpoints

### GET /api/pool/list
List all registered GPU workers with health status.

**Response**: Array of `{ gpu_id, vram_gb, status: "idle"|"busy"|"offline", last_heartbeat }`

---

### POST /api/pool/acquire
Atomically claim an idle GPU for an experiment.

**Request**: `{ "experiment_id": "exp_..." }`
**Response**: `{ "ok": true, "gpu_id": "gpu_0", "gpu_index": 0 }` or `{ "ok": false, "reason": "no_idle_gpus" }`

---

### POST /api/pool/release
Return a GPU to idle state.

**Request**: `{ "gpu_id": "gpu_0" }`

---

### POST /api/pool/register
Register a new GPU worker (called by the GPU worker process on startup).

**Request**: `{ "gpu_id": "gpu_0", "vram_gb": 24, "gpu_index": 0 }`

---

### POST /api/gpu/health
Lightweight heartbeat from GPU worker (every 30s).

**Request**: `{ "gpu_id": "gpu_0" }`

---

## Report Endpoints

### POST /api/report/summary
Full session summary: best result, success rate, category breakdown, BPB progression.

**Request**: `{ "tag": "run-2024-01-15" }`

---

### POST /api/report/tsv
Export experiment history as tab-separated values (commit, BPB, memory, status, description).

**Request**: `{ "tag": "run-2024-01-15" }`

---

### POST /api/report/diff
Compare two experiments side by side.

**Request**: `{ "experiment_id_a": "exp_...", "experiment_id_b": "exp_..." }`
**Response**: Delta in val_bpb, param_count, peak_vram_gb.

---

### GET /api/report/tags
List all experiment tags sorted by creation date.

---

## State KV Scopes (internal reference)

| Scope | Contents |
|-------|----------|
| `experiments` | Individual experiment records |
| `lineage` | Parent→child relationships |
| `best` | Best val_bpb per tag |
| `near_misses` | Experiments within threshold of best |
| `gpu_pool` | GPU worker registrations |
| `strategy` | Current search strategy per tag |
| `tags` | Tag metadata (branch, creation time) |
| `crashes` | Crash records and consecutive counts |

---

## Configuration Constants

```python
VERSION                  = "0.1.0"
WS_URL                   = "ws://localhost:49134"
MAX_CONSECUTIVE_CRASHES  = 3
NEAR_MISS_THRESHOLD      = 0.002   # BPB delta
TIME_BUDGET              = 300     # seconds (5 min)
```
