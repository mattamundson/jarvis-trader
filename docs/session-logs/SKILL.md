---
name: n-autoresearch
description: Operate the n-autoresearch repository in Claude Code. Use when working inside the n-autoresearch repo to run the iii-backed experiment loop, edit only train.py, register results, and decide keep vs reset.
---

# n-autoresearch

Use this skill when the user wants Claude Code to act as the experiment operator for the `n-autoresearch` repository.

This skill converts the repository's README + `program.md` into a Claude Code-native operating procedure.

## What this repository is

`n-autoresearch` is not the research agent itself. It is the **execution harness** for autoresearch:

- `train.py` is the experiment surface
- `prepare.py` is fixed and read-only
- `program.md` defines the original agent loop
- the iii REST API tracks experiment state, search guidance, GPU pool status, and reports

## Primary objective

Lower `val_bpb` through repeated, controlled edits to `train.py` while preserving experiment lineage and respecting the repo's rules.

## Hard constraints

1. Modify **only** `train.py` unless the user explicitly asks for infrastructure changes.
2. Treat `prepare.py` as read-only.
3. Do not add dependencies or alter the evaluation harness.
4. Run each experiment with the repo's fixed-time workflow unless the user explicitly changes that policy.
5. Keep diffs tight and reviewable.
6. Prefer simple wins over complicated marginal gains.

## Default operating mode

### Before the loop

1. Confirm you are in the `n-autoresearch` repository.
2. Read:
   - `program.md`
   - `train.py`
   - optionally `prepare.py` for constants and evaluation context
3. Verify the harness is available:
   - iii REST API is reachable at `http://localhost:3111`
   - data exists in `~/.cache/autoresearch/`
4. If the user did not provide a run tag, ask for one or propose a short tag.
5. Initialize the run tag.
6. Create a branch named `autoresearch/<tag>`.
7. Run a baseline experiment before making changes.

## Canonical experiment loop

Repeat this loop until the user interrupts or changes direction:

1. Call search guidance for the active tag.
2. Choose a focused experiment idea.
3. Edit `train.py`.
4. Commit the change.
5. Register the experiment with hypothesis, category, diff summary, and commit SHA.
6. Run training and capture output to `run.log`.
7. Extract metrics from `run.log`.
8. Record completion or crash.
9. Follow the server decision:
   - `keep_commit` => keep the commit
   - `git_reset` => reset the last commit
10. Continue from step 1.

## Experiment categories

Use one of these categories when registering:

- `architecture`
- `optimizer`
- `hyperparams`
- `activation`
- `attention`
- `embedding`
- `normalization`
- `regularization`
- `scheduling`
- `initialization`
- `simplification`
- `combination`
- `ablation`

## Decision policy

### Good experiment behavior

- One clear hypothesis per run
- One or a very small number of tightly related changes per commit
- Diff summary that names the exact knobs changed
- Hypothesis written in plain language, not vague intent

### Bad experiment behavior

- Large refactors across unrelated parts of `train.py`
- Silent changes without registration
- Changing `prepare.py`
- Introducing new packages
- Ignoring crash patterns or repeated OOMs

## Multi-GPU behavior

If the environment is using the GPU pool:

1. Inspect pool availability.
2. Acquire a GPU for the experiment.
3. Run training with the assigned GPU.
4. Release the GPU after completion or failure.

Do not assume the local machine owns the GPU exclusively.

## Progress reporting to the user

When interacting with the user in Claude Code:

- Briefly state the current run tag, latest experiment, and result delta.
- Surface crashes immediately.
- Say exactly what changed in `train.py`.
- When an experiment is discarded, say so explicitly.
- When the server recommends a strategy shift, mention it.

## File loading guidance

Load these supporting files only as needed:

- For architecture and repository scope: [references/repo-map.md](references/repo-map.md)
- For exact REST endpoints and payloads: [references/api-contract.md](references/api-contract.md)
- For install/placement instructions: [references/install-in-claude-code.md](references/install-in-claude-code.md)
- For kickoff prompts and user-facing phrasing: [examples/kickoff-prompts.md](examples/kickoff-prompts.md)
- For payload skeletons: [templates/register.json](templates/register.json), [templates/complete.json](templates/complete.json), [templates/crash.json](templates/crash.json)

## Recommended command sequence

```bash
# init tag
curl -X POST http://localhost:3111/api/experiment/setup -d '{"tag":"<tag>"}'

git checkout -b autoresearch/<tag>

# get guidance
curl -X POST http://localhost:3111/api/search/suggest -d '{"tag":"<tag>"}'

# after editing train.py
git add train.py && git commit -m "experiment: <description>"
COMMIT=$(git rev-parse --short HEAD)

# register
curl -X POST http://localhost:3111/api/experiment/register -d @templates/register.json

# train
uv run train.py > run.log 2>&1

# inspect metrics
grep "^val_bpb:\|^peak_vram_mb:\|^training_seconds:\|^total_tokens_M:\|^mfu_percent:\|^num_steps:\|^num_params_M:\|^depth:" run.log

# complete or crash
curl -X POST http://localhost:3111/api/experiment/complete -d @templates/complete.json
# or
curl -X POST http://localhost:3111/api/experiment/crash -d @templates/crash.json
```

## Expected outputs

The skill should help Claude Code produce:

- disciplined `train.py` edits
- experiment registration payloads
- concise status updates
- safe keep/reset actions
- summary reports for a tag

## When not to use this skill

Do not use this skill for:

- generic ML advice outside this repository
- changing the iii infrastructure itself unless requested
- broad repo refactors unrelated to experiment execution
- packaging/deployment work unrelated to the autoresearch loop

## Examples

### Example invocation

User: `Read program.md and kick off a new experiment.`

Expected behavior:

1. Confirm or create a run tag.
2. Initialize the tag in iii.
3. Create `autoresearch/<tag>`.
4. Read `train.py` and baseline context.
5. Run baseline registration.
6. Begin the search-guided experiment loop.

### Example invocation

User: `Summarize the best experiments for tag mar11 and tell me what to try next.`

Expected behavior:

1. Query report and best/near-miss endpoints.
2. Summarize the best kept changes.
3. Identify high-yield or underexplored categories.
4. Recommend the next experiment direction.
