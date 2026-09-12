# O-03 — Reproducible Build Baseline

**Plan:** JARVIS-MIP-1.0  
**Program:** O — Delivery, Verification & Governance  
**Phase:** MIP-0  
**Safety class:** S0 document  
**State:** **DRAFT COMPLETE — BOUNDED REPRODUCIBILITY, NOT BIT-FOR-BIT LOCKED**  
**Depends on:** O-01 CI baseline, O-02 verification matrix  
**Required for:** ISG-0 and implementation ratchet

## 1. Decision

JARVIS will establish a reproducible **bounded build** baseline using the versions and lock artifacts already exercised by CI. Phase 0 will not claim bit-for-bit or supply-chain-complete reproducibility because the Python dependency set is requirements-based rather than hash-locked.

No dependency upgrades are part of this work package.

## 2. Current build identities

Observed from the current CI/build files:

| Layer | Baseline |
|---|---|
| Python major/minor | 3.12 |
| Engine dependency manifest | `engine/requirements-core.txt` |
| Python cryptographic lock | **Not present / not established by this WP** |
| Dashboard Node | 22 in CI |
| Dashboard package manager | pnpm 10 in CI |
| Dashboard lock | `dashboard/pnpm-lock.yaml` (`lockfileVersion: 9.0`) |
| Dashboard framework | Next.js 15.3.4 |
| React | 19.x |
| TypeScript | 5.x |
| Vitest | 4.0.18 |
| Playwright | 1.58.2 |
| Hosted CI | GitHub Actions Ubuntu runners |

The exact Git commit SHA remains part of every build identity.

## 3. Canonical clean-engine bootstrap

From repository root:

```bash
python -m venv .venv
. .venv/bin/activate          # Windows equivalent: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r engine/requirements-core.txt
```

The CI-equivalent verification commands are defined by `.github/workflows/ci.yml`; the workflow file is authoritative over copied command snippets when they differ.

Because `requirements-core.txt` is not a hash-locked resolver output, a later package index state can theoretically resolve a different transitive environment. Therefore this is a bounded reproducibility contract, not a cryptographic one.

## 4. Canonical clean-dashboard bootstrap

```bash
cd dashboard
corepack enable
pnpm install --frozen-lockfile
```

CI uses Node 22 and pnpm 10. The frozen lockfile is mandatory for canonical verification.

Required build evidence includes the production Next.js build plus the dashboard verification slices defined in O-02/CI.

## 5. Build receipt

Every release-candidate or safety-relevant verification receipt should record:

```text
commit_sha
repository_dirty: true|false
os / runner image
python --version
pip --version
node --version
pnpm --version
engine manifest hash
dashboard lockfile hash
build/test command identifiers
result
artifact hashes where artifacts are retained
```

Environment variable **names** necessary to reproduce the mode may be recorded. Secret values must never be embedded in the receipt.

## 6. Determinism boundaries

### Deterministic or bounded by this WP

- repository source at an exact commit;
- dashboard dependency graph under frozen `pnpm-lock.yaml`;
- CI interpreter major/minor and Node/pnpm major versions;
- verification commands under version control;
- no intentional dependency upgrade during O-03.

### Not yet guaranteed

- Python transitive dependency hashes;
- GitHub-hosted runner image bit-for-bit identity across time;
- external package-index availability;
- OS-level native libraries outside the repository manifests;
- broker/TWS version or local operator machine state;
- market-data/research data unless separately content-addressed;
- secrets or credentials.

Those boundaries must be stated rather than hidden.

## 7. Recommended hardening after ISG-0

Create a separate, reviewable work package to:

1. generate a Python resolver lock/constraints artifact from the intended dependency source;
2. include hashes where the selected tooling supports them;
3. record the exact Python patch version used for release verification;
4. cache or attest build artifacts by SHA;
5. record runner-image identity in release receipts;
6. add software-bill-of-materials generation if deployment scope warrants it;
7. pin browser binaries for canonical Playwright release verification;
8. define TWS/IB Gateway version compatibility for real broker PAPER/canary environments.

This hardening must not be conflated with routine package upgrades.

## 8. Rebuild protocol

A reproducibility check is:

1. start from a clean clone at the receipt SHA;
2. confirm no uncommitted files affect execution;
3. bootstrap engine/dashboard using canonical manifests;
4. run the required O-02 rung(s);
5. compare dependency/build metadata with the original receipt;
6. classify any mismatch as source, dependency, environment, data or runtime drift;
7. do not label the build reproduced if a required rung was skipped.

## 9. CI workflow governance

Workflow files are themselves part of the build system. Changes to `.github/workflows/**` must:

- receive O-05 governance review;
- use minimal permissions;
- avoid privileged execution of untrusted PR code;
- preserve the verification ratchet unless the weakening is explicitly approved and documented;
- record why interpreter/tool-version changes are necessary.

## 10. Acceptance criteria

- [x] Canonical engine/dashboard bootstrap paths are documented.
- [x] Current interpreter/tooling versions are captured from repository CI/manifests.
- [x] Dashboard frozen-lock requirement is explicit.
- [x] Python lock limitation is explicit.
- [x] Build receipt fields are defined.
- [x] Secrets are excluded from receipts.
- [x] No dependency upgrades were introduced.
- [x] Future hardening is separated from Phase-0 baseline.
- [ ] O-01 current-master required CI receipt is finalized.
- [ ] PR #768 adopted.

## 11. Decision status

**Draft decision:** BOUNDED REPRODUCIBILITY BASELINE ACCEPTED FOR REVIEW.  
**Bit-for-bit reproducibility claim:** NOT MADE.  
**Production authorization:** none.
