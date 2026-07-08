# PROPOSAL — Activate the autonomous pipeline on MES + MGC

> **Status: DRAFT PROPOSAL — requires Tier-3 sign-off from Amo. Nothing here is
> executed.** This document proposes a config change; it changes no running
> config and edits no safety code. The actual flip is a human `engine/.env` edit
> + `restart_engine.ps1` on the trading box.
>
> Companion to (does not replace) `docs/runbooks/AUTONOMOUS_PIPELINE_RUNBOOK.md`,
> which documents the mechanics, safety gates, and approve/reject flow. Read that
> first. This memo only covers the *decision* to point the loop at tradeable symbols.

---

## 1. Why this exists

The autonomous scheduler (`engine/scheduler/pipeline_autonomous.py`) is wired and
was enabled 2026-05-21 — but with `AUTONOMOUS_ACTIVE_SYMBOLS=MCL,MNQ`. Both MCL and
MNQ are `DO_NOT_TRADE_SYMBOLS` (HALTED), so every tick force-`NO_TRADE`s and the loop
**runs but can never enqueue a candidate**. It is on, and inert, by configuration.

The two active paper instruments are **MES + MGC** (Tier-3 auth 2026-05-24, per
`engine/CLAUDE.md`). Pointing the loop at them is what makes it actually do its job:
scan those symbols each tick and enqueue green, high-confidence candidates for review.

**No code change is required or proposed.** `AUTONOMOUS_ACTIVE_SYMBOLS` is read fresh
from env every tick; the committed default stays `MCL,MNQ` (a deliberate inert-by-
default safety). Only `engine/.env` on the box changes.

---

## 2. The safety envelope (unchanged by this proposal)

Grounded in the code as of this writing:

- **The loop never auto-submits an order** (`pipeline_autonomous.py:19`). Green +
  confident verdicts are inserted into `pipeline_approval_queue` with a TTL; a human
  approves via `POST /approvals/{id}/approve`.
- **Preflight refuses** the tick on: `ENABLE_AUTONOMOUS_PIPELINE=0`,
  `LIVE_TRADING_ENABLED=True`, kill-switch active, safety layer unavailable, or IB
  data down (`_preflight_check`, lines 301-331).
- **Entry-price sanity** rejects corrupted verdicts at enqueue AND at approve
  (closes the 2026-05-09 phantom-trade class).
- **Instant off:** `ENABLE_AUTONOMOUS_PIPELINE=0` + restart; pending candidates
  expire on TTL. Kill switch halts enqueue AND approve on the next tick, no restart.

This proposal does not touch any of that. It only changes which symbols are scanned.

---

## 3. The decision that actually needs Tier-3 judgment

There are **two** env knobs, and the second is the real one:

| Knob | Proposed | Effect |
|---|---|---|
| `AUTONOMOUS_ACTIVE_SYMBOLS` | `MES,MGC` | Scan the two approved paper instruments instead of the dead MCL,MNQ |
| `AUTONOMOUS_AUTO_APPROVE_PAPER` | **`0` (recommended)** | See below — this is the human-in-loop switch |

### `AUTONOMOUS_AUTO_APPROVE_PAPER` — undocumented in the runbook, must be decided

This flag exists in code (`pipeline_autonomous.py:263-298`) but is **not** in
`AUTONOMOUS_PIPELINE_RUNBOOK.md`. When `1`, a freshly-enqueued candidate is
**auto-approved in paper** by programmatically pressing the same approve button a
human would (`approve_candidate` → `safety_layer.submit_paper_order`, after re-checking
kill-switch, live-guard, validation-only block, entry-price sanity). It refuses when
`LIVE_TRADING_ENABLED` — the "never auto-submit live" guarantee holds.

- **`0` (recommended):** human-in-the-loop. Candidates wait in the queue for an
  explicit approve. This is the honest first step — you watch what the loop *would*
  do before letting it act.
- **`1`:** fully autonomous paper trading (no human between signal and paper order).
  Only consider after a sustained observation window at `0` shows the queue is sane.

**Recommendation: ship at `0`.** Prove the candidate stream is trustworthy before
removing the human.

---

## 4. Preconditions (Tier-3 checklist — verify on the box before flipping)

- [ ] **IB data connected** — the 2026-05-21 preflight verdict was **WAIT —
      ibkr_data_connected=false** (`scripts/autonomous_pipeline_activation.ps1`).
      Confirm `GET /health` shows `ibkr_connected/data_connected=true` (or accept the
      documented Polygon fallback) before enabling.
- [ ] **Kill switch clear** — `GET /safety/status` → `kill_switch_active:false`.
- [ ] **MES + MGC still approved paper** — cross-check `engine/CLAUDE.md` "Active
      Instruments" / the `/validation` scorecard (they are, as of 2026-05-24 Tier-3).
- [ ] **`LIVE_TRADING_ENABLED=False`** — invariant; confirm unchanged.
- [ ] **Threshold sanity** — the 2026-05-21 activation used `0.75`
      (above default 0.65). Decide whether to keep the conservative bar.

---

## 5. Proposed change (for the box, on approval — NOT executed here)

In `engine/.env` (gitignored, never committed):

```
ENABLE_AUTONOMOUS_PIPELINE=1
AUTONOMOUS_ACTIVE_SYMBOLS=MES,MGC        # was MCL,MNQ (dead / DO_NOT_TRADE)
AUTONOMOUS_CONFIDENCE_THRESHOLD=0.75     # conservative, matches 2026-05-21
AUTONOMOUS_AUTO_APPROVE_PAPER=0          # human-in-the-loop first (recommended)
```

Then `.\restart_engine.ps1` and verify per the runbook's "How to Enable" §
(loop-started log line + `GET /approvals/pending` returns `{"count":0,...}`).

---

## 6. Staged rollout

1. **Observe (days 1-N):** `AUTO_APPROVE_PAPER=0`. Let candidates accrue; review the
   queue via Discord/Hermes/dashboard. Confirm symbols, directions, confidences, and
   entry prices look right against the engine. Reject/approve by hand.
2. **Decide:** only if the candidate stream is consistently sane, consider
   `AUTO_APPROVE_PAPER=1` for hands-off paper — as its own Tier-3 decision.
3. **Rollback anytime:** `ENABLE_AUTONOMOUS_PIPELINE=0` + restart, or trip the kill
   switch (no restart). Pending candidates expire on TTL.

---

## 7. Follow-up doc fixes (apply on approval, not in this proposal)

Two accuracy gaps in `AUTONOMOUS_PIPELINE_RUNBOOK.md`, surfaced here, to fix when this
is approved (so the executed change and the runbook agree):

1. Its examples + env table still say `AUTONOMOUS_ACTIVE_SYMBOLS ... MCL,MNQ`. Update
   the guidance to MES,MGC with a note that MCL,MNQ are `DO_NOT_TRADE`.
2. `AUTONOMOUS_AUTO_APPROVE_PAPER` is entirely absent from the runbook. Add it to the
   Environment Variables Reference + a short "Auto-approve (paper only)" section.

---

## 8. Sign-off

- [ ] Amo (Tier-3): symbols → MES,MGC — approved
- [ ] Amo (Tier-3): `AUTONOMOUS_AUTO_APPROVE_PAPER` value — decided (`0` recommended)
- [ ] Preconditions §4 verified on the box
- [ ] Runbook follow-ups §7 scheduled

_Proposal only. No code or config changed by this document._
