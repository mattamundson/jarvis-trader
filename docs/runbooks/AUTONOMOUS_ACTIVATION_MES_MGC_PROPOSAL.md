# PROPOSAL — Activate the autonomous pipeline on MES + MGC (+ MNQ, pending)

> **Status: DRAFT PROPOSAL — requires Tier-3 sign-off from Amo. Nothing here is
> executed.** This document proposes a config change; it changes no running
> config and edits no safety code. The actual flip is a human `engine/.env` edit
> + `restart_engine.ps1` on the trading box.
>
> Companion to (does not replace) `docs/runbooks/AUTONOMOUS_PIPELINE_RUNBOOK.md`,
> which documents the mechanics, safety gates, and approve/reject flow. Read that
> first. This memo only covers the *decision* to point the loop at tradeable symbols.
>
> **2026-07-08 update:** Amo requested MES,MGC,MNQ + `AUTONOMOUS_AUTO_APPROVE_PAPER=1`.
> MNQ is a documented no-op pending §3a below — flagged, not silently added. The
> auto-approve decision is recorded in §3b as an explicit, informed Tier-3 choice.

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

## 3. The decisions that need Tier-3 judgment

### 3a. Symbols — MES, MGC confirmed; MNQ is a documented no-op pending a separate decision

Amo requested `MES,MGC,MNQ`. MES and MGC are approved paper instruments — no issue.
**MNQ is different in kind, not just status:** it isn't merely defaulted-off, it is
force-blocked in code:

```python
# engine/backtest/signals.py:113
DO_NOT_TRADE_SYMBOLS = frozenset({"MCL", "MNQ", "M2K"})
```

This forces `NO_TRADE` at signal generation, unconditionally, **regardless of
`AUTONOMOUS_ACTIVE_SYMBOLS`**. So adding MNQ to the scan list today would:
- Burn an LLM call on MNQ every tick, and
- **Never produce a candidate** — it always resolves to `NO_TRADE`.

That's the same "configured but structurally inert" pattern the 2026-07-06 diagnosis
(`docs/strategic/09_SCOPE_COLLAPSE_FIX_STRATEGY.md`) found across this whole codebase.
This proposal will not reproduce it by listing MNQ as if it does something it can't.

To make MNQ actually tradeable requires removing it from `DO_NOT_TRADE_SYMBOLS` in
`signals.py` — a file `CLAUDE.md` marks Tier-3-gated — which means reversing a
documented halt (0 wins in 55 trades, all strategy families exhausted 2026-05-07)
**without new validation evidence**. That is its own workstream (fresh WFE/gate-v2
run + Tier-3 approval), not a line item here, and is **not** proposed or executed
by this document.

**Decided 2026-07-08 — (c): open the MNQ re-validation workstream separately.**
This proposal ships `AUTONOMOUS_ACTIVE_SYMBOLS=MES,MGC` (§5) — unblocked, not
waiting on MNQ. MNQ re-validation is scoped in
`docs/runbooks/MNQ_REVALIDATION_SCOPE.md` and is **not executable from a cloud
session** — it requires the engine venv + live/historical market data connections
that exist only on the trading box. See that doc for what "new evidence" would
actually mean vs. re-litigating the same failed result.

### 3b. `AUTONOMOUS_AUTO_APPROVE_PAPER` — set to `1`, Amo's explicit informed choice

This flag exists in code (`pipeline_autonomous.py:263-298`) but was **not** in
`AUTONOMOUS_PIPELINE_RUNBOOK.md` before this proposal. When `1`, a freshly-enqueued
candidate is **auto-approved in paper** by programmatically pressing the same approve
button a human would (`approve_candidate` → `safety_layer.submit_paper_order`, after
re-checking kill-switch, live-guard, validation-only block, entry-price sanity). It
refuses when `LIVE_TRADING_ENABLED` — the "never auto-submit live" guarantee holds.

The original recommendation here was `0` (human-in-the-loop first, prove the
candidate stream is sane before removing the human). **Amo was shown that tradeoff
directly — first auto-submitted paper order gets zero human review, no observation
window — and confirmed `1` anyway.** Recorded as an explicit Tier-3 decision, not a
default: full hands-off paper trading from tick one. The rest of the safety envelope
(§2) is unaffected — kill-switch, live-guard, and entry-price sanity still gate every
auto-approval attempt.

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

In `engine/.env` (gitignored, never committed). Decision (c) means MNQ is not in
this env block — it's scoped separately in `MNQ_REVALIDATION_SCOPE.md` and will
only be added here if that workstream produces a Tier-3 approval to lift the halt:

```
ENABLE_AUTONOMOUS_PIPELINE=1
AUTONOMOUS_ACTIVE_SYMBOLS=MES,MGC        # was MCL,MNQ (dead / DO_NOT_TRADE); MNQ deferred, see §3a
AUTONOMOUS_CONFIDENCE_THRESHOLD=0.75     # conservative, matches 2026-05-21
AUTONOMOUS_AUTO_APPROVE_PAPER=1          # Amo's explicit choice — hands-off from tick one, see §3b
```

Then `.\restart_engine.ps1` and verify per the runbook's "How to Enable" §
(loop-started log line + `GET /approvals/pending` returns `{"count":0,...}`).

**Because auto-approve is `1` from the start, the first watch is not "review before
approving" — it's "watch the audit trail immediately after."** Within the first tick
cycle after restart:
- Tail `engine/data/approval_audit.jsonl` for the first auto-approved entries.
- Confirm symbol/direction/entry price/confidence look sane against the live engine
  (per the numeric-accuracy discipline in `CLAUDE.md` — cross-check against source
  of truth, don't eyeball).
- `GET /approvals/history?days=1` to see submitted paper orders.
- The kill switch and `ENABLE_AUTONOMOUS_PIPELINE=0` remain the immediate stop —
  use either the moment anything looks wrong.

---

## 6. Rollout (no observation window — see §3b)

1. **Flip and watch immediately** (not "observe then decide" — auto-approve is live
   from the first tick): confirm the loop-started log line, then monitor the audit
   log / Discord webhook / `/approvals/history` in real time for the first candidates.
2. **Rollback anytime:** `ENABLE_AUTONOMOUS_PIPELINE=0` + restart, or trip the kill
   switch (no restart). Already-submitted paper orders are not reversed by this —
   only the queue/enqueue path stops.
3. If the candidate stream looks wrong (bad prices, wrong direction, too-frequent
   enqueues), the fastest safe stop is `ENABLE_AUTONOMOUS_PIPELINE=0`; consider
   reverting to `AUTONOMOUS_AUTO_APPROVE_PAPER=0` rather than fully disabling if the
   symbols/signals are fine and only the auto-submit behavior is in question.

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

- [x] Amo (Tier-3): `AUTONOMOUS_AUTO_APPROVE_PAPER=1` — confirmed 2026-07-08, explicit
      and informed (no observation window; see §3b)
- [x] Amo (Tier-3): MNQ — decision (c), 2026-07-08: deferred to
      `MNQ_REVALIDATION_SCOPE.md`; this proposal ships MES,MGC only (see §3a, §5)
- [ ] Preconditions §4 verified on the box
- [ ] Runbook follow-ups §7 scheduled, including the auto-approve-live monitoring
      note in §5 if not already covered

_Proposal only. No code or config changed by this document._
