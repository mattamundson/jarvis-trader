# Operate v4 pack

The v4 pack is the first version intended to be used as a near turn-key operator overlay for the repository.

## What changed vs v3

- Added a robust Python register helper (`scripts/register_experiment.py`)
- Added a one-command full experiment runner (`scripts/run_full_cycle.py`, `scripts/run_full_cycle.sh`)
- Added runner-specific examples and reference notes
- Added automatic status-note generation after each run

## Suggested local operator flow

1. Edit `train.py`
2. Run the full-cycle wrapper
3. Inspect the dashboard and status note
4. If needed, use `team/HANDOFF-TEMPLATE.md` for a richer human handoff

## Fast start

```bash
scripts/validate_env.sh
scripts/run_full_cycle.sh \
  --auto-setup \
  --baseline \
  --tag mar11 \
  --category hyperparams \
  --description "baseline unchanged train.py" \
  --hypothesis "Record starting point" \
  --diff-summary "baseline / no train.py changes"
```
