# Operations API Playbook

Version: 4.9.0

This document explains operational usage patterns for admin, ingestion, and integration endpoints.

> Document role: Workflow and runbook guidance.
>
> Contract authority: Exact paths, methods, parameters, payload schemas, auth, and canonical examples are defined in [openapi.operations.yaml](../../api_docs/openapi.operations.yaml).
>
> GPT-facing semantic endpoints are documented in [SEMANTIC_LAYER_API.md](../gpt/SEMANTIC_LAYER_API.md) with contracts in [openapi.yaml](../../api_docs/openapi.yaml).

---

## Usage Pattern Map

- Ingestion and data import: FIT processing and source sync orchestration
- Config and baseline management: physiometrics/config lifecycle operations
- Weekly aggregation operations: rollup computation and backfill runs
- Integration lifecycles: OneDrive and Withings authorization, callback, and sync operations
- Async operations and platform assets: queue status and plugin asset delivery

For endpoint-level contracts in each family, use [openapi.operations.yaml](../../api_docs/openapi.operations.yaml).

---

## Operational Workflows

### 1. FIT Ingestion Workflow

Use when importing FIT files manually or from external sync systems.

1. Ensure source metadata is available (athlete, source filename, source system identifiers).
2. Submit ingestion through the FIT processing endpoint.
3. Validate ingestion outcome and capture identifiers for downstream traceability.
4. Confirm data appears in semantic read endpoints and weekly rollups as expected.

Operational intent:

- Keep ingestion idempotent where possible.
- Preserve source provenance fields for replay/debug workflows.
- Prefer async-safe orchestration during batch imports.

### 2. OneDrive Sync Workflow

Use for OAuth setup and recurring synchronization of OneDrive FIT sources.

1. Generate authorization URL and complete callback once per athlete/source connection.
2. Trigger manual sync for on-demand hydration or recovery operations.
3. Use reset operation only when delta cursor corruption or source drift is suspected.
4. Validate sync outcomes via operation status and downstream workout availability.

Operational intent:

- Treat reset as an exceptional remediation step.
- Avoid repeated forced sync unless troubleshooting stale source state.

### 3. Weekly Rollup Compute Workflow

Use to force persisted weekly summaries for one or more athletes.

1. Select compute scope (single athlete, list, or broader run).
2. Trigger weekly rollup compute operation.
3. Inspect per-athlete outcomes and partial success results.
4. Re-run failures with narrowed scope and source diagnostics.

Operational intent:

- This endpoint is compute-oriented, not dependency hydration.
- Dependency hydration is handled by planning-context read-repair and timer workflows.

### 4. Config and Physiometrics Update Workflow

Use for baseline or metadata changes that should affect downstream analytics.

1. Submit physiometrics/config update with intended effective-date semantics.
2. Confirm history and current projections reflect the update.
3. Validate downstream calculations for training-state and planning interpretations.

Operational intent:

- Preserve effective-date semantics; avoid ad-hoc backdating without audit context.
- Treat manual override values as explicit operator decisions.

### 5. Withings Integration Workflow

Use for OAuth onboarding and webhook-driven physiometric updates.

1. Complete authorization and callback flow.
2. Confirm webhook endpoint reachability and provider registration.
3. Validate webhook normalization for both GET and form POST transport shapes.
4. Monitor deduplication and async processing health.

Operational intent:

- Keep webhook endpoint externally reachable per provider requirements.
- Maintain fast acknowledgment behavior with deferred processing.

---

## Runbook Notes

- Use [MONITORING.md](./MONITORING.md) for telemetry and error triage.
- Use [DEPLOYMENT.md](./DEPLOYMENT.md) for release/runtime procedures.
- Use [BACKENDS.md](./BACKENDS.md) for source ownership and integration behavior.

## Testing Guidance

Use your local/staging environment to execute operational workflow checks.

- Verify auth and callback paths for each integration.
- Validate ingestion and sync outcomes through semantic read endpoints.
- Validate weekly rollup compute outcomes, including partial-success handling.
- Prefer scripted smoke flows to ad-hoc one-off requests where possible.

For concrete request payloads and response examples, use [openapi.operations.yaml](../../api_docs/openapi.operations.yaml).
