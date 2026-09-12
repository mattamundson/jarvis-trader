# Observability/Sentinel consolidation contract

Source-mining wave: GitHub repo consolidation wave 9.

This document folds the reusable `jarvis-sentinel` observability model into the active JARVIS runbook surface without importing another always-on process. It maps probes, alerts, heartbeats, and remediation outcomes to the mission evidence schema so future monitoring work produces reviewable proof instead of narrative status.

## Source provenance

| Source | Commit | Evidence mined |
|---|---|---|
| `mattamundson/jarvis-sentinel` | `400fe60d3e190275dd9493066028f70fd0fc7cf6` | README, `sentinel.example.yaml`, `sentinel/events.py`, `sentinel/probes/*`, `sentinel/analysis.py`, `sentinel/core.py`, `sentinel/status.py`, `scripts/deadman-switch.ps1`, and design spec. |
| `mattamundson/jarvis-trader` | `2661282f5fc756d8d064aed85773c9c66ded4508` | `docs/runbooks/health-probe-deadman-checklist.md` and current docs/runbook authority. |
| `mattamundson/master-jarvis` | `8acae9b91d47041710e29f822de05f72b2954eff` | `docs/repo-consolidation/mission-evidence-schema.md` and `mission-ops-consolidation.md`. |

Scope boundary: this PR is docs-only. It does not change live trading config, risk limits, kill-switch behavior, broker routing, `.env`, API keys, PM2, active instrument gates, scheduled tasks, or order behavior. Any future PR that changes restart behavior, kill-switch/risk thresholds, paper/live selection, broker routing, or active symbol gates requires a dedicated `[safety-review]` PR.

## Consolidation decision

Do not resurrect `jarvis-sentinel` as a third production authority by default. Instead:

1. `jarvis-trader` owns trading health evidence and any JARVIS-specific runbooks.
2. `home-scripts` may own host-level scheduled tasks after a separate implementation PR.
3. `master-jarvis` owns mission/evidence schema and cross-domain orchestration semantics.
4. `second-brain` stores journals, postmortems, and incident lessons.
5. `jarvis-sentinel` remains a reference repo until every useful pattern below has a canonical owner and verification gate.

This avoids a split-brain monitoring stack where a private Sentinel process, engine watchdogs, PM2, Windows Scheduled Tasks, and Mission Control each claim authority without shared evidence IDs.

## Sentinel patterns to preserve

| Pattern | Sentinel source | Canonical JARVIS translation | Why it matters |
|---|---|---|---|
| Append-only event substrate | `sentinel/events.py` `Event(kind, source, status, detail, metrics, extra)` | Every future watchdog/probe writes JSONL or JSON evidence rows with stable `kind`, `source`, `status`, metrics, timestamp, and retention path. | Makes failures reconstructable and supports trend detection without trusting chat summaries. |
| Probe result contract | `sentinel/probes/base.py` `ProbeResult(status, detail, metrics, predicted_failure_days)` | JARVIS probes should expose `OK/WARN/CRIT`, operator detail, structured metrics, and optional forecast horizon. | Separates observed health from prose and enables deterministic alert thresholds. |
| Restart grace | `sentinel/probes/engine.py` `restart_grace_seconds` | Engine liveness checks must suppress normal startup/restart warmup while still recording truthful grace metrics. | Prevents false CRIT pages and restart storms during known boot windows. |
| Passive brain-health probe | `sentinel/probes/hermes.py` `HermesBrainHealthProbe` | Prefer zero-token evidence from existing logs before paid active canaries. | Catches “process up, brain dead” provider cascades while limiting cost. |
| Provider burn-rate forecast | `sentinel/analysis.py` + `providers.py` `days_until_empty` | Provider/credit monitors should emit days-to-empty forecasts as metrics, not only hard-failure alerts. | Allows intervention before market-hours decision support degrades. |
| Debounce semantics | `sentinel.example.yaml` `debounce_ticks` and `analysis._sustained` | Require consecutive failing observations before page-worthy alert unless the signal is a forecast/explicit safety state. | Reduces one-tick noise without hiding sustained outages. |
| Independent delivery paths | `sentinel.example.yaml` routing + `notify/*` | At least one alert channel must survive engine/Hermes failure; static config alone is insufficient. | Monitoring coverage is false if the alert path shares the failed dependency. |
| Watch-the-watcher | `core._heartbeat` + `scripts/deadman-switch.ps1` | Local heartbeat plus independent dead-man readback before claiming watchdog coverage. | A dead monitor is itself an incident. |
| Read-only status surface | `sentinel/status.py` snapshot/dashboard | Mission Control should render probe state from event/heartbeat evidence, not recompute trading truth. | Keeps UI as observer, not authority. |
| Dry-run healer | `sentinel.example.yaml` `healer.dry_run: true` | Any remediation proof starts as dry-run/log-only, with risky actions ask-gated. | Preserves paper/live/risk/kill-switch safety boundaries. |

