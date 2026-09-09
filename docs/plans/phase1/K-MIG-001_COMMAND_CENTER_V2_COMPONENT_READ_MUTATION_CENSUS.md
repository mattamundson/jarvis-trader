# K-MIG-001 — Command Center V2 Component / Read / Mutation Census

**Parent receipt:** `COMMAND_CENTER_V2_MIGRATION_RECEIPT_DRAFT.md`  
**Plan:** JARVIS-MIP-1.0 / proposed JARVIS-MPP-1.0 mapping  
**State:** DRAFT EVIDENCE — NO REDIRECT OR REMOVAL AUTHORIZED  
**Observed source baseline:** `master@6afe8970b8a588a3b67131d960fe47bee6fa40cf`

## 1. Purpose

Inventory the active `/command-center-v2` product generation at source level so useful behavior can be harvested into the proposed canonical operator IA without preserving a permanent second dashboard. This census distinguishes **rendering**, **read projections**, and **mutations** because only the latter can change trading state.

The existence of these files on `master` does not mean the canonical product is implemented or visually accepted.

---

## 2. Source identities

| Source | Observed blob | Role |
|---|---|---|
| `dashboard/app/command-center-v2/page.tsx` | `c20eff4b62c4df1f8a92312c85556f1e7cca0a18` | cockpit + candidate approval/reject UI |
| `dashboard/app/command-center-v2/trade/page.tsx` | current at `master@6afe8970…` | manual PAPER TradeIntent ticket |
| `dashboard/app/command-center-v2/layout.tsx` | `c3e2e7cd44fb666cfa43791a66242f5f1bc56267` | V2-only navigation shell |
| `dashboard/lib/controlPlane.ts` | `69795743d7359a3161082863cb0253b43cfef305` | fail-closed multi-endpoint read projection + approval mutations |
| `dashboard/lib/tradeIntent.ts` | `cb87095276cc27501818317d40b68427d49735cd` | typed TradeIntent preview/read/submit client + submit capability |

---

## 3. Route-level census

### `/command-center-v2`

**Jobs currently served**
- display execution mode;
- display IB execution connection state;
- display safety/portfolio/position state;
- display pending candidates;
- calculate candidate geometry presentation from frozen server verdict data;
- approve PAPER candidate through server endpoint;
- reject candidate through server endpoint;
- surface degraded subsystem errors independently rather than replacing them with healthy defaults.

**Canonical destinations**
- trust/vitals → `/command-center`;
- risk/safety → `/risk` + `/command-center` summary;
- positions → `/portfolio` + `/command-center` summary;
- pending candidates and approve/reject → `/trades`;
- subsystem degradation detail → `/operations` and `/data` as applicable;
- V2-specific title/navigation → retire.

### `/command-center-v2/trade`

**Jobs currently served**
- define a manual PAPER futures intent;
- require stop and target client-side before preview;
- optionally provide a quantity ceiling;
- request a server-sized preview;
- render current server entry, equity, risk budget, risk/unit, allowed quantity, final dollar risk, and R:R;
- submit only a PREVIEWED intent when the cockpit execution gate is ready;
- after submit transport/server error, re-read durable intent state;
- render `RECONCILIATION REQUIRED — DO NOT RETRY` when durable state is `SUBMITTING`;
- explicitly label the page PAPER-only.

**Canonical destination**
- `/trades` / Trade Workstation.

### V2 layout

Current navigation contains only:
- Cockpit;
- Manual Paper Trade;
- PAPER control-plane badge.

**Disposition:** do not migrate as a second shell. Replace with canonical application navigation from `COMMAND_CENTER_PRODUCT_SPEC.md` after that spec is adopted.

---

## 4. Read/API census — `controlPlane.ts`

`fetchControlPlaneSnapshot()` independently captures each subsystem so one failed read does not erase the others.

| Read | V2 use | Canonical destination | Migration decision |
|---|---|---|---|
| `GET /health` | mode, IB connectivity, kill-switch-related health projection | shared Trust header, `/operations`, `/broker` | **KEEP / normalize** into canonical read model |
| `GET /safety/status` | kill switch, P&L, equity, drawdown, limits | `/risk` + Command Center summary | **KEEP / strengthen provenance** |
| `GET /portfolio` | equity, P&L, positions | `/portfolio` + Command Center summary | **KEEP**, broker/internal authority must be explicit |
| `GET /portfolio/risk` | portfolio risk projection | `/risk`, `/portfolio` | **KEEP / rationalize** with H-01 authority |
| `GET /approvals/pending` | candidate queue | `/trades` + Command Center attention list | **KEEP** if approval workflow remains product requirement |
| `GET /backtest/paper-status` | PAPER/backtest status context | `/strategies`, `/research-lab`, `/operations` as appropriate | **REVIEW**; avoid unrelated status aggregation on home |

