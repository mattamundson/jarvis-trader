# Team prompts

## Team operator kickoff

```text
Use the n-autoresearch skill in team mode. Read program.md, validate the environment, create or confirm a run tag, and start with a baseline. After each experiment, leave a handoff note using the provided template.
```

## Status-first mode

```text
Use the n-autoresearch skill. Before changing anything, show current tag status, best experiment, current search strategy, and GPU pool state. Then propose the next 3 experiments in priority order.
```

## Review-gated mode

```text
Operate this repo using the n-autoresearch skill, but do not keep any experiment commit until you have run the review checklist and summarized the exact train.py changes.
```

## Handoff mode

```text
Use the n-autoresearch skill and leave the workspace ready for a teammate. Include branch name, tag, latest experiment_id, outcome, reset/keep status, and the best next experiment.
```
