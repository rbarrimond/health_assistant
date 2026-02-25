# Health Assistant API Specifications

This directory contains the OpenAPI specifications for the Health Assistant API.

## Files

### `openapi.yaml` (Semantic/Read API)

- **Purpose**: Read-only endpoints for ChatGPT Actions integration
- **Operations**: 10 endpoints (within ChatGPT's 30-operation limit)
- **Scope**: Agent context, planning, workouts, rollups, analysis, physiometrics
- **Auth**: Function key required for most endpoints
- **Use Case**: Primary spec for GPT Actions configuration

### `openapi.operations.yaml` (Operations/Admin API)

- **Purpose**: Full API surface including admin/write operations
- **Operations**: 20+ endpoints
- **Scope**: All semantic endpoints + config, ingestion, OAuth flows, webhooks
- **Auth**: Function key required for most endpoints
- **Use Case**: Internal documentation, admin tooling, full API reference

## Why Two Specs?

ChatGPT Actions has a limit of 30 operations per OpenAPI specification. The two specs serve different purposes:

- **openapi.yaml**: Semantic/read endpoints optimized for GPT Actions (17 operations)
- **openapi.operations.yaml**: Administrative/operational endpoints (17 operations)

The specs are **independent** with minimal overlap (only `/api/health` appears in both). Each maintains only the schemas required by its endpoints, avoiding unnecessary duplication.

## Endpoint Categorization

### Semantic/Read (openapi.yaml)

- `GET /api/agent/context` - Agent memory context
- `GET /api/planning/context` - Planning decisions
- `GET /api/workouts` - List workouts
- `GET /api/workouts/{workout_id}` - Workout detail
- `GET /api/workouts/{workout_id}/laps/{lap_index}` - Lap detail
- `GET /api/rollups/weekly` - Weekly summaries
- `GET /api/analysis/zones` - Zone distribution
- `GET /api/analysis/efficiency` - Efficiency trends
- `GET /api/physiometrics/current` - Current metrics
- `GET /api/physiometrics/history` - Body metrics trends

### Operations/Admin (openapi.operations.yaml)

Administrative and operational endpoints:

- `/api/health` - Health check (also in semantic spec)
- `/api/agent/preferences` - GET/POST user preferences
- `/api/agent/observations` - GET/POST training observations
- `/api/agent/observations/{observation_id}` - PATCH observation status
- `/api/physiometrics/update` - POST metric updates
- `/api/config/*` - Configuration endpoints (reload, update, history)
- `/api/process_fit` - POST FIT file ingestion
- `/api/onedrive/*` - OneDrive OAuth and sync
- `/api/withings/*` - Withings integration
- `/api/workouts/{workout_id}/recalculated` - Recalculated zones
- `/api/.well-known/ai-plugin.json` - Plugin manifest
- `/api/openapi.yaml` - Spec endpoint
- `/api/logo.svg` - Logo asset

## Usage

### ChatGPT Actions Setup

1. Navigate to your GPT configuration
2. Add Action → Import from URL
3. Use: `https://health.azure.barrimond.net/api/openapi.yaml`
4. Configure authentication with function key

### Internal Reference

Use `openapi.operations.yaml` for:

- Complete API documentation
- Admin tooling development
- Integration reference
- Postman/testing collections

## Version

Both specs share the same version number and are kept in sync with the deployed API.
