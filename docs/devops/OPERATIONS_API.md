# Operations API

Version: 3.1.0

This document describes admin, ingestion, and infrastructure endpoints for the Health Assistant system.

> **Note:** This document mirrors [`openapi.operations.yaml`](../../api_docs/openapi.operations.yaml). For GPT-facing endpoints, see [`../gpt/SEMANTIC_LAYER_API.md`](../gpt/SEMANTIC_LAYER_API.md).

---

## Healthcheck

```http
GET /api/health
```

Health check with dependency status.

**Response (200 OK):**

```json
{
  "status": "healthy",
  "timestamp": "2026-02-14T10:30:00+00:00",
  "storage": "connected"
}
```

---

## Admin Endpoints

### FIT File Ingestion

```http
POST /api/process_fit
Content-Type: application/json
```

Ingest a FIT file payload from OneDrive or other sources.

**Request Body:**

```json
{
  "athlete_id": "rob",
  "source_file_name": "activity_123.fit",
  "file_content_b64": "base64_encoded_fit_data...",
  "source_drive_id": "optional_drive_id",
  "source_item_id": "optional_item_id",
  "source_ctag": "optional_ctag",
  "source_quickxor_hash": "optional_hash",
  "source_modified_at_utc": "2026-01-15T10:00:00+00:00"
}
```

**Response (201 Created):**

```json
{
  "source_info": {
    "athlete_id": "rob",
    "source_file_name": "activity_123.fit",
    "ingested_at_utc": "2026-01-15T10:05:00+00:00"
  },
  "workout_id": "abc123",
  "sport": "Cycling",
  "start_time_utc": "2026-01-15T10:00:00+00:00",
  "duration_sec": 3600
}
```

**Use cases:**

- Manual FIT file upload
- OneDrive sync integration
- Batch ingestion workflows

---

### OneDrive Integration

#### Authorize OneDrive

```http
GET /api/onedrive/authorize?athlete_id=rob
```

Generate OneDrive OAuth authorization URL.

**Response:**

```json
{
  "authorization_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?...",
  "athlete_id": "rob"
}
```

#### OneDrive Callback

```http
GET /api/onedrive/callback?code=...&state=...
```

OAuth callback endpoint (handled automatically by Azure).

#### OneDrive Sync

```http
POST /api/onedrive/sync
Content-Type: application/json
```

Trigger manual OneDrive folder sync and FIT file ingestion.

**Request Body (optional):**

```json
{
  "athlete_id": "rob",
  "force": false
}
```

**Response (202 Accepted):**

```json
{
  "status": "accepted",
  "message": "OneDrive sync queued for background processing",
  "athlete_id": "rob"
}
```

---

### Configuration Management

#### Update Configuration

```http
POST /api/config/update
Content-Type: application/json
```

Update physiometrics configuration (FTP, LTHR, HR/power zone basis) with optional
effective-date semantics and extensible athlete metadata.

**Request Body:**

```json
{
  "heart_rate": {
    "basis": "LTHR",
    "lthr_bpm": 175,
    "hr_max_bpm": 195,
    "resting_hr_bpm": 52
  },
  "power": {
    "ftp_watts": 285
  }
}
```

**Request Body (with effective date + athlete metadata):**

```json
{
  "as_of": "2026-03-02",
  "heart_rate": {
    "basis": "LTHR",
    "lthr_bpm": 175,
    "hr_max_bpm": 195,
    "resting_hr_bpm": 52
  },
  "power": {
    "ftp_watts": 285
  },
  "athlete_info": {
    "home_timezone": "America/New_York",
    "nickname": "rob"
  },
  "gear": {
    "favorite_bike": "Tarmac"
  }
}
```

Notes:

- `as_of` is optional and maps to Physiometrics effective date (`YYYY-MM-DD`).
- `athlete_info.home_timezone` is the preferred operational timezone source for weekly rollups.
- Existing payloads containing only `heart_rate` and `power` remain valid.

**Response (200 OK):**

```json
{
  "status": "success",
  "message": "Configuration saved to Azure Table Storage",
  "updated_at_utc": "2026-01-20T10:30:00+00:00",
  "as_of": "2026-03-02",
  "heart_rate": {...},
  "power": {...},
  "athlete_info": {
    "home_timezone": "America/New_York",
    "nickname": "rob"
  },
  "gear": {
    "favorite_bike": "Tarmac"
  }
}
```

#### Reload Configuration

