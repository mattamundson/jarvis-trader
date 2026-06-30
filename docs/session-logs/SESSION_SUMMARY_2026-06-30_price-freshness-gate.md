# SESSION SUMMARY — 2026-06-30 — Price-Freshness Gate, pm2 Recovery, and the LLM-Billing Wall

> **Companion documents (same folder):**
> - `HANDOFF_2026-06-30_price-freshness-gate-and-llm-blocker.md` — the structured, exhaustive handoff (state/files/git/TODO)
> - `CONVERSATION_2026-06-30_price-freshness-gate.md` — full secret-redacted transcript (1,616 turns)
>
> This document is the **narrative** — the "why we did what we did, in what order, and what we learned." It is meant to be read top-to-bottom by a fresh AI session that needs the *story* and the *judgment*, not just the facts.

**Repo:** `C:\Users\mattm\ThinkorSwim\jarvis-trader` · **Branch:** `fix/corey-cache-stale-nodata` · **Engine:** UP (pm2, `degraded` on LLM only)

---

## The one paragraph that matters

The autonomous paper pipeline booked fills against a **frozen MES price (~5300)** on 2026-06-29 while the live market was **~7497**, because the IB **paper** account has no futures market-data subscription and the engine fell back to a **months-old, self-consistent CSV cache** that defeated all three existing price-sanity anchors. We built and **deployed** the durable fix — a fourth, *absolute* anchor (**bar-timestamp freshness**) plus an **IB delayed-data stopgap** — verified the engine now sees real MES (~7487/7495), and restored clean pm2 supervision. The system is now **one step from its real goal** (generating calibrated paper volume), and that step is **not code**: the **LLM path is down** because Anthropic credits are exhausted, the OpenAI fallback key is globally dead, and local ollama is too heavy for this machine. Restoring it is an **Amo-only billing/key action**.

---

## Act I — The contamination and its diagnosis

The trigger was a concrete, alarming symptom: paper fills at ~5300 for MES when the continuous future was ~7497. The instinct "the price feed is wrong" was right, but the *interesting* part was **why nothing caught it**.

The engine has a `MarketDataManager` with a source ladder (TradingView MCP / IB / CSV cache). When IB's data leg failed — the paper account simply **isn't subscribed to futures market data**, so IB throws Error 10168/354 — the ladder fell through to a **CSV historical export**. That export was months stale, but it was *clean*: consistent OHLC, no NaNs, and crucially it was surfaced **tagged as a normal source**, not flagged stale.

Then `entry_price_sanity.check_entry_price_sanity()` did its job — and passed it anyway, because **all three of its anchors are relative**:
- **ATR-delta** compares the entry to recent bars — but the entry (~5300) *matched* the stale bars.
- **provenance-source** rejects `unavailable`/`error` — but the cache reported a benign source.
- **era-deviation** compares the entry to a robust median *of the same stale window* — also ~5300.

The realization that reframed the fix: **a self-consistent stale frame is invisible to every relative check.** The only surviving signal is the **wall-clock age of the latest bar**. That is the whole thesis of the fix.

---

## Act II — Designing the fix (and why it looks the way it does)

Two changes, deliberately complementary — one attacks the *cause*, one caps the *blast radius*.

**1. The 4th anchor — bar-timestamp freshness (`entry_price_sanity.py`).** A new `latest_bar_age_seconds()` reads the most-recent-bar timestamp (DatetimeIndex first, then a `timestamp`/`time`/`date`/`datetime` column; naive → UTC). If the latest bar is older than a ceiling (default **2 h**, env `ENTRY_PRICE_MAX_BAR_AGE_SECONDS`, floored at 60 s), the order is rejected — **fail-safe NO_TRADE**. The design choices were each load-bearing:
- *Absolute, not relative* — the entire reason the bug existed.
- *2 h ceiling* — wide enough to never nag on a slow tape; tight enough that a months-old cache is caught on the first check.
- *Opt-out and determinable-only* — it fires only when a timestamp exists, so real bars are protected while the timestamp-less synthetic frames in the legacy test-suite are skipped. That's why we could add 20 new tests **and** keep the existing 60-odd green.
- *Protects both paths* — manual approval and `AUTONOMOUS_AUTO_APPROVE_PAPER=1` both flow through this function, so one change covers both.

**2. The IB delayed-data stopgap (`market_data.py`).** In `IBKRDataConnector.connect()` we now call `reqMarketDataType(3)` (env `IB_MARKET_DATA_TYPE`, default 3 = delayed). The subtlety that makes this safe: `reqMarketDataType(3)` only *adds* delayed data **where there is no live subscription** — a subscribed feed keeps streaming live, never downgraded. So a subscription gap now yields **delayed real prices** instead of a **stale cache**. The whole block is non-fatal: if `reqMarketDataType` ever raises, `connect()` still succeeds.

Either fix alone would have prevented 2026-06-29. Shipping both is intentional belt-and-suspenders.

We worked test-first throughout: 20 freshness cases + 4 stopgap cases, full suite **86 green**.

---

## Act III — Shipping it through the safety gate

