# TradingView / crypto-bot execution integration — assessment

**Status:** Assessment only. Nothing here is implemented. Requested 2026-07-24 (option 3 of the
TradingView MCP integration task). This is the decision record for *why* the auto-execution path
is not wired, and *what it would take* to wire one — so the question doesn't get re-litigated from
scratch later.

## What was asked

Integrate two repos:
1. [tradesdontlie/tradingview-mcp](https://github.com/tradesdontlie/tradingview-mcp) — a chart-
   reading MCP server (78 CDP tools). **Integrated** (already in `.mcp.json`; now surfaced via the
   `tradingview-mcp` skill + `/jarvis-tv-chart` command). Read/analysis + Pine dev only.
2. [jackson-video-resources/claude-tradingview-mcp-trading](https://github.com/jackson-video-resources/claude-tradingview-mcp-trading)
   — an **autonomous crypto-exchange execution bot**. An LLM reads a `rules.json`, evaluates live
   TradingView data, and **places real orders** on BitGet/Binance/Bybit/OKX/… via exchange API
   keys. **Not integrated.** Its specification idea is salvaged (see the `strategy-spec-extract`
   skill); its execution half is what this document assesses.

## Why the crypto bot's execution path is a hard conflict

Every one of these is a jarvis-trader non-negotiable (`CLAUDE.md`, `.claude/rules/safety.md`) that
the bot's design breaks:

| jarvis-trader invariant | The crypto bot's behavior |
|---|---|
| `LIVE_TRADING_ENABLED = False` — paper only | Places live orders on real exchange accounts |
| `REQUIRE_HUMAN_APPROVAL = True` — every trade | Fires autonomously on a cron; no human in the loop |
| Safety layer is **hardcoded Python**, never LLM | An LLM one-shot prompt makes the go/no-go call |
| Orders route **only** engine → IB Gateway paper (4002) | Routes to crypto exchange REST APIs |
| Instruments are futures (MES + MGC active — MGC re-auth 2026-08-04, PR #597; MNQ/MCL halted, `DO_NOT_TRADE_SYMBOLS`) | Crypto pairs (BTCUSDT, …) |
| No credentials in-repo; `.env` gitignored | Ships `BITGET_API_KEY`/`SECRET`/`PASSPHRASE` env contract |

This is not a "tighten the config" gap — the bot's *architecture* (LLM-decided, autonomous,
direct-to-exchange) is the opposite of jarvis-trader's (hardcoded-safety, human-approved,
paper-gated). Adopting it wholesale would mean deleting the safety model, not extending it.

## What a *sanctioned* execution path would actually require

jarvis-trader already has an execution path — engine → IB Gateway **paper** (port 4002, account
DUP662235), behind the 6-check `SafetyLayer`, `RiskManagerAgent`, and `FundManagerAgent`, with
human approval via the WhatsApp/approval flow. Any new execution capability must go *through* that,
not around it. Concretely, to add or extend execution one would need:

1. **A Tier-3 human decision**, recorded — not an agent's initiative. `LIVE_TRADING_ENABLED` and
   `REQUIRE_HUMAN_APPROVAL` stay as they are unless Matt explicitly flips them with Tier-3 confirmation.
2. **No new direct-to-broker/-exchange route.** Orders continue through the engine's execution layer
   so the SafetyLayer, kill switch (-8% daily / drawdown halt), rate throttle, and position/margin
   caps in `engine/config.py` still apply. A crypto exchange has none of these wired — it would be a
   from-scratch safety build, and crypto is out of the current mandate anyway.
3. **`[safety-review]` PR tag + safety-reviewer sign-off** for any diff touching `engine/config.py`,
   `engine/risk/` (the hardcoded kill switch is `engine/risk/safety_layer.py`), the kill-switch
   enforcement in `engine/execution/` (e.g. `ib_order_manager.py`, `ibkr_executor.py` — there is
   no single `kill_switch.py` file), or position-sizing bounds.
4. **A validated edge first.** A strategy reaches "sizeable" only by graduating the candidate
   registry (6 independent forward paper OOS windows, PF CI-lower ≥ 1.10, p_edge ≥ 0.95, survives
   family-FDR) — and graduation is *necessary, not sufficient* (gate-v2 routing still governs).
   The bot has none of this; it trades a hand-written `rules.json` with no OOS validation.
5. **Port 4001 stays permanently blocked**; live-capital deployment is a separate phase entirely.

## Recommendation

Keep execution where it is: engine-mediated, IB paper, human-approved, hardcoded-safety. Take the
crypto bot's *only* transferable value — turning a trader's stated rules into a spec — through the
`strategy-spec-extract` skill, which lands the result in the pre-registration gates rather than an
order. Revisit an execution change only as an explicit, Tier-3, safety-reviewed piece of work with
its own PR — never as a side effect of "integrating a repo".

## Related

- `.claude/skills/tradingview-mcp/SKILL.md` — chart-read integration + rejection note
- `.claude/skills/strategy-spec-extract/SKILL.md` — the salvaged, safe half
- `.claude/rules/safety.md`, `CLAUDE.md` — the invariants cited above
- `engine/backtest/candidate_registry.py` / `candidate_registry.json` — graduation gate