### Read-side invariant worth harvesting

The `capture()` helper records failures by subsystem and returns `null` rather than fabricating values. The canonical product should preserve this **degraded-but-honest projection** pattern, while adding source, authority, timestamp, freshness, and reason code to capital-relevant fields.

### Read-side debt

- current V2 uses 3-second SWR polling;
- the target spec prefers governed HTTP queries plus SSE/WebSocket for observations where useful;
- V2 freshness is partly computed client-side for positions and is not yet a universal server-authoritative freshness contract;
- the combined cockpit snapshot is assembled in the browser rather than a canonical read-model/BFF contract;
- financial fields do not yet all carry uniform source/authority/version/freshness metadata.

---

## 5. Mutation census — `controlPlane.ts`

| Mutation | Client function | Server endpoint | Current browser authority | Canonical destination / rule |
|---|---|---|---|---|
| Approve candidate | `approvePaperCandidate()` | `POST /approvals/{id}/approve` | sends candidate ID + empty body | `/trades`; server remains final safety/execution authority |
| Reject candidate | `rejectPaperCandidate()` | `POST /approvals/{id}/reject` | sends candidate ID + optional reason | `/trades`; audited server mutation |

The client computes an **approval capability** to disable unsafe-looking actions, but this is presentation defense only. Server-side approval/risk/broker checks remain authoritative.

### Candidate presentation semantics to preserve

V2 separates and displays:
- candidate state / validation-only status;
- direction;
- strategy signal label;
- confidence;
- frozen quantity/entry/stop/target;
- risk and reward points;
- R:R;
- expiry countdown;
- explicit reasons when approval is blocked.

### Candidate semantics to improve in canonical UI

Do not present one opaque “approved” state as proof of execution readiness. Canonical Trade Workstation should distinguish:

```text
CANDIDATE
→ HUMAN/WORKFLOW APPROVAL (if required)
→ STRATEGY ELIGIBILITY
→ FRESH RISK VALIDATION
→ TRADE INTENT
→ OMS CLAIM
→ BROKER STATE
→ RECONCILIATION
```

---

## 6. Manual TradeIntent client census — `tradeIntent.ts`

| Operation | Client function | Server endpoint | Mutation? | Canonical treatment |
|---|---|---|---:|---|
| preview | `previewManualTradeIntent()` | `POST /trade-intents/preview` | stateful intent creation, no broker mutation | `/trades`; treat as preview/intent state, clearly not broker submit |
| read intent | `fetchManualTradeIntent()` | `GET /trade-intents/{id}` | no | shared OMS lifecycle projection |
| submit | `submitManualTradeIntent()` | `POST /trade-intents/{id}/submit` | **yes — PAPER broker mutation** | canonical OMS only after I-MIG-001 adoption/cutover evidence |

### Client-side states

Typed states currently include:

```text
PREVIEWED
SUBMITTING
SUBMITTED
BLOCKED
REJECTED
EXPIRED
```

`manualIntentCapability()`:
- requires a preview;
- blocks submit unless PAPER execution capability is ready;
- only submits `PREVIEWED`;
- blocks zero-sized server result;
- treats `SUBMITTING` as reconciliation-required.

### Idempotency

The browser generates an idempotency key (`manual-<UUID>` when Web Crypto is available; timestamp/random fallback otherwise). The canonical requirement remains server-enforced idempotency/request identity; browser-generated identity is useful but never the only duplicate defense.

---

## 7. Trade page interaction census

