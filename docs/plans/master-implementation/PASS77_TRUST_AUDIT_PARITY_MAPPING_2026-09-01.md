# PASS77 - Trust Audit Parity Mapping

## Scope

Completed P15-001 and P15-002 by ranking Trust Audit parity as the next route-consolidation tranche and mapping `/trust-pane` first-screen facts against Command Center.

## Mapping

| Trust Pane fact | Trust Pane source | Command Center compact owner |
|---|---|---|
| JARVIS liveness | `/health` | `Trust Audit Summary` `Liveness` row |
| Live/static provenance | panel error state | `Trust Audit Summary` `Provenance` row |
| Data-quality gate | `/analytics/bar-quality?hours=168` | `Trust Audit Summary` `Bar Rejects` row with gate/window detail |
| Validated edge | `/reports/edge-ledger` | `Trust Audit Summary` `Edge Ledger` row with PASS/FAIL detail |
| Market-data leg | `/health` `ibkr_data_connected` | `Trust Audit Summary` `Data Leg` row |
| Post-trade diagnostics | `PostTradeExecutionWidget` and `PostTradeSnippet` | `Trust Audit Summary` `Post-Trade` handoff row linking to `/trust-pane` |

## Decision

`/trust-pane` remains the deep audit drilldown. Command Center should expose compact audit authority, not inline the dense cross-system diagnostics.
