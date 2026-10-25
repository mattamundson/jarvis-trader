# A-01 Contradiction Register (Static Baseline)

**Status:** IN PROGRESS — static evidence only; runtime observations outstanding.

| ID | Domain | Competing claims | Interim safe interpretation | Owner WP |
|---|---|---|---|---|
| CTR-001 | Eligibility | Root/engine/static tables and live eligibility endpoints have historically disagreed. | Static prose cannot authorize a trade; default deny on ambiguity. | A-02, D-08 |
| CTR-002 | Risk policy | Code defaults, comments, and environment values differ. | Observe active runtime before making numeric claims; do not change limits. | A-02, H-01 |
| CTR-003 | Datastore | Older architecture names PostgreSQL/Redis/QuestDB while the operational manager uses SQLite WAL. | SQLite is the observed code-path baseline; runtime use remains unobserved. | A-02, A-06 |
| CTR-004 | Execution | Gateway, connector, executor, order manager, router, OMS, and reconcilers overlap. | No module is declared the sole writer until runtime tracing and J-02 ADR. | A-03, A-06, J-02 |
| CTR-005 | Paper mode | Internal simulation, ledger-only paper, and IBKR paper are described under one label. | Preserve LOCAL_PAPER and IBKR_PAPER as separate evidence environments. | A-02, N-02 |
| CTR-006 | Runtime docs | File sizes, router counts, Python paths, and service claims are stale across docs. | Machine-generated inventory and observed health outrank copied counts. | A-01, O-03, M-03 |
| CTR-007 | Dashboard truth | UI routes and numbers can outlive their sources or external master-api availability. | UI is presentation only; unavailable is not zero. | K-01, K-12 |

This register does not resolve runtime truth. Resolution requires evidence named by the owning WP; absence of a contradiction here is not proof of consistency.
