# O-03 — Reproducible Build Baseline

**Parent product candidate:** `JARVIS-MPP-1.0` (#789 / GOV-01 #791)  
**Program:** O — Delivery & Engineering System  
**Phase:** Phase 0 / ISG-0 design  
**Safety class:** S0 document  
**State:** **DRAFT CURRENT-MASTER REFRESH — BOUNDED REPRODUCIBILITY, NOT BIT-FOR-BIT**  
**Observed repository baseline:** `master@6afe8970b8a588a3b67131d960fe47bee6fa40cf`  
**Current hosted-CI blocker:** O-CI-001 / #790  
**Depends on:** O-02 verification matrix

## 1. Decision

JARVIS will define a reproducible **bounded build** from version-controlled manifests, lockfiles, exact Git identity, and recorded tool/runtime metadata.

This ADR does **not** claim cryptographic or bit-for-bit reproducibility. The Python dependency set is requirements-based rather than a fully hash-locked transitive environment, GitHub-hosted runner images can change, and broker/TWS/runtime state is external to the repository build.

No dependency upgrade is introduced by this document.

## 2. Current verified build identities

The following values were re-read from current `master` rather than copied from the older #774 baseline.

| Layer | Current bounded baseline |
|---|---|
| Repository identity | exact Git commit SHA + clean/dirty worktree state |
| Python | **3.12** in `.github/workflows/ci.yml` |
| Ruff | **0.8.0** explicitly installed by CI |
| Engine dependency manifest | `engine/requirements-core.txt` |
| Python cryptographic transitive lock | **not established by this ADR** |
| Dashboard Node | **22** in CI |
| Dashboard package manager | **pnpm 10.33.2** pinned in CI |
| Dashboard lock | `dashboard/pnpm-lock.yaml` with frozen-lockfile installation in canonical CI/build flow |
| Next.js declared range | `^15.3.0` in `dashboard/package.json` |
| React / React DOM declared range | `^19.0.0` |
| TypeScript declared range | `^5.8.3` |
| Vitest declared range | `^4.1.10` |
| Playwright declared range | `^1.61.1` |
| Hosted CI | GitHub Actions Ubuntu runners when runner allocation succeeds |

Package manifest ranges are **not** rewritten as exact installed versions. The frozen pnpm lockfile is the dependency-resolution authority for a reproducible dashboard install.

## 3. Canonical engine bootstrap

From a clean clone/worktree at the candidate SHA:

```bash
python -m venv .venv
# activate the environment for the current OS
python -m pip install --upgrade pip
pip install -r engine/requirements-core.txt
```

The exact CI commands in `.github/workflows/ci.yml` are authoritative over copied documentation snippets when they differ.

Current CI also pins Ruff separately at `ruff==0.8.0`.

Because `requirements-core.txt` is not a complete hash-locked resolver output, the Python environment is bounded by manifest/version constraints and the package index state, not cryptographically frozen.

## 4. Canonical dashboard bootstrap

Canonical verification uses the repository's Node/pnpm versions and frozen lockfile semantics:

```bash
cd dashboard
corepack enable
pnpm install --frozen-lockfile
```

The repository CI currently uses Node 22 and pinned pnpm 10.33.2.

Required dashboard evidence is determined by O-02 and current workflow definitions; it includes type/unit/build slices appropriate to the safety class and V3 operator E2E when the work claims operator behavior.

## 5. Build receipt contract

Every release-candidate or safety-relevant build receipt should record:

```text
commit_sha
repository_dirty: true|false
branch/ref when useful
os / runner image or host identity
python --version
pip --version
ruff --version
node --version
pnpm --version
engine manifest hash
dashboard package.json hash
dashboard lockfile hash
workflow/build definition hash or commit
commands/checks executed
result and verification rung
artifacts and hashes where retained
known limitations
```

Necessary environment-variable **names** or mode classifications may be recorded. Secret values, broker credentials, API keys, and unredacted account identifiers must never be embedded in receipts.

## 6. Determinism boundaries

### Bounded by this ADR

- exact repository source SHA;
- clean/dirty worktree declaration;
- version-controlled CI commands;
- Python major/minor requested by CI;
- explicitly pinned CI tooling such as Ruff;
- Node/pnpm versions requested by CI;
- dashboard dependency graph under the frozen lockfile;
- manifest/lockfile content hashes;
- no intentional dependency upgrade inside O-03.

### Not guaranteed

- Python transitive package hashes across future index states;
- GitHub Ubuntu runner bit-for-bit image identity across time;
- external package-index availability;
- native OS libraries outside repository control;
- local Windows/TWS/Gateway versions or loaded runtime state;
- market/research data unless separately content-addressed;
- broker account/session state;
- secrets/credentials;
- exact installed dashboard version inferred merely from a semver range without the lockfile.

These limitations are part of the evidence contract, not hidden caveats.

## 7. O-CI-001 boundary

A reproducible build definition can exist while hosted execution is unavailable.

Current GitHub Actions runner-allocation failures tracked in #790 are classified **CI-INFRA / NO VALIDATION EXECUTED** when jobs receive no runner and execute no steps.

That infrastructure state:

- does not invalidate the manifest/build design by itself;
- does not prove the candidate builds;
- cannot be counted as V1/V3 evidence;
- must not be worked around by weakening required checks.

Once runner execution is restored, exact-head jobs must be rerun and their actual outputs recorded.

## 8. Rebuild protocol

A bounded reproducibility check is:

1. start from a clean clone/worktree at the receipt SHA;
2. verify repository cleanliness and expected branch/ref;
3. hash the engine manifest and dashboard package/lock files;
4. bootstrap with the canonical manifests/tool versions;
5. run the required O-02 rung(s);
6. record tool/runtime metadata;
7. compare with the original receipt;
8. classify differences as source, dependency, runner/OS, data, or runtime drift;
9. do not label the build reproduced if a required rung did not execute.

## 9. Future hardening work package

After the Phase-0 baseline is adopted, a separate reviewable work package may:

1. generate a resolver-produced Python constraints/lock artifact;
2. add package hashes where supported;
3. pin release-verification Python patch versions;
4. attest/cache build artifacts by SHA;
5. record exact runner-image identity;
6. generate an SBOM where deployment scope warrants it;
7. pin browser/runtime artifacts for canonical Playwright release verification;
8. define supported TWS/IB Gateway versions for real PAPER and future canary environments;
9. define offline/mirrored dependency recovery if supply-chain availability becomes operationally important.

These changes must not be mixed with routine dependency upgrades merely to claim reproducibility.

## 10. Workflow governance

Workflow files are part of the build system. Changes to `.github/workflows/**` must eventually be governed by GOV-02/O-05 controls and should:

- use minimal token permissions;
- avoid privileged execution of untrusted PR code;
- preserve or strengthen the verification ratchet unless an explicit reviewed exception exists;
- document interpreter/tool-version changes;
- keep CI-infrastructure failure distinct from repository test failure;
- bind required evidence to exact heads.

## 11. Relationship to stale #774

This is the current-master refresh of O-03 from #774. It deliberately corrects stale tool-version claims rather than copying them.

Notable current facts include Node 22, pnpm 10.33.2, Python 3.12, Ruff 0.8.0, and current `dashboard/package.json` ranges for Next/React/TypeScript/Vitest/Playwright.

The older #774 O-03 remains historical provenance once this refresh is independently reviewed; it should not be treated as the current build identity.

## 12. Acceptance criteria

- [x] Exact source SHA/worktree identity is part of build identity.
- [x] Current CI Python/Node/pnpm/Ruff facts were re-read from master.
- [x] Current dashboard package ranges were re-read from master.
- [x] Frozen dashboard lockfile semantics are explicit.
- [x] Python hash-lock limitation is explicit.
- [x] Build receipt fields are defined.
- [x] Secrets are excluded.
- [x] CI-infrastructure failure is separated from build/test evidence.
- [x] No dependency upgrade was introduced.
- [ ] GOV-01 parent hierarchy explicitly adopted/revised.
- [ ] O-CI-001 restored and current exact-head verification executed where required.
- [ ] Human governance review marks O-03 `ADOPTED` with effective SHA.

## 13. Decision status

**Draft decision:** BOUNDED REPRODUCIBILITY BASELINE READY FOR REVIEW.  
**Bit-for-bit/cryptographic reproducibility claim:** NOT MADE.  
**Production/PAPER/LIVE/capital authorization:** NONE.
