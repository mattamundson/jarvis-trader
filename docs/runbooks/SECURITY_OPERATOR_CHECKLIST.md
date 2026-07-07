# Security operator checklist (Tier S)

Use this with [SECURITY_REMEDIATION.md](SECURITY_REMEDIATION.md) and [API_KEY_ROTATION.md](API_KEY_ROTATION.md). **Code cannot rotate your production keys** — this is the human execution list.

## Before scaling paper usage or sharing the repo

- [ ] Rotate **Anthropic**, **Polygon**, **Twilio**, **Schwab/OAuth**, and **engine `API_KEY`** if there is any chance they appeared in git history, logs, Discord, or transcripts.
- [ ] Run repo secret scan (e.g. `detect-secrets`, `gitleaks`, or `bash scripts/hooks/check-secrets.sh` if configured).
- [ ] Confirm **`.env`** and `client_secret*.json` are never committed.
- [ ] Enable or verify **log sanitization** for production-like environments (`ENABLE_SIGNAL_SANITIZATION` / formatter — see [engine/security/log_sanitizer.py](../../engine/security/log_sanitizer.py)).

## Kill switch persistence (evidence)

Kill switch state is persisted in SQLite `system_state` and reloaded on startup by `SafetyLayer._load_kill_switch_state`. Automated proof:

- [engine/tests/test_system_state.py](../../engine/tests/test_system_state.py) — `test_kill_switch_persists_across_restarts`
- [engine/tests/test_safety_layer.py](../../engine/tests/test_safety_layer.py) — `TestKillSwitchPersistence`

## After an incident

1. Revoke exposed credentials at the provider.
2. Rotate and redeploy `.env`; restart engine ([restart_engine.ps1](../../restart_engine.ps1)).
3. Append a row to the research / ops log with date and scope (no secret values).

**Strategic risk IDs:** RISK-001, RISK-002, RISK-003 in [docs/strategic/05_RISK_REGISTER.md](../strategic/05_RISK_REGISTER.md).
