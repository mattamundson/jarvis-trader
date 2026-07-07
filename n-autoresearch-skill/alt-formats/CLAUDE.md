# n-autoresearch operator prompt

You are operating the `n-autoresearch` repository.

Core rules:
- Edit `train.py` only during normal experiments.
- Treat `prepare.py` as read-only.
- Do not add dependencies.
- Use the iii API at `http://localhost:3111` to register, complete, and summarize experiments.
- Keep one clear hypothesis per experiment.
- After each run, obey the server decision: keep commit or reset.
- Prefer simple improvements over complexity.

Default workflow:
1. Read `program.md`, `train.py`, and optionally `prepare.py`.
2. Initialize a run tag and branch `autoresearch/<tag>`.
3. Run a baseline experiment unchanged.
4. Query `/api/search/suggest` before each new experiment.
5. Edit `train.py`, commit, register, train, parse metrics, and complete or crash the experiment.
6. Repeat until interrupted.

Use the reference files in this pack for exact payload shapes and startup steps.


## TEAM MODE

When multiple operators may inherit the workspace, always end a session with: tag, branch, latest experiment_id, outcome, best val_bpb, and next recommended experiment.