```http
POST /api/config/reload
```

Force reload of athlete configuration from storage.

**Response:**

```json
{
  "status": "success",
  "message": "Configuration reloaded from disk",
  "heart_rate": {...},
  "power": {...}
}
```

#### Configuration History

```http
GET /api/config/history?limit=10
```

Retrieve configuration change history.

**Query Parameters:**

- `limit` (optional): Max records to return (default 10, max 50)

**Response:**

```json
{
  "status": "success",
  "count": 2,
  "history": [
    {
      "updated_at_utc": "2026-01-20T10:30:00+00:00",
      "heart_rate": {...},
      "power": {...}
    }
  ]
}
```

---

### Physiometrics Update

```http
POST /api/physiometrics/update
Content-Type: application/json
```

Update physiometric values (single metric or bulk partial update).

**Request Body (Single Metric):**

```json
{
  "athlete_id": "rob",
  "metric": "cycling_vo2max_ml_kg_min",
  "value": 52.3,
  "effective_date": "2026-01-19",
  "source": "chatgpt"
}
```

**Request Body (Bulk Update):**

```json
{
  "athlete_id": "rob",
  "metrics": {
    "weight_kg": 75.2,
    "cycling_vo2max_ml_kg_min": 52.3
  },
  "effective_date": "2026-01-19",
  "source": "chatgpt"
}
```

**Response:**

```json
{
  "status": "success",
  "athlete_id": "rob",
  "metric": "cycling_vo2max_ml_kg_min",
  "value": 52.3,
  "effective_date": "2026-01-19",
  "source": "chatgpt",
  "updated_at_utc": "2026-01-19T14:32:15+00:00"
}
```

---

## Workout Utilities

### Recalculated Workout Zones (Read-only)

```http
GET /api/workouts/{workout_id}/recalculated?ftp_watts=285&lthr_bpm=175
```

Returns a placeholder response today. Intended for future recalculated zone summaries.

## Withings Integration (Internal)

### Authorize Withings

```http
GET /api/withings/authorize?athlete_id=rob
```

Generate Withings OAuth authorization URL.

### Withings Callback

```http
GET /api/withings/callback?code=...&state=...
```

OAuth callback endpoint (handled automatically by Azure).

### Withings Webhook

```http
POST /api/withings/webhook
Content-Type: application/x-www-form-urlencoded

userid=12345&appli=1&startdate=1705622400&enddate=1705622500
```

Internal endpoint called by Withings servers when new measurements are available.

**Processing:**

- Validates webhook payload
- Checks deduplication (avoids processing same webhook twice)
- Queues for async processing
- Returns HTTP 200 immediately (fast acknowledgment)
- Background worker fetches and stores measurement data

**Supported Measurements:**

- Weight (kg)
- Fat mass (kg)
- Muscle mass (kg)
- Bone mass (kg)
- Body fat percentage
- Visceral fat index
- Metabolic age (years)

---

## Plugin Assets

### ChatGPT Plugin Manifest

```http
GET /api/.well-known/ai-plugin.json
```

Returns the ChatGPT plugin manifest for GPT Actions integration.

### OpenAPI Spec

```http
GET /api/openapi.yaml
```

Returns the semantic/read-only OpenAPI specification (GPT-facing endpoints only).

For the full operations spec including admin endpoints, see [`openapi.operations.yaml`](../../api_docs/openapi.operations.yaml).

### Logo

```http
GET /api/logo.svg
```

Returns the Health Assistant logo (SVG format).

---

## Testing

```bash
# Test FIT ingestion
curl -X POST http://localhost:7071/api/process_fit \
  -H "Content-Type: application/json" \
  -d '{"athlete_id":"rob","source_file_name":"test.fit","file_content_b64":"..."}'

# Test OneDrive sync
curl -X POST http://localhost:7071/api/onedrive/sync \
  -H "Content-Type: application/json" \
  -d '{"athlete_id":"rob"}'

# Test config update
curl -X POST http://localhost:7071/api/config/update \
  -H "Content-Type: application/json" \
  -d '{"heart_rate":{"basis":"LTHR","lthr_bpm":175},"power":{"ftp_watts":285}}'
```

---

## Deployment

See [DEPLOYMENT.md](./DEPLOYMENT.md) for Azure Functions deployment procedures.

## Monitoring

See [MONITORING.md](./MONITORING.md) for monitoring strategy and Power BI dashboards.