PR #194 went up and CI immediately failed the **Safety Invariant Check** — by design: any change touching `^engine/risk/` must carry `[safety-review]` in the PR body, with an explicit note on each safety invariant the change interacts with. This is exactly the kind of gate you do **not** route around. Amo authorized adding the tag; we wrote the per-invariant notes, the gate re-ran **green**, and **no hook was ever bypassed** (no `--no-verify`, no shortcuts). That's the intended workflow: the gate forces a human-readable safety argument to exist in the PR record.

---

## Act IV — Deploying without waiting on the merge

To get the contamination fix *live now* rather than after a PR merge, we landed the two commits (`a81cf29` freshness, `a326d75` stopgap) onto the **running** branch `fix/corey-cache-stale-nodata` and restarted under pm2 — keeping PR #194 as the clean-merge record. Verification was done against the **actual interface**, not log-absence (a recurring lesson on this system): the engine log showed `IBKR market-data type set to 3` and `IBKR connected`, and MES `marketPrice` read **~7487/7495** — real market, no longer frozen 5300.

---

## Act V — The pm2 kill-loop (a supervision lesson)

`jarvis-engine` carried a chronic **144-restart** count and kill-looped on the first pm2-path restart. The root cause was not the code — `port_guardian.py` is sound (it runs once, kills a single orphan if 8010 is held, then runs uvicorn in-process for one stable PID) — it was **mixing launch paths**: `restart_engine.ps1` starts its *own* standalone uvicorn, while pm2 launches `port_guardian.py`. When both touch port 8010, the supervisor churns and orphans accumulate. The fix was a clean `pm2 delete` → re-register with the venv interpreter and `--cwd engine` → `pm2 save`. The durable rule: **pm2 is the single supervisor; never start the engine via the standalone path while pm2 owns it.** Restart the managed engine with `pm2 restart jarvis-engine` (never `--reload`).

---

## Act VI — Hitting the wall: the LLM path

With the engine healthy on data and supervision, the remaining red flag on `/health` was `llm_path_healthy:false`. The chain is **claude → gemini → openai**:
- **Anthropic (primary):** `credit balance is too low` — out of credit.
- **OpenAI (fallback):** the key in `engine/.env:453` is **globally dead** — OpenAI returns HTTP 401 `invalid_api_key`, and it's identical to the copy in 1Password, so it isn't a sync problem; the key itself is revoked/expired.
- **gemini:** configured but never exercised this session — a possible *free* restore if its billing is live.

We tried local **ollama** (`hermes3:latest`) as a stopgap, with Amo's authorization. It **crashlooped the engine**: ~29 s cold inference stalled boot, and the model's 9.26 GB resident footprint on a box with ~3 GB free drove it to `status=stopped`. We reverted `JARVIS_LLM_PROVIDER` to `anthropic`, unloaded the model, and the engine recovered to its stable degraded baseline. The honest conclusion: **ollama is not viable on this hardware**, and the LLM restore is fundamentally a **billing/key decision** only Amo can make.

This matters because the LLM is upstream of *everything the recent roadmap is about*: no working LLM → the analyst agents can't run → no signals → **zero calibration volume**. The freshness gate, the auto-approve path, the IC/Brier calibration framework — they're all waiting on the one thing that has to come from outside the code.

---

## Act VII — The secret-hygiene thread (small, but it recurred)

When the OpenAI fix came up, Amo asked whether to save the new key "in a notepad file." The answer was a firm no — a plaintext secret at rest is exactly what `rules/secret-hygiene.md` forbids. The protocol we held to: keys live only in **1Password** (`op://Amo Personal/OpenAI-API/credential`); when we wire one we read it into a `$key` variable, print only a **redacted fingerprint**, write `.env` via the variable (so the `credential-guard` hook doesn't see a literal `sk-` and the value never lands in tool-call arguments), and verify against OpenAI's API before restarting. Today's attempt to read the key from the clipboard found **prose, not a key**, so nothing was written and nothing was restarted — the right outcome. (The clipboard's content turned out to be the directive that produced this very document set.)

---

## What a fresh session should believe vs. verify

- **Believe:** the contamination fix is real, tested, CI-green, and deployed; the engine sees real MES prices; pm2 supervision is clean.
- **Verify before trusting:** that the LLM is *still* down (it's the gating fact) — hit `/health` and read `llm_path_healthy`; that PR #194 is still OPEN and `[safety-review]` is intact; that the two execution paths (`engine/systematic/live_signal_executor.py` vs the auto-approve queue) are **both still default-OFF** before anyone enables either (they share no idempotency → double-fill risk).

## The one next action

**Restore the LLM path** — cheapest-first: probe gemini (possibly free), else Anthropic top-up (keeps Claude primary, no `.env` change) or a fresh OpenAI key into 1Password + `! op signin`. That single action converts a healthy-but-idle engine into one that finally produces the calibrated paper volume the whole effort exists to generate.

---

*Provenance: authored from the in-context summary, live git/`/health`/pm2 queries, and the rendered transcript. Secrets redacted throughout. Full structured detail in the companion HANDOFF; full dialogue in the companion CONVERSATION transcript.*
