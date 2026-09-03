# Canonical serving tree classification — 2026-09-03

## Verdict
`C:/Users/mattm/ThinkorSwim/jarvis-trader` is currently **serving-but-non-authoritative**.

It is valid enough to keep PM2 serving the dashboard on `:3010`, but it is **not** a trustworthy Git authority or safe source-edit lane.

## Evidence

### Runtime truth
- `pm2 status jarvis-dashboard` → `online`
- Authenticated `GET /api/runtime-snapshot` on `http://127.0.0.1:3010` → `200`
- Authenticated `GET /mission-control` on `http://127.0.0.1:3010` → `200`

### VCS / filesystem truth
- `git -C C:/Users/mattm/ThinkorSwim/jarvis-trader status --porcelain` summary:
  - total rows: `1939`
  - deleted: `1885`
  - modified: `26`
  - untracked: `28`
- `git rev-list --left-right --count origin/master...HEAD` → `0 0`
  - branch is not ahead/behind origin, so the problem is working-tree integrity, not branch drift.
- `.git` directory exists on disk.

### Build fragility
Background canonical build failed with:
- `ENOTEMPTY: directory not empty, rmdir 'C:\Users\mattm\ThinkorSwim\jarvis-trader\dashboard\.next\export'`

Current state after service recovery:
- `dashboard/.next/export` directory absent
- `dashboard/.next/export-marker.json` present

## Interpretation
This tree is in the exact failure class described by the session-coordination rule:
- runtime can be healthy enough to serve
- VCS / build state can still be untrustworthy
- in-place repair while PM2 is serving from the tree risks turning a source-of-truth problem into a runtime outage

## Recommended path [RISK]
1. **Do not use `jarvis-trader` for source edits or Git repair while it is serving.**
2. Continue all source work in the clean worktree:
   - `C:/Users/mattm/ThinkorSwim/jarvis-runtime-panel-master-20260902`
3. Treat canonical `jarvis-trader` as a **serving tree only** until a controlled cutover plan exists.
4. Before any future in-place Git mutation, archive the canonical `.git` directory and current `.next` tree.
5. Preferred remediation path:
   - create/verify a fresh clean canonical checkout or worktree
   - validate build + PM2 there
   - cut serving over only after fresh verification
   - only then decide whether to preserve or retire the current canonical tree

## Explicitly not recommended now
- `git reset --hard` in the serving tree
- deleting/recreating `.git` in place
- rebuilding repeatedly inside the serving tree while PM2 depends on it
- any engine/risk/kill-switch changes

## Next action
Use this classification as the basis for the n2 remediation plan: define the lowest-risk cutover path from `serving-but-non-authoritative` to `serving + authoritative`, without touching live risk behavior.
