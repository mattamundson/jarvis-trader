# PR queue (post restart_engine / CI green)

Scheduled follow-ups from the 2026-04-03 plan. Each item should be a **narrow PR**.

| Order | Topic | Notes |
|-------|--------|--------|
| 1 | **Full test suite** | CI runs a Tier-1 subset; `engine/tests/` has async/mock/auth debt per session analysis. Expand only after triage. |
| 2 | **OrderRouter / `route_order()`** | Dead path today — remove or wire with tests if the abstraction stays. |
| 3 | **Dev API key hygiene** | Rotate `jarvis-dev-key-change-me` in local `.env`; never commit real keys (CI security grep). |
| 4 | **Strategy / trading rules doc** | Single canon under `docs/strategy/` if not already satisfied by `TRADING_RULES.md` / `EQUATIONS.md`. |
| 5 | **CI pytest expansion** | Add files to `.github/workflows/ci.yml` only when stable offline. |

Local parity commands mirror [.github/workflows/ci.yml](../../.github/workflows/ci.yml).
