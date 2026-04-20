# Jarvis Gemini Contract Runbook

## Purpose

This runbook documents the canonical engine-based `/jarvis/analyze` flow, the required Gemini environment variables, and the expected startup and verification path.

## Environment Contract

Set these variables in the engine environment:

- `GOOGLE_CLOUD_PROJECT`: the Google Cloud project that owns the Vertex AI / Gemini usage.
- `GOOGLE_CLOUD_LOCATION`: the Vertex AI region, such as `us-central1`.
- `JARVIS_GEMINI_MODEL`: the Gemini model name used by the Jarvis snapshot flow, such as `gemini-2.5-flash`.

Local development can use Application Default Credentials created with `gcloud auth application-default login`.
Production should use the credential mechanism provided by the engine host or deployment platform.
Do not rely on an interactive browser login in non-dev environments.

## Canonical Request Path

The dashboard should call the engine proxy, and the engine should own the public snapshot contract.

- Frontend helper: `dashboard/lib/api.ts`
- Dashboard proxy: `dashboard/app/api/engine/[...path]/route.ts`
- Backend route: `engine/main.py` via the Jarvis router or analysis router
- Service layer: `engine/services/jarvis_analysis.py`

## Startup Flow

1. Export the required Google Cloud environment variables before starting the engine.
2. Authenticate locally with ADC only when developing on a workstation.
3. Start the engine using the repository's canonical engine startup path.
4. Open the dashboard and issue a Jarvis analysis request against `/jarvis/analyze`.

## Verification Flow

Run the verification steps in this order:

1. Confirm the engine starts cleanly with the Jarvis route mounted.
2. Verify `/jarvis/analyze` returns a successful response for a valid symbol such as `SPY`.
3. Verify invalid symbols or malformed input return a client error.
4. Confirm the dashboard proxy reaches the engine endpoint.
5. Run the project TypeScript build or type-check step for the dashboard.

## Operational Notes

- Keep the Flask sidecar, if present, treated as a temporary compatibility path rather than the canonical product runtime.
- Prefer the engine route for all new work so the dashboard and backend stay aligned.
- If the Gemini model or region changes, update both this runbook and the env examples together.