## Mission evidence mapping

Every future monitoring artifact should map into the `master-jarvis` mission evidence schema.

### Requirement contract

```json
{
  "schema_version": 1,
  "requirement_contract": {
    "contract_id": "contract.jarvis.observability.probe.<probe_name>",
    "subject_id": "jarvis.observability.<probe_name>",
    "intent": "Detect and prove a specific JARVIS health condition without changing trading behavior.",
    "expected_outcome": "Probe emits machine-readable OK/WARN/CRIT evidence with source provenance and a safe operator action.",
    "definition_of_done": [
      "Probe source of truth is named and reachable in a dry-run or read-only check.",
      "Failure debounce/grace rules are explicit.",
      "Alert delivery evidence is recorded without exposing secrets.",
      "No live trading config, risk, kill-switch, broker routing, .env, PM2, active instrument gate, or order behavior changes."
    ],
    "verification_method": "Dry-run probe output, JSON schema validation, secret scan, safety-boundary diff check, and remote PR readback.",
    "required_evidence_types": [
      "source_provenance",
      "command_output",
      "freshness_check",
      "safety_boundary_check",
      "remote_readback"
    ],
    "risk_class": "low",
    "approval_policy": "autonomous_for_docs_only_human_for_runtime_or_safety_surfaces"
  }
}
```

### Evidence record

```json
{
  "schema_version": 1,
  "evidence_record": {
    "evidence_id": "evidence.jarvis.observability.<probe_name>.<sha256_16>",
    "evidence_type": "freshness_check",
    "subject_id": "jarvis.observability.<probe_name>",
    "artifact_uri": "docs/runbooks/observability-sentinel-consolidation.md",
    "content_hash": "<sha256>",
    "created_at": "<utc_timestamp>",
    "producer": "background-repo-consolidation-loop",
    "code_commit": "<jarvis-trader_commit>",
    "environment_id": "windows-default-hermes-profile",
    "command": "python validate_wave9_docs.py",
    "exit_status": 0,
    "machine_result": {
      "status": "accepted",
      "changed_files": [
        "docs/runbooks/observability-sentinel-consolidation.md"
      ],
      "forbidden_runtime_paths_touched": 0,
      "secret_markers_found": 0
    },
    "summary": "Docs-only Sentinel consolidation evidence passed local validation.",
    "retention_path": "C:/Users/mattm/Archive/2026/worktrees/<wave9_archive>.zip"
  }
}
```

### Verification verdict

```json
{
  "schema_version": 1,
  "verification_verdict": {
    "verdict_id": "verdict.jarvis.observability.<probe_name>.local",
    "subject_id": "jarvis.observability.<probe_name>",
    "verifier_id": "independent-docs-validator",
    "status": "accepted",
    "reason": "Required provenance, freshness, validation, and safety-boundary evidence is present.",
    "evidence_ids": [
      "evidence.jarvis.observability.<probe_name>.<sha256_16>"
    ],
    "independence_check": "Validator reads committed artifacts and git diff scope, not producer prose.",
    "safety_check": "No trading runtime, risk, kill-switch, broker, .env, PM2, active instrument gate, or order path changed."
  }
}
```

A verifier may accept monitoring evidence only if all of these are true:

1. Producer lineage, commit, artifact path, and hash are present.
2. Probe source of truth is named and not circular. Example: Hermes health cannot be verified solely by a Hermes-delivered message.
3. Debounce/grace/freshness rules are explicit.
4. Alert channel evidence does not print secrets and includes a readback or logged delivery result.
5. `safety_check` explicitly confirms no trading runtime, risk, kill-switch, broker, `.env`, PM2, symbol-gate, or order path changed.
6. Evidence age is inside the requirement freshness window.

## Probe taxonomy for JARVIS

