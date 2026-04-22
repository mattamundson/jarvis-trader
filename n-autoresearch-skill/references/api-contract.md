# iii REST API contract used by n-autoresearch

Base URL:

```text
http://localhost:3111
```

## Primary endpoints

### `POST /api/experiment/setup`
Initialize a run tag and associated state.

Minimal payload:

```json
{
  "tag": "mar11"
}
```

### `POST /api/search/suggest`
Return the current strategy and next experiment guidance.

Minimal payload:

```json
{
  "tag": "mar11"
}
```

Typical concepts returned:
- `strategy`
- `underexplored_categories`
- `high_yield_categories`
- `near_misses_available`
- `suggestions`

### `POST /api/experiment/register`
Register a hypothesis before training.

Payload fields used by the repo:

```json
{
  "tag": "mar11",
  "hypothesis": "Increasing depth from 8 to 12 should lower BPB due to more representational capacity",
  "description": "increase depth 8->12",
  "category": "architecture",
  "commit_sha": "abc1234",
  "diff_summary": "DEPTH=8 -> DEPTH=12",
  "parent_id": null
}
```

### `POST /api/experiment/complete`
Record successful training results.

Payload shape:

```json
{
  "experiment_id": "<id>",
  "val_bpb": 0.997900,
  "peak_vram_mb": 45060.2,
  "training_seconds": 300.1,
  "total_tokens_m": 499.6,
  "mfu_percent": 39.80,
  "num_steps": 953,
  "num_params_m": 50.3,
  "depth": 8
}
```

Expected decision fields in the response:
- `improved`
- `action` (`keep_commit` or `git_reset`)
- `best_val_bpb`

### `POST /api/experiment/crash`
Record a failed experiment.

Payload shape:

```json
{
  "experiment_id": "<id>",
  "error": "RuntimeError: CUDA out of memory..."
}
```

May lead to:
- crash tracking
- conservative strategy shifts
- abort advice after repeated failures

## Reporting endpoints

### `POST /api/report/summary`
Full stats for a run tag.

### `POST /api/report/tsv`
Export results in TSV format for compatibility with the original autoresearch workflow.

### `POST /api/report/diff`
Compare two experiments.

### `POST /api/experiment/best`
Return the best experiment for a tag.

### `POST /api/experiment/near-misses`
Return experiments close enough to the current best to consider combining.

## GPU pool endpoints

### `GET /api/pool/list`
List all GPUs and current status.

### `POST /api/pool/acquire`
Claim an idle GPU for an experiment.

### `POST /api/pool/release`
Release a GPU after training.

## Search modes

The orchestrator uses four strategy modes:
- `explore`
- `exploit`
- `combine`
- `ablation`

Heuristic examples:
- high crash rate => conservative exploit mode
- plateau with near-misses => combine
- long plateau without near-misses => ablation
- good keep rate => exploit
