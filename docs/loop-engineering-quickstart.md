# Loop Engineering — PowerShell Quickstart (jarvis-trader)

> Hands-on companion to `docs/loop-engineering.md` (the mental model) and the
> `loop-brakes` skill (the safety checklist). This file is the "type these
> commands on Windows" guide. Flags verified against current Claude Code,
> 2026-06-22.

---

## 1. Why bother — the jarvis-trader business case

The leverage is not "write code faster." It is **moving repeatable, low-judgment
work off your plate while you keep judgment for yourself.** Concretely, for this
repo:

| Loop | Boring job it removes | Payoff |
|---|---|---|
| Test/build triage | Manually running `pytest` + `pnpm build` and reading output | A 9am report of only NEW failures; you stop babysitting green suites |
| PR/CI triage | Checking which PRs are red or reviewer-less | Inbox of "needs you" items, the rest archived |
| Secret-scan sweep | Remembering to run `check-secrets.sh` before push | Continuous guard against committing `.env`/keys |
| Doc/state drift | Noticing `CURRENT_STATE.md` has gone stale vs. code | A flagged diff for you to approve, not auto-applied |

What you should **never** automate here (the value of NOT looping):

- Anything that places an order or touches `engine/risk/`, `engine/config.py`,
  or kill-switch code. `REQUIRE_HUMAN_APPROVAL = True` is the whole point.
- Anything where being wrong costs paper-account dollars or breaks a safety
  invariant. Those stay human, every time.

The honest ROI math: on a $20–200 plan, one small capped loop pointed at one dull
job pays for itself in attention reclaimed. A swarm does not — the $1.3M/month
fleet in the essay is sponsored. Start with one loop, read every diff, widen only
when you trust it.

---

## 2. Step 0 — learn the brakes with zero risk

Open Claude Code and run the skill. No loop, no automation, just the checklist:

```powershell
claude
> /loop-brakes
```

Answer every cell in its table before you ever add `--max-turns` to a real run.

---

## 3. Running a loop in PowerShell

The flags are identical to macOS/Linux. Only **quoting** and **scheduling**
differ on Windows.

### Interactive loop (safest to start — dies when you close the session)

```powershell
claude
> /loop 30m run the fast pytest suite and pnpm build, list only NEW failures
```

`/loop` re-runs the prompt on the interval **while the session is open**. Close
the window and it stops. Good for "watch this while I work," not for overnight.

### Headless, fully capped run (the brakes, baked in)

PowerShell uses the **backtick** `` ` `` for line continuation (not `\`), and
double-quotes for the prompt:

```powershell
claude -p --max-turns 20 --max-budget-usd 2.50 `
  --permission-mode auto `
  --tools "Read,Bash,Grep" --disallowedTools "Write,Edit" `
  --output-format json `
  "Run engine fast tests and the dashboard build. Summarize only failures."
```

- `--max-turns` and `--max-budget-usd` only work in **print mode** (`-p`).
- Need a literal quote inside the prompt? Escape it as `` `" ``.

---

## 4. Scheduling on Windows (there is no crontab)

Two real options:

### Option A — cloud Routines (`/schedule`), laptop can be closed

```powershell
claude
> /schedule daily test+build triage at 8am
```

Runs on Anthropic's cloud, 1-hour minimum interval, survives reboots. Best when
you want it to fire regardless of whether your machine is on.

### Option B — Windows Task Scheduler calling a .ps1 (local, full control)

Use the shipped wrapper `scripts/loops/triage-loop.ps1` (read-only, all brakes
baked in). Register it once:

```powershell
$action  = New-ScheduledTaskAction -Execute "pwsh.exe" `
  -Argument "-File C:\Users\mattm\ThinkorSwim\jarvis-trader\scripts\loops\triage-loop.ps1"
$trigger = New-ScheduledTaskTrigger -Daily -At 8am
Register-ScheduledTask -TaskName "jarvis-triage-loop" -Action $action -Trigger $trigger
```

**Keep loops out of PM2.** PM2 manages the engine (port 8010); a loop crash must
never touch that process. Task Scheduler isolates them cleanly.

### Notifications and the dead-man watcher

Both shipped loops use `scripts/loops/loop-lib.ps1` for two brakes:

- **Notification** — set `JARVIS_LOOP_WEBHOOK` to a Discord/Slack-style webhook
  URL and the loop pushes a one-line result. Unset = silent (file report only).
  This follows the repo's existing env-gated webhook convention.
- **Dead-man heartbeat** — every run appends to `docs/loop-reports/.heartbeat`.
  Schedule `heartbeat-check.ps1` on a SEPARATE, more frequent trigger so a loop
  that silently stops firing pages you instead of failing quietly:

```powershell
# Watch the triage loop: alert if no run in 26h. Run it a few times a day.
$hbAction  = New-ScheduledTaskAction -Execute "pwsh.exe" `
  -Argument "-File C:\Users\mattm\ThinkorSwim\jarvis-trader\scripts\loops\heartbeat-check.ps1 -LoopName triage -MaxAgeHours 26"
$hbTrigger = New-ScheduledTaskTrigger -Daily -At 12pm
Register-ScheduledTask -TaskName "jarvis-heartbeat-triage" -Action $hbAction -Trigger $hbTrigger
```

