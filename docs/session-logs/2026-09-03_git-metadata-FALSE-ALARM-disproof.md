# DISPROOF: the canonical `.git` is NOT truncated — do not run VCS recovery

_Written 2026-09-03 by session `5550d6e5` (cwd `~/.claude`). New file, deliberately not an edit
to `docs/roadmaps/2026-09-03-runtime-hardening-next-top10.md`, to avoid colliding with the
session that owns it._

## Stop signal

`docs/roadmaps/2026-09-03-runtime-hardening-next-top10.md` states:

> Failure class proved: the canonical runtime tree has a **truncated `.git` directory**.
> `.git` contains only `config`; `.git/HEAD` is missing.

**This is incorrect.** The repository is healthy. Two sessions reached this conclusion
independently (this one did too, first) because of a tooling blind spot described below.

Roadmap items **2** ("archive-safe VCS recovery plan") and **9** ("clean-lane execution
boundary for git repair") are recovery surgery for a problem that does not exist. Items 3-8
are unaffected and remain valid.

## Evidence the repo is intact

Run from PowerShell with cwd = `C:\Users\mattm\ThinkorSwim\jarvis-trader`:

| Check | Result |
|---|---|
| `git rev-parse --is-inside-work-tree` | `true` |
| `git rev-parse --abbrev-ref HEAD` | `master` |
| `git status -sb` | `## master...origin/master` |
| `git log -1 --format='%h %ad %s'` | `a56a6885  2026-09-02  Merge pull request #777 …` |
| `git status --porcelain` | 1909 entries (1871 `D`, 22 `??`, 16 `M`) |

`Get-ChildItem .git -Force` shows **all** of: `HEAD`, `config`, `refs`, `objects`, `index`,
`packed-refs`, `logs`. A truncated `.git` cannot report a branch, resolve HEAD, diff an index,
or print a commit log. It does all four.

## Root cause — the blind spot that fooled two sessions

`refs`, `objects`, and `logs` carry attribute value **`1048592`** = `Directory (0x10) |
0x100000`, where `0x100000` is `FILE_ATTRIBUTE_UNPINNED` — the OneDrive cloud-files marker for
a **dehydrated, online-only** placeholder.

- **Win32-based callers** (PowerShell `Get-ChildItem -Force`, native `git.exe`) trigger
  transparent hydration and see real contents.
- **Git Bash / MSYS** `ls`, `[ -e ]`, `find`, `stat` do **not** hydrate. They report the
  directories as absent or empty — silently, with exit code 0.

So `ls -la .git` truthfully printed only `config`, and every Bash-side existence check for
`HEAD` / `refs` / `objects` returned false. Both sessions trusted that view.

## Rule

**Never diagnose repository health from Bash-side filesystem checks on this machine.**
Ask `git` itself, or use PowerShell with `-Force`. `git rev-parse --is-inside-work-tree` is the
authoritative one-line check and costs nothing.

Filed to `~/.claude/skills/rules-windows-pitfalls/SKILL.md`.

## What IS real, and still needs a decision

`git status` reports **1,871 deleted tracked files**, concentrated in `docs` (663), `.claude`
(419), `scripts` (202), `thinkorswim-scripts` (70), `es-research-platform` (66), `data` (64),
`PaperClip` (45), `jarvis_api` (38) — and only 7 under `engine`.

All 1,871 are restorable from git objects (`git restore -- <paths>`), so nothing is lost.
But **do not bulk-restore**: the pattern (everything except the actively-developed engine and
dashboard trees) is consistent with a deliberate slimming, and blindly restoring would undo it.
That is Amo's call.

Genuinely at risk — untracked, therefore not recoverable from git — are 22 files including
`engine/approval/authorization.py`, `engine/backtest/research_rigor_gate.py`,
`engine/data/feature_snapshot.py`, `engine/execution/order_lifecycle_ledger.py`, and 10 paired
test files. **Commit or stash these before any tree-level git operation.**
