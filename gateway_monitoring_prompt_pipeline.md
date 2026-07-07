# Gateway Monitoring Tool — Staged Research-to-Build Prompt Pipeline

**Purpose:** Drive an AI agent through a 4-phase funnel that discovers the best gateway-monitoring resources across the internet, extracts their best features and code, mines real operator pain points from social/community sources, and synthesizes a research dossier + architecture/build spec + starter code for a new, best-of-breed Power BI / Fabric gateway monitoring tool.

**How to run:** Execute phases in order. Feed each phase's saved output file into the next as context. Inspect intermediate output before advancing — kill or re-run a phase if quality is low. Do NOT collapse phases into one pass.

**Stack context to carry through all phases (the builder's environment):**
- Target platform: Power BI / Microsoft Fabric, On-premises Data Gateway (standard + VNet), OneLake, Fabric capacity.
- Build stack preference: Python (primary), PySpark, PowerShell, SQL; Fabric notebooks/Lakehouse; Delta tables (medallion architecture); deployable to a Fabric workspace or lightweight local/Railway/Vercel front-end.
- Operator: principal-level data/analytics engineer building this as an internal company tool.

**Global rules to embed in every phase prompt:**
- Accuracy over fluency. Never invent APIs, counter names, prices, product specs, or code behavior. If unverifiable, label `[Unverified]`. Label decision-critical claims `[Assumption]` / `[Inference]`.
- Every extracted feature, code pattern, and pain point MUST carry a source URL and a one-line evidence quote/paraphrase. No source = it does not exist.
- Distinguish three "gateways" explicitly and never conflate them: (a) On-premises Data Gateway (the thing that actually needs monitoring here), (b) VNet data gateway, (c) API/app gateways (out of scope — exclude).

---

## PHASE 0 — Scope & Calibration Prompt

> You are a principal-level Microsoft Fabric / Power BI platform engineer. Before any research begins, produce a scoping brief for a project to build a best-of-breed **On-premises Data Gateway monitoring tool** for Power BI / Fabric.
>
> Deliver, in prose plus a compact table where useful:
> 1. **Disambiguation.** Define the three things people call a "gateway" in the Microsoft data ecosystem (On-premises Data Gateway, VNet data gateway, API/app gateways). State precisely which is in scope (On-prem + VNet gateways) and which is excluded.
> 2. **Monitoring surface map.** Enumerate every observable signal source that a complete gateway-monitoring tool could draw from. For each, note what it exposes and its access method. Cover at minimum: the Gateway Performance Monitoring public preview / `GatewayPerformanceMonitoring` logs, the on-prem gateway configuration & report files, Windows PerfMon counters exposed by the gateway, the gateway logs (Mashup/Query/Report/Spatial logs), `Get-OnPremisesDataGateway*` PowerShell cmdlets, the Fabric/Power BI Admin & Gateway REST APIs, the Monitoring workspace / capacity metrics, and any service-side refresh-history telemetry.
> 3. **The job-to-be-done.** Define the 6–10 questions a gateway operator most needs answered (e.g., "which queries are saturating the gateway," "is a refresh failing because of the gateway or the source," "what is gateway CPU/memory headroom," "which data sources route through which gateway," "are spooler files spilling to disk"). These become the feature requirements the later phases score against.
> 4. **Known-gap hypothesis.** State, as `[Hypothesis]`, the 3–5 areas where existing solutions are believed weak (to be confirmed in Phase 3), e.g., cross-gateway fleet view, query-level attribution, alerting, historical trend retention, multi-tenant/cluster visibility.
> 5. **Success criteria for the final tool** — the bar the synthesized architecture must clear.
>
> Output as `phase0_scope.md`. Be exhaustive on the monitoring surface map — it is the backbone of every later phase. Do not propose architecture yet.

---

## PHASE 1 — Discover Prompt (cast wide, then qualify)

> Input: `phase0_scope.md`.
>
> You are running source discovery for a best-of-breed On-premises Data Gateway monitoring tool. Goal: assemble a **qualified source inventory**, NOT a "top 10 list." Optimize for feature coverage across source classes, not popularity.
>
> **Search across these source classes and meet the minimum quota for each:**
> - Microsoft first-party (≥4): official Gateway Performance Monitoring docs/preview, the gateway log/PerfMon documentation, official sample reports/templates (e.g., the Gateway Performance PBIT/monitoring report), admin/gateway REST API docs, Fabric capacity metrics app.
> - Community GitHub repos & gists (≥6): gateway log parsers, PerfMon collectors, PowerShell health scripts, Power BI report templates over gateway logs, refresh-failure analyzers.
> - Blog posts / technical walkthroughs (≥5): from MVPs and practitioners showing real implementations (favor ones with code or PBIX/PBIT artifacts).
> - Vendor / commercial tooling (≥3): paid monitoring products (note features, not price unless verifiable) to understand the feature ceiling.
> - Community Q&A & forums (≥4): Power BI Community, Microsoft Q&A, Stack Overflow threads describing how people actually monitor gateways today.
>
> **For each source produce a row:** name | URL | source class | what it covers (1 line) | artifact present (code/PBIT/script/none) | freshness (last meaningful update) | initial signal score 1–5.
>
> **Kill rules — exclude and log the reason:** dead/abandoned with no reusable artifact; pure SEO regurgitation with no original feature or code; conflates gateway with API/app gateway; behind a paywall with zero discoverable feature detail.
>
> Output `phase1_sources.md`: the full qualified inventory (target 22–30 sources after kills), the kill log, and a coverage matrix showing which Phase-0 monitoring-surface signals each source class addresses (flag any signal NO source covers — that's a build-it-yourself gap).
>
> Do not extract features in depth yet. Discovery and qualification only.

---

## PHASE 2 — Extract Prompt (features + code, evidence-bound)

> Inputs: `phase0_scope.md`, `phase1_sources.md`.
>
> You are extracting the best **features, strategies, and reusable code/artifacts** from the qualified sources. Work source-class by source-class. Every item must be evidence-bound: source URL + one-line evidence quote/paraphrase. Unsupported items are discarded.
>
> **For each notable feature/strategy, produce a structured entry:**
> - Feature name & one-line description
> - Source(s) + evidence
> - Signal source it consumes (map to Phase-0 monitoring surface)
> - Implementation approach (how it technically works — counter, log field, API call, parsing strategy)
> - Reusable code/artifact: extract or summarize the actual code pattern (PowerShell cmdlet usage, log-parsing regex/schema, PerfMon counter list, REST endpoint + payload shape, DAX/measure, PBIT data model). Quote real code where present; mark `[Unverified]` if you cannot confirm it runs.
> - Strength (why it's best-in-class) and limitation (what it misses)
>
> **Then build the master Feature Matrix:** rows = every distinct feature found; columns = which sources implement it, maturity, and a "best implementation" pointer. Collapse duplicates; when multiple sources implement the same feature, name the single best implementation and say why.
>
> **Explicitly surface:** the 5–10 "crown-jewel" features (best single idea from any source) and the orphan signals from Phase 0 that NO source exploits well (greenfield opportunities).
>
> Output `phase2_features.md`. Code-bearing entries must include the extracted code or a faithful schematic of it. Do not design the new architecture yet — inventory and judge only.

---

## PHASE 3 — Pain-Point Mine Prompt (operators complaining, isolated from vendor copy)

> Inputs: `phase0_scope.md`. (Deliberately NOT given the feature files — pain points must come from operator complaints, not from what tools claim to solve.)
>
> You are mining **real, expressed pain points** about On-premises Data Gateway monitoring and performance from community and social sources. Sources to prioritize: reddit.com (r/PowerBI, r/MicrosoftFabric, r/dataengineering), x.com/Twitter, Power BI Community forums, Microsoft Q&A, Stack Overflow, Fabric community blogs' comment sections, and LinkedIn posts where accessible.
>
> **Rules:**
> - Only count pain expressed by an actual operator/user. Vendor marketing and "here's why our product is great" posts do NOT count as pain points.
> - Each pain point: verbatim or close-paraphrase quote + source URL + date + platform.
> - Cluster raw complaints into themes (e.g., "no query-level attribution," "refresh fails with opaque gateway errors," "no fleet/multi-gateway view," "PerfMon setup is manual and brittle," "logs are huge and unparseable," "alerting is nonexistent," "spooler disk-spill surprises," "can't correlate gateway load to specific reports/users").
>
> **For each theme produce:** theme name | frequency/intensity (how often + how angry) | representative quotes (2–4) with sources | root cause `[Inference]` | which Phase-0 job-to-be-done it maps to.
>
> Rank themes by a **Pain Score** = frequency × severity × how poorly current tools address it. Confirm or refute the Phase-0 known-gap hypotheses with evidence.
>
> Output `phase3_painpoints.md`: ranked pain themes, evidence, and an explicit "Top 5 unmet needs" list that the new tool must win on.

---

## PHASE 4 — Synthesize Prompt (dossier + architecture + starter code)

> Inputs: `phase0_scope.md`, `phase1_sources.md`, `phase2_features.md`, `phase3_painpoints.md`.
>
> You are the principal solution architect. Produce the three final deliverables. Be brutally honest — if a "best" feature isn't worth building, say so; if a pain point can't be solved with available signals, say so.
>
> **Deliverable A — Research Dossier (`phase4_dossier.md`).**
> Synthesize Phases 1–3 into one decision-grade document: the qualified source landscape, the consolidated best-of-breed feature set, the ranked operator pain points, and the explicit map of "best feature → which pain it solves." Call out the white-space: features no existing tool offers that the pain data says are needed. Include a "what NOT to build" section.
>
> **Deliverable B — Architecture & Build Spec (`phase4_architecture.md`).**
> Design the new tool for THIS stack: Microsoft Fabric / OneLake, Python + PySpark, PowerShell for gateway-side collection, Delta/medallion architecture, Power BI report layer.
> Include: (1) signal-ingestion layer (which collectors pull which signals — PowerShell cmdlets, PerfMon, log parsing, REST APIs, GatewayPerformanceMonitoring logs); (2) bronze/silver/gold Delta model with table schemas; (3) processing layer (Fabric notebooks / PySpark transforms); (4) the analytics/semantic model + key DAX measures; (5) the report/alerting layer and how it answers each Phase-0 job-to-be-done; (6) a feature-to-component traceability table proving every crown-jewel feature and top pain point has a home; (7) deployment, scheduling, and security/credential model; (8) risks, `[Assumption]`s, and explicit open questions. Provide a phased build roadmap (MVP → v1 → v2) tied to pain-point priority.
>
> **Deliverable C — Working Starter Code (`/starter/`).**
> Scaffold a runnable starting point consistent with Deliverable B: repo/folder structure; a PowerShell gateway-signal collector (real cmdlets/counters from Phase 2, marked `[Unverified]` where not confirmed); a Python/PySpark bronze→silver ingestion+parse notebook with the Delta schemas; at least one gold-layer aggregation and example DAX measures; config and credential-handling stubs; and a README mapping each module to its feature and pain-point origin. Reuse the best extracted code patterns from Phase 2 — cite their source in comments. Mark anything not verified to run as `[Unverified]`.
>
> End with a one-page executive summary: what we're building, why it beats the existing top sources, the top 3 risks, and the immediate next 3 actions.

---

## Operating notes for the human running this
- After Phase 1, manually eyeball the coverage matrix. If a Phase-0 signal has zero sources, that's your highest-value differentiator — flag it for the model.
- Keep Phase 3 firewalled from the feature files. The moment the model sees what tools *claim*, it starts inventing pain that conveniently matches. Isolation keeps the pain data honest.
- The traceability table in Deliverable B is the single most important artifact — it's the proof that the build is grounded in evidence, not in the model's pattern-completion instinct.