| Probe class | Source of truth | Status metrics | Evidence type | Safe operator action | Safety stop |
|---|---|---|---|---|---|
| Engine liveness | `GET /health`, `GET /health/watchdog`, PM2/port readback | HTTP status, `status`, subsystem booleans, latency, consecutive misses | `freshness_check`, `command_output` | Diagnose logs/port owner; use existing restart runbook only when authorized | No blind restart from a broad consolidation loop |
| Supervision parity | PM2 process table + TCP port owner + dashboard/engine URL | process state, PID, port state, restart count | `command_output` | Identify orphan/PM2 mismatch | No force-kill without scoped runtime-recovery lane |
| IB/paper broker visibility | Existing engine health fields and `/ib/connection-test` | paper port, connector status, stale age | `freshness_check` | Mark execution path degraded and escalate | No broker-routing/paper-live changes |
| Kill-switch and risk visibility | Existing engine safety fields | kill-switch active, drawdown/risk state labels | `safety_boundary_check` | Observe and report | No threshold or kill-switch mutation without `[safety-review]` |
| Market-data freshness | engine freshness/system data-integrity endpoints | last bar age, source, expected cadence, stale reason | `freshness_check` | Degrade confidence and block claims | No bypass of strategy/data gates |
| LLM/provider health | Hermes logs, provider status, low-cost canary where funded | provider failures, fallback count, forecast days, canary latency | `freshness_check`, `command_output` | Degrade research/briefing jobs or rotate provider in a scoped ops lane | No fabricated model output; no secret/key edits in docs PR |
| Alert delivery | Discord/Telegram/Twilio/toast self-test result | channel enabled, credential-present boolean, provider response ID/status | `command_output`, `remote_readback` | Repair delivery channel through secret-safe ops | No token printing; no claim from config alone |
| Watchdog heartbeat | heartbeat JSON/mtime and dead-man readback | age seconds, last probe status, last alert result | `freshness_check` | Page “monitor blind” and recover watcher via scheduled-task runbook | No assuming engine is down solely because watcher is down |
| Read-only dashboard status | event log + heartbeat snapshot | latest status per probe, sparkline history, heartbeat stale flag | `schema_validation_report` | Surface operator status | UI must not become a trading authority |

## Alert and remediation policy

1. `OK -> WARN/CRIT`: alert only after documented debounce unless the condition is a safety state, credential exhaustion, delivery-path failure, or forecast crossing a threshold.
2. `WARN/CRIT -> OK`: emit one recovery event and reset the dedupe/cooldown key.
3. Remediation defaults to `dry_run` until a dedicated implementation PR proves the exact action and rollback path.
4. Reversible, non-trading actions may later become auto-heal candidates only after incident history proves high confidence.
5. Risky actions stay ask-gated: trading-engine restart, Hermes restart with active peers, broker/gateway recovery, kill-switch/risk edits, `.env` changes, PM2 mutation, and anything touching positions/orders.
6. Alert copy must include: first failing probe, current severity, debounce/grace context, evidence path, and safe next action.

## Future implementation slices

These are intentionally separated so each can be tested and reverted independently:

1. `observability-event-schema`: define a JSON schema for probe/heartbeat rows under `docs/schemas/` and validate examples in CI.
2. `watchdog-heartbeat-json`: add a read-only heartbeat JSON writer to an existing watchdog script. Normal PR if it only writes local evidence and tests stale/fresh classification.
3. `deadman-dry-run`: add a dry-run dead-man classifier that reads the heartbeat and prints the alert body without sending live pages by default.
4. `delivery-self-test`: add a non-secret delivery self-test that records provider response metadata and redacts tokens.
5. `mission-control-observability-card`: render event-log/heartbeat state in Mission Control from fixtures first, then live read-only endpoint later.
6. `provider-burn-forecast`: emit provider/fallback forecast metrics from existing logs without active paid canaries as the initial low-cost path.

Implementation order should prioritize evidence plumbing before automation. The first runtime PR should prove stale/fresh heartbeat classification; it should not restart services.

## PR acceptance checklist

For any follow-up observability PR:

- [ ] Changed file list is limited to the scoped docs/tests/scripts.
- [ ] Source provenance includes repo, commit, and path.
- [ ] JSON/YAML examples parse.
- [ ] `git diff --check` passes.
- [ ] Secret marker scan returns zero live secrets.
- [ ] Safety-boundary diff check confirms no forbidden trading/runtime paths changed.
- [ ] If a remote write occurs, GitHub PR state and target file contents are read back.
- [ ] Worktree is archived before removal.
- [ ] Handoff records evidence paths, hashes, blockers, and next action.
