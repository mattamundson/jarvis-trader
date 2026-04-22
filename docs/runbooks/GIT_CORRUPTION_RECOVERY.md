# Git repository corruption recovery

Use when `git status` reports **`fatal: bad object HEAD`** or **`invalid sha1 pointer`** on `refs/heads/master`.

## 1. Diagnose

```bash
git fsck
```

Note any **`dangling commit`** lines — one may be a recoverable tip.

## 2. Try fetch (clean remote)

```bash
git remote -v
git fetch origin
```

If fetch fails with the same bad ref, temporarily point `master` at a known-good commit (see below) or re-clone.

## 3. Repoint `master` at a dangling commit (advanced)

Only if `fsck` shows a dangling commit you believe is the last good tip:

```bash
git update-ref refs/heads/master <dangling_commit_sha>
git reset --hard master
```

Verify with `git log -1` and `git status`.

## 4. Fresh clone (safest)

If objects are missing and fetch cannot repair:

```bash
cd ..
mv jarvis-trader jarvis-trader.bak
git clone https://github.com/mattamundson/jarvis-trader.git
# Copy over untracked .env and local artifacts as needed; do not copy .git from the bad clone.
```

## 5. After recovery

Run `pytest engine/tests/ -q` and `pnpm run build` in `dashboard/` before pushing.
