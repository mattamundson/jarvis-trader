# GCP Cloud Run Trigger Repair — Runbook

**Status:** BLOCKED on GCP console access (Amo). Non-blocking for merges (check is not in required list).
**Discovered:** 2026-08-16 during PR backlog wave.

## Symptom
Check `cloudrun-jarvis-trader-git-europe-west1-mattamundson-jarvis-yjl (jarvis-trading-493009)` fails on **every** PR branch within ~25s:
- Build step `Pull` → SUCCESS (1.2s)
- Build step `Build` → **FAILURE (672ms)** — config validation, not a real build
- Steps `Push` / `Deploy` → never reached (QUEUED)

Fails identically on all branches (verified on #487, #690, others), including after forced CI re-runs → it is a trigger/config problem, not a code problem.

## Facts
- **No `cloudbuild.yaml` in the repo** (checked `git ls-tree origin/master | grep -i cloudbuild` → empty). The build config lives entirely in the GCP trigger's inline config.
- **Project IDs seen in logs:** `jarvis-trading-493009` (trigger URL) and `572648909908` (build URL param) — likely project number vs ID of the same project.
- **Trigger ID:** `a0fbe173-744b-45d2-82bc-9bd49f41b2b7`
- **Region:** `europe-west1`
- **Latest failing build:** `627c9477-7cde-4cc2-a866-fbf8bfebbbf6` (2026-08-16 11:56:35-07:00)
- Check-run output (via `gh api repos/mattamundson/jarvis-trader/commits/<sha>/check-runs`) confirms step table above.

## What to check in the console (in order)
1. **Open the trigger:** https://console.cloud.google.com/cloud-build/triggers/edit/a0fbe173-744b-45d2-82bc-9bd49f41b2b7?project=jarvis-trading-493009
2. **View the failed build log:** https://console.cloud.google.com/cloud-build/builds;region=europe-west1/627c9477-7cde-4cc2-a866-fbf8bfebbbf6?project=jarvis-trading-493009
   - The `Build` step error message (fails in 672ms) will state the exact config problem — commonly:
     - Missing/invalid Dockerfile path or image name
     - Bad build args or env substitution
     - Region/service-name mismatch (`cloudrun-jarvis-trader-git-europe-west1...` service must exist in `europe-west1`)
     - Quota/permission: Cloud Build SA missing `roles/run.admin` or `roles/iam.serviceAccountUser`
3. **If the error is Dockerfile/context:** confirm the trigger's "source → build config" points at a Dockerfile that exists in the repo (or inline config that resolves).
4. **If the error is permissions:** ensure the Cloud Build service account has Cloud Run Admin + Service Account User on the project.
5. **If the error is quota:** check Quotas page for Cloud Build concurrent builds / Cloud Run.

## After repair
- Force one test run: push a noop commit to any open PR branch (or use the trigger's "Run trigger" button in console).
- Confirm the check goes green on the next PR CI cycle.
- Optionally add the check back as REQUIRED in branch protection once it's stable (it was never required; leaving it non-required is also fine — merges don't wait on it).

## Notes for agents
- `gcloud` CLI is **broken from git-bash on this host** (MSYS path mangling: `python3.12.exe: can't open file 'C:\c\Program Files...'`). Workarounds: use `gh api` for check-run summaries, GCP console for full logs, or PowerShell with `gcloud.cmd`.
- This runbook is referenced from the 2026-08-16 PR wave handoff.