| UI element / behavior | Keep? | Canonical target | Notes |
|---|---|---|---|
| PAPER ONLY badge | yes, concept | persistent environment shell + `/trades` | environment distinction must become stronger, not weaker |
| symbol/direction/order type | yes | Trade Workstation intent form | use B-01 canonical instrument selector eventually |
| mandatory stop | yes | Trade Workstation | protective geometry required for exposure-increasing futures |
| mandatory target | yes for current futures bracket policy | Trade Workstation | policy-driven, not purely client validation |
| max account risk % input | **rework** | Trade Workstation | user may request a lower cap; H-01 must own maximum |
| optional quantity ceiling | yes | Trade Workstation | must never override server sizing |
| server-sized preview | yes | Trade Workstation | add policy version, data provenance/freshness, broker mode |
| account equity display | yes | Trade Workstation | add source, timestamp, authority |
| risk budget/dollar risk | yes | Trade Workstation | identify H-01 policy version/reason codes |
| R:R | yes | Trade Workstation | advisory geometry metric, not authorization |
| submit button only for PREVIEWED | yes | Trade Workstation | server still final authority |
| re-read durable intent after error | **yes — critical** | shared OMS client | preserve |
| `DO NOT RETRY` on SUBMITTING | **yes — critical** | Trade Workstation + Audit/Operations | preserve and tie to reconciliation action |
| “Back to cockpit” V2 link | no | canonical nav | retire |

---

## 8. Canonical component mapping

| V2 source concept | Proposed canonical component | Surface |
|---|---|---|
| `StatePill` / execution mode pills | `EnvironmentStatus`, `TruthStatus` tokens | global shell / all surfaces |
| `MetricCard` | provenance-aware metric card | Command Center / Portfolio / Risk |
| degraded `errors` list | dependency/degradation panel | Command Center + Operations |
| position freshness label | `ProvenanceFreshness` | Portfolio / Command Center |
| candidate card | `CandidateEvidenceCard` | Trade Workstation |
| approval capability reasons | `ActionGateReasons` | Trade Workstation |
| manual intent form | `TradeIntentComposer` | Trade Workstation |
| preview result | `RiskPreviewReceipt` | Trade Workstation |
| intent status pill | `OmsLifecycleStatus` | Trade Workstation / Audit |
| ambiguity warning | `ReconciliationRequiredBanner` | Trade Workstation / Broker / Operations |
| V2 nav | none | retire after canonical shell parity |

Names are proposed design contracts, not implementation requirements.

---

## 9. Migration acceptance matrix

Before `/command-center-v2` may redirect:

| Requirement | Current evidence | Missing |
|---|---|---|
| V2 source census complete | **this document** | update if source changes |
| read endpoints mapped | complete at source level | canonical read-model implementation |
| mutations mapped | complete at source level | canonical Trade/OMS implementation |
| canonical IA approved | product spec exists in draft #789 | explicit human adoption |
| canonical shell rendered | static blueprint only | actual Next.js implementation + visual review |
| degraded/unknown states preserved | V2 concepts inventoried | V3 canonical E2E |
| critical numeric provenance | partial V2 | source→API→render assertions |
| approval workflow parity | source behavior inventoried | canonical E2E |
| manual intent preview parity | source behavior inventoried | canonical E2E |
| PAPER submit parity | RT-2 active-unadopted | I-MIG-001 + V4 real IB PAPER |
| ambiguity/no-retry parity | V2 + RT-2 source behavior | V3/V4 observed evidence |
| route census has no required V2-only behavior | not yet | run after canonical implementation |
| rollback tested | receipt describes concept | execute before redirect |

---

## 10. Implementation sequence after product-plan adoption

```text
K-01A canonical shell + semantic status tokens (read-only)
→ K-01B canonical read-model/provenance contract
→ K-02 Command Center truth projection
→ K-02B degraded/unknown V3 tests
→ K-03 Trade Workstation preview/read lifecycle
→ I-MIG-001 OMS authority adoption/cutover prerequisites
→ K-03B PAPER submit + ambiguity/reconciliation visualization
→ V3 operator E2E
→ V4 real IB PAPER evidence for mutations
→ parity receipt
→ human redirect approval
→ V2 redirect
→ observation window
→ deprecate/remove V2
```

No new exposure-increasing backend feature is needed to begin the read-only K-01/K-02 work.

---

## 11. Current recommendation

**Harvest:** fail-closed independent reads, explicit degraded state, candidate geometry/reasons, PAPER-only labeling, server-sized preview, durable intent reread, and ambiguity/no-retry UX.

**Rework:** browser-assembled cockpit projection, inconsistent provenance/freshness, max-risk input semantics, route-specific status components, and 3-second polling as the long-term real-time model.

**Retire:** permanent V2 navigation/product identity once canonical feature/numeric/failure-state parity is proven.

**Current decision:** **NO REDIRECT / NO REMOVAL.** The canonical product is specified and visually prototyped in draft #789 but is not yet adopted or implemented.

**Invariant:** this census performs no API call, broker mutation, route redirect, risk change, or capital authorization.
