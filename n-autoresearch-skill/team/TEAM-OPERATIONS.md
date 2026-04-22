# Team operations

## Goal

Make the repository safe for multiple operators without losing experiment tempo.

## Rules

1. One hypothesis per experiment.
2. One commit per experiment.
3. Register before training.
4. Finalize after training.
5. Do not leave ambiguous local state.
6. If you reset a commit, state that explicitly in the handoff.
7. If you keep a commit, note why the added complexity is justified.

## Minimum handoff fields

- active tag
- active branch
- latest experiment_id
- description
- category
- outcome (`keep`, `discard`, or `crash`)
- current best val_bpb
- current strategy
- next recommended experiment

## Recommended cadence

- Before session start: run `scripts/status_dashboard.py`
- After each experiment: run `scripts/finalize_experiment.py`
- Before keeping a commit: run `scripts/last_experiment_review.sh`
- Before ending session: write a handoff using `team/HANDOFF-TEMPLATE.md`
