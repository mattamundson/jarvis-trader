# Experiment review checklist

Use this before keeping the latest experiment commit.

## Scope control

- [ ] Only `train.py` was modified for a normal experiment.
- [ ] `prepare.py` was not changed.
- [ ] No dependencies or environment assumptions were added.

## Hypothesis discipline

- [ ] The hypothesis is explicit and testable.
- [ ] The category matches the actual change.
- [ ] The diff summary names the concrete knobs or modules changed.

## Code quality

- [ ] The diff is narrow and understandable.
- [ ] The change does not add gratuitous complexity.
- [ ] Any new complexity is justified by metric gain or strong follow-up value.

## Result quality

- [ ] The log was parsed successfully.
- [ ] The run was finalized through the API.
- [ ] Keep/reset decision matches the server recommendation.
- [ ] If the run is a near-miss, note whether it is a candidate for `combine` mode.

## Handoff quality

- [ ] Latest branch, tag, experiment_id, and outcome are captured.
- [ ] Next recommended experiment is written down.