### The recommended first scheduled loop — morning brief

`scripts/loops/morning-brief-loop.ps1` wraps the existing
`engine/scripts/daily_morning_briefing.py` (which posts the brief to Discord via
`DISCORD_WEBHOOK_URL`). It is pure read + report, fails closed if the engine is
down, and is the safest loop to start with:

```powershell
$mbAction  = New-ScheduledTaskAction -Execute "pwsh.exe" `
  -Argument "-File C:\Users\mattm\ThinkorSwim\jarvis-trader\scripts\loops\morning-brief-loop.ps1"
$mbTrigger = New-ScheduledTaskTrigger -Daily -At 9am
Register-ScheduledTask -TaskName "jarvis-morning-brief" -Action $mbAction -Trigger $mbTrigger
```

All three scripts return exit codes (0 = green, non-zero = problem), so Task
Scheduler's own run history is a free red/green dashboard.

---

## 5. The non-negotiable jarvis-trader guardrails

Every loop you create, local or cloud, inherits these (they override the brakes):

1. **No order placement, ever, unattended.** The human-approval gate is the
   dead-man check for trading.
2. **No autonomous edits to** `engine/risk/`, `engine/config.py`, or kill-switch
   code. Those need a human and the `[safety-review]` PR tag.
3. **Read curated state, write your own.** A loop reads `CURRENT_STATE.md` /
   `MEMORY.md` but writes its output to `docs/loop-reports/` — never edits the
   curated docs (`meta-discipline.md` rule 3).
4. **Budget every LLM-in-the-loop** against the `jarvis-cost-routing` skill.
5. **Live port 4001 stays blocked.** Paper only (4002, DUP662235).

---

## 6. Your first loop, end to end (the one-command path)

```powershell
# 0. Learn the brakes (interactive, in the Claude Code terminal)
claude
> /loop-brakes

# 1. Verify the box is ready (read-only; fix any [FAIL] before continuing)
pwsh -File scripts\loops\preflight.ps1

# 2. Run the safest loop ONCE by hand and read what it posts
pwsh -File scripts\loops\morning-brief-loop.ps1

# 3. Happy with it? Schedule the brief + its dead-man watcher in one command
#    (elevated shell; re-runnable; optionally persist the alert webhook)
pwsh -File scripts\loops\register-loops.ps1 -LoopWebhook https://discord.com/api/webhooks/...

# 4. Confirm + smoke-test the scheduled task
Get-ScheduledTask -TaskName jarvis-*
Start-ScheduledTask -TaskName jarvis-morning-brief
```

Then, once you trust that harness:

5. Graduate to `scripts/loops/triage-loop.ps1` for CI/test triage (run by hand,
   then add it to Task Scheduler the same way).
6. **Read every report for a week** before you widen scope or add another loop.

You designed it once. You stay the engineer.

---

## 7. Tier-2: the checker (maker/checker review loop)

The highest-value move in any loop is splitting the agent that writes from the
agent that checks. `scripts/loops/review-loop.ps1` is the **checker** half: it
runs an adversarial, READ-ONLY review of the current branch's diff against a base
ref and writes the verdict to `docs/loop-reports/`. It reuses the repo's existing
review tooling (the `/code-review` skill + `safety-reviewer` discipline) instead
of reimplementing review logic.

```powershell
# Second opinion before you open a PR by hand
pwsh -File scripts\loops\review-loop.ps1 -BaseRef origin/master
```

It is incapable of changing anything: `--disallowedTools "Write,Edit"`, so it
cannot edit code, commit, push, open, or merge a PR. Exit codes: 0 = no blocking
issues, 2 = blocking issue(s) found, 3 = run error.

Run this *on demand* (after staging work), not on a schedule — a checker with no
diff to review is wasted tokens. It never auto-merges and never touches
`engine/risk/`, `engine/config.py`, or kill-switch code.

### The full maker/checker loop

`scripts/loops/maker-checker-loop.ps1` composes both halves: a **maker** drafts
the change for a task in an isolated git worktree, a **hardcoded** safety-path
guard rejects any diff touching `engine/risk/`, `config.py`, kill-switch,
`trader.py` sizing, or `.env`, then the **checker** reviews the diff read-only.

```powershell
pwsh -File scripts\loops\maker-checker-loop.ps1 -Task "Add a --dry-run flag to scripts\foo.py and a test"
```

It stops at a human gate: the output is a worktree (`.worktrees/maker-<stamp>`,
gitignored) plus a report. Nothing is committed, pushed, or PR'd for you — you
inspect the worktree and open the PR by hand if you agree. Exit codes: 0 green,
2 review found blockers, 3 error, 4 safety-path violation (diff rejected
unreviewed). The maker may edit files (that is its job) but cannot commit/push,
and your real working tree is never touched.
