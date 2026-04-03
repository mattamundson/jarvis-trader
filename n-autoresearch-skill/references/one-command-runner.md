# One-command runner

The v4 pack adds a full-cycle operator wrapper that performs the common local workflow in one call:

1. optional tag setup
2. optional branch creation/switch to `autoresearch/<tag>`
3. commit `train.py`
4. register experiment
5. run `uv run train.py`
6. finalize to `/complete` or `/crash`
7. optionally apply `git_reset` automatically
8. print dashboard
9. write a timestamped status note in `status-notes/`

## Primary command

```bash
scripts/run_full_cycle.sh \
  --auto-setup \
  --tag mar11 \
  --category architecture \
  --description "increase depth 8->12" \
  --hypothesis "More capacity should reduce validation BPB" \
  --diff-summary "DEPTH=8 -> DEPTH=12"
```

## Baseline run

For an unchanged baseline, use `--baseline`. This permits an empty commit so the baseline still has a commit and experiment lineage.

```bash
scripts/run_full_cycle.sh \
  --auto-setup \
  --baseline \
  --tag mar11 \
  --category hyperparams \
  --description "baseline unchanged train.py" \
  --hypothesis "Unchanged baseline for the tag" \
  --diff-summary "baseline / no train.py changes"
```

## Useful flags

- `--auto-setup` — call setup and ensure `autoresearch/<tag>` branch exists
- `--baseline` — allow an unchanged baseline commit
- `--cuda-visible-devices 0` — force local training onto a specific GPU index
- `--no-auto-git-action` — do not auto-apply `git_reset`
- `--log-path path/to/log` — override the default `run-<experiment_id>.log`

## Behavior notes

- Normal runs require a staged change in `train.py`; otherwise the runner stops.
- Baseline runs allow an empty commit.
- Finalization still relies on metric lines in the log. If no `val_bpb` is found, the run is posted as a crash.
- A markdown status note is written after each run so another operator can inherit the workspace quickly.
