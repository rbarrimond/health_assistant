# Backend Integrations

This document describes the external data source integrations for the Health Assistant system.

## Overview

The Health Assistant supports multiple backend integrations to automatically collect training and physiological data:

| Backend                  | Status       | Data Types                   | Protocol                       |
| ------------------------ | ------------ | ---------------------------- | ------------------------------ |
| **HealthFit (OneDrive)** | Production   | FIT workout files            | OAuth (delegated) + Timer/HTTP |
| **Garmin**               | Production   | FIT workout files            | OAuth 2.0 (garth) + Timer/HTTP |

## HealthFit (OneDrive) Integration

### OneDrive Overview

The OneDrive backend ingests HealthFit FIT exports stored in OneDrive Personal using delegated OAuth. It is a passive backend (no Power Automate): the function app pulls files on a timer or via an HTTP trigger.

**Data Flow:**

```text
OneDrive Personal (/Apps/HealthFit)
    ↓
OAuth 2.0 (delegated)
    ↓
Azure Function (Timer + HTTP sync via Microsoft Graph)
    ↓
FIT Parser → Metrics → Azure Table Storage
```

### Prerequisites

- OneDrive Personal account
- HealthFit exports stored in `/Apps/HealthFit` (or your chosen folder)
- Azure Function deployed with the OneDrive endpoints

### OneDrive Setup & Configuration

#### 1. Create Microsoft App Registration

1. Azure Portal → App registrations → New registration
2. Supported account types: **Accounts in any organizational directory and personal Microsoft accounts**
3. Redirect URI (web): `https://<FUNCTION_APP>.azurewebsites.net/api/onedrive/callback`
4. Create a **client secret**

Record the **Client ID** and **Client Secret**.

#### 2. Configure OneDrive Environment Variables

Set these in your Function App configuration:

```bash
ONEDRIVE_CLIENT_ID=your_client_id_here
ONEDRIVE_CLIENT_SECRET=your_client_secret_here
ONEDRIVE_REDIRECT_URI=https://<FUNCTION_APP>.azurewebsites.net/api/onedrive/callback
ONEDRIVE_SCOPES="Files.ReadWrite offline_access"
ONEDRIVE_FOLDER_PATH=/Apps/HealthFit
ONEDRIVE_SYNC_LOOKBACK_DAYS=30
```

#### 3. Authorize OneDrive

Generate an authorization URL:

```bash
curl "https://<FUNCTION_APP>.azurewebsites.net/api/onedrive/authorize?athlete_id=rob&code=<FUNCTION_KEY>"
```

Open the returned `authorization_url` in a browser and sign in. The user grants delegated scopes during this consent step (no pre-grant required in Terraform). On success, the callback stores refresh tokens in `OneDriveTokens`.

#### 4. Run Sync

Manual sync (HTTP):

```bash
curl -X POST "https://<FUNCTION_APP>.azurewebsites.net/api/onedrive/sync?code=<FUNCTION_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"days": 30, "athlete_id": "rob", "async": true}'
```

By default the endpoint runs asynchronously and returns a 202 digest. Set `async=false` to block and wait for results.

Automatic sync (Timer):

- Runs every 10 minutes
- Uses Microsoft Graph delta query with persisted delta token state
- Uses `ONEDRIVE_SYNC_LOOKBACK_DAYS` by default

Lookback filtering uses the workout date parsed from the filename (YYYY-MM-DD) when available. If no date is found, it falls back to OneDrive `lastModifiedDateTime`.

### OneDrive API Endpoints

#### GET /api/onedrive/authorize

Generates an OAuth authorization URL for a specific athlete.

**Query Parameters:**

- `athlete_id` (optional) - Athlete identifier (defaults to "rob")
- `state` (optional) - Custom state token (auto-generated if omitted)

**Response:**

```json
{
  "authorization_url": "https://login.microsoftonline.com/...",
  "athlete_id": "rob",
  "state": "..."
}
```

#### GET /api/onedrive/callback

OAuth callback endpoint (called by Microsoft after authorization).

**Query Parameters:**

- `code` - Authorization code from Microsoft
- `state` - State token (includes athlete_id)

**Response:**
HTML success page

#### POST /api/onedrive/sync

HTTP-triggered OneDrive sync.

**Auth:** Function-level (default)

**Request Body:**

```json
{
  "days": 30,
  "athlete_id": "rob",
  "async": true
}
```

**Response (async=true):**

```json
{
  "status": "queued",
  "athlete_id": "rob",
  "lookback_days": 30
}
```

**Response (async=false):**

```json
{
  "status": "success",
  "athlete_id": "rob",
  "file_count": 5,
  "workout_count": 5,
  "error_count": 0
}
```

#### POST /api/onedrive/sync/reset

Reset OneDrive delta cursor state so the next sync reseeds from Graph delta start.

**Auth:** Function-level

**Single athlete reset (recommended default):**

```bash
curl -X POST "https://<FUNCTION_APP>.azurewebsites.net/api/onedrive/sync/reset?code=<FUNCTION_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"athlete_id": "rob"}'
```

**Bulk reset (all athletes):**

```bash
curl -X POST "https://<FUNCTION_APP>.azurewebsites.net/api/onedrive/sync/reset?code=<FUNCTION_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"all": true}'
```

**Response (single):**

```json
{
  "status": "success",
  "scope": "single",
  "athlete_id": "rob",
  "reset_count": 1,
  "reset_applied": true,
  "reset_at_utc": "2026-03-15T10:00:00+00:00"
}
```

**Response (bulk):**

```json
{
  "status": "success",
  "scope": "bulk",
  "reset_count": 3,
  "reset_at_utc": "2026-03-15T10:00:00+00:00"
}
```

**Operational notes:**

- Reset clears only OneDrive delta cursor fields (`delta_token`, `delta_sync_state`, sync marker); OAuth credentials are preserved.
- First sync after reset runs in seed mode (`delta_link=None`) and persists a fresh delta cursor.
- Reseed can re-list historical files; ingestion idempotency prevents duplicate ingests when source/hash identity is unchanged.

### OneDrive Implementation Files

| File | Purpose |
| --- | --- |
| [onedrive_client.py](../../TrainingAnalyticsPlatform/integrations/onedrive_client.py) | Microsoft Graph OAuth + API calls |
| [onedrive_sync_handler.py](../../TrainingAnalyticsPlatform/handlers/onedrive_sync_handler.py) | OAuth + sync service |
| [function_app.py](../../function_app.py) | HTTP endpoints + timer trigger |
| [table_storage.py](../../TrainingAnalyticsPlatform/storage/table_storage.py) | Token storage + ingestion state |

### OneDrive Troubleshooting

| Issue | Likely Cause | Fix |
| --- | --- | --- |
| Authorization failed | Invalid client ID/secret/redirect URI | Verify app registration values |
| No tokens stored | Callback not completed | Complete authorize → callback flow |
| No files found | Wrong folder path | Verify `ONEDRIVE_FOLDER_PATH` and file location |

## Withings Integration

### Withings Overview

The Withings backend provides automatic synchronization of body composition and weight measurements from Withings smart scales and devices.

**Data Flow:**

```text
Withings Scale/Device
    ↓
Withings Cloud API
    ↓
OAuth 2.0 Authorization
    ↓
Webhook Notifications (on new measurement)
    ↓
Azure Function Endpoint (/api/withings/webhook)
    ↓
Azure Queue (withings-webhooks)
    ↓
Background Processor
    ↓
Fetch Measurements (Withings API)
    ↓
Azure Table Storage (Physiometrics)
```

### Supported Measurements

The integration captures the following body composition metrics:

- **Weight** (kg) - `TYPE_WEIGHT` (1)
- **Body Fat %** - `TYPE_FAT_RATIO` (6)
- **Fat Mass** (kg) - `TYPE_FAT_MASS` (8)
- **Muscle Mass** (kg) - `TYPE_MUSCLE_MASS` (76)
- **Bone Mass** (kg) - `TYPE_BONE_MASS` (88)
- **Visceral Fat Index** - `TYPE_VISCERAL_FAT` (123)
- **Metabolic Age** (years) - `TYPE_METABOLIC_AGE` (155)

### Withings Setup & Configuration

#### 1. Create Withings Developer Application

1. Go to [Withings Developer Portal](https://developer.withings.com/)
2. Create a new application
3. Set the redirect URI to: `https://<your-function-app>.azurewebsites.net/api/withings/callback`
4. Note your **Client ID** and **Client Secret**

#### 2. Configure Withings Environment Variables

Add the following to your Azure Function App Configuration:

```bash
WITHINGS_CLIENT_ID=your_client_id_here
WITHINGS_CLIENT_SECRET=your_client_secret_here
WITHINGS_REDIRECT_URI=https://<your-function-app>.azurewebsites.net/api/withings/callback
WITHINGS_WEBHOOK_URL=https://<your-function-app>.azurewebsites.net/api/withings/webhook
```

#### 3. Authorize User Access

Each athlete must authorize access to their Withings data:

1. **Generate Authorization URL:**

   ```bash
   curl "https://<your-function-app>.azurewebsites.net/api/withings/authorize?athlete_id=rob&code=<function-key>"
   ```

2. **User Authorization:**
   - Open the returned `authorization_url` in a browser
   - Sign in to Withings account
   - Grant permissions (user.metrics, user.info)
   - User will be redirected to callback endpoint

3. **Automatic Token Storage:**
   - OAuth tokens stored in `WithingsTokens` table
   - Webhook subscription automatically created
   - Access tokens auto-refresh when expired

### Withings API Endpoints

#### GET /api/withings/authorize

Generate OAuth authorization URL for a specific athlete.

**Query Parameters:**

- `athlete_id` (required) - Athlete identifier (e.g., "rob")

**Response:**

```json
{
  "authorization_url": "https://account.withings.com/oauth2_user/authorize2?...",
  "athlete_id": "rob",
  "state": "secure_state_token:rob",
  "instructions": "Open this URL in your browser to authorize Withings access"
}
```

#### GET /api/withings/callback

OAuth callback endpoint (called by Withings after authorization).

**Query Parameters:**

- `code` - Authorization code from Withings
- `state` - State token (includes athlete_id)

**Processing:**

1. Exchanges code for access/refresh tokens
2. Stores tokens in `WithingsTokens` table
3. Subscribes to webhook notifications
4. Returns success HTML page

#### POST /api/withings/webhook

Webhook endpoint for Withings notification callbacks.

**Request Body:**

```json
{
  "userid": "12345678",
  "appli": 1,
  "startdate": 1642000000,
  "enddate": 1642003600
}
```

**Processing:**

1. Validates request signature (optional)
2. Queues webhook data for async processing
3. Returns 200 OK immediately

**Background Processing:**

1. Retrieves access token (refreshes if expired)
2. Fetches measurements from Withings API
3. Stores in `Physiometrics` table with `data_source="withings"`

### Data Storage

Measurements are stored in the `Physiometrics` table with the following schema:

```python
{
  "PartitionKey": "rob",                    # athlete_id
  "RowKey": "2026-01-25|withings",          # effective_date + data_source
  "weight_kg": 75.5,
  "fat_mass_kg": 12.3,
  "muscle_mass_kg": 58.2,
  "bone_mass_kg": 3.1,
  "body_fat_pct": 16.3,
  "visceral_fat_index": 5,
  "metabolic_age_years": 28,
  "data_source": "withings",
    "Timestamp": "2026-01-25T08:30:00+00:00"
}
```

**Key Features:**

- **Per-source idempotency**: Same-day writes overwrite only that source's prior daily snapshot
- **Multi-source support**: `data_source` plus source-qualified row keys preserve same-day rows from different backends
- **Time series queries**: Easily retrieve trends over date ranges

### Withings Implementation Files

| File | Purpose |
| --- | --- |
| [withings_client.py](../../TrainingAnalyticsPlatform/integrations/withings_client.py) | OAuth client, API methods, measurement parsing |
| [withings_webhook_processor.py](../../TrainingAnalyticsPlatform/integrations/withings_webhook_processor.py) | Async webhook processing logic |
| [function_app.py](../../function_app.py) | HTTP endpoints (authorize, callback, webhook) |
| [table_storage.py](../../TrainingAnalyticsPlatform/storage/table_storage.py) | Token and measurement storage |

### OAuth Token Management

**Token Storage:**

- Stored in `WithingsTokens` table
- PartitionKey: `athlete_id`
- RowKey: `withings_{userid}`

**Token Refresh:**

- Automatic refresh when expired
- Refresh tokens have ~180 day lifetime
- Stored tokens updated atomically

**Token Retrieval:**

```python
from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator

storage = StorageCoordinator()
tokens = storage.oauth_tokens.get_withings_tokens(athlete_id="rob")
# Returns: {access_token, refresh_token, expires_at_utc, withings_userid}
```

### Webhook Subscription Management

**Automatic Subscription:**

- Created during OAuth callback
- Notifies on weight/body composition measurements
- `appli=1` for weight-related data

**Subscription Properties:**

- Callback URL: `WITHINGS_WEBHOOK_URL` env variable
- Comment: "Health Assistant weight sync"
- Handles 343 status (already subscribed) gracefully

### Testing Locally

1. **Setup Ngrok for webhook testing:**

   ```bash
   ngrok http 7071
   ```

2. **Update environment variables:**

   ```bash
   WITHINGS_REDIRECT_URI=https://your-ngrok-id.ngrok.io/api/withings/callback
   WITHINGS_WEBHOOK_URL=https://your-ngrok-id.ngrok.io/api/withings/webhook
   ```

3. **Start function app:**

   ```bash
   func start
   ```

4. **Test authorization flow:**

   ```bash
   curl "http://localhost:7071/api/withings/authorize?athlete_id=rob"
   ```

### Error Handling

**Common Issues:**

| Error                                 | Cause                | Solution                                                                    |
| ------------------------------------- | -------------------- | --------------------------------------------------------------------------- |
| `Withings credentials not configured` | Missing env vars     | Set `WITHINGS_CLIENT_ID`, `WITHINGS_CLIENT_SECRET`, `WITHINGS_REDIRECT_URI` |
| `Invalid state parameter`             | State token mismatch | Verify state token format: `{token}:{athlete_id}`                           |
| `Token exchange failed`               | Invalid auth code    | Regenerate authorization URL                                                |
| `No Withings tokens found`            | User not authorized  | Complete OAuth flow first                                                   |
| `Status 343`                          | Already subscribed   | Normal - webhook already active                                             |

**Retry Logic:**

- Failed webhook processing automatically retries (Azure Queue default)
- Token refresh failures logged with full context
- API timeouts set to 30 seconds

### Security Considerations

1. **State Parameter Validation:**
   - Uses `secrets.token_urlsafe(32)` for CSRF protection
   - State includes athlete_id for context preservation

2. **Token Storage:**
   - Access tokens stored in Azure Table Storage
   - Automatic expiration handling
   - Secure refresh token rotation

3. **Webhook Signature (Optional):**
   - Withings provides signature validation
   - Currently not implemented (internal network)
   - Add for production if exposed publicly

### Monitoring & Diagnostics

**Application Insights Queries:**

```kusto
// Recent Withings authorizations
traces
  | where message contains "Withings"
  | where message contains "authorization"
  | order by timestamp desc

// Webhook processing failures
exceptions
  | where outerMessage contains "withings"
  | order by timestamp desc

// Measurement storage events
traces
  | where message contains "Stored Withings measurement"
  | order by timestamp desc
```

**Key Metrics:**

- Authorization success rate
- Webhook processing latency
- Token refresh frequency
- Measurement count by athlete

---

## Garmin Connect Integration

### Garmin Overview

**Status:** ✅ Production

The Garmin backend provides access to workout data directly from Garmin Connect using the `garminconnect` library with account credential login. It syncs activities as FIT files and reuses the existing FIT parsing pipeline.

Garmin also exposes a physiometrics sync that fetches daily summary and training-status metrics into the `Physiometrics` table. Under canonical wellness schema `4.1.0`, Garmin owns performance and training-state fields including `ftp_watts`, `cycling_vo2max_ml_kg_min`, `running_vo2max_ml_kg_min`, `hr_lthr_bpm`, `hr_max_bpm`, `training_load`, `recovery_time_minutes`, `readiness_score`, `training_effect_*`, `training_stress_*`, and `atp_probability`. `resting_hr_bpm` remains Intervals-exclusive and Garmin values are intentionally ignored.

**Data Flow:**

```text
Garmin Connect API
    ↓
GarminConnect login (email/password)
    ↓
Azure Function (Daily Timer + HTTP sync)
    ↓
Activity List → FIT Download
    ↓
FIT Parser → Metrics → Azure Table Storage
```

**Key Features:**

- Email/password login via `garminconnect`
- Daily sync at 3 AM UTC
- Configurable lookback window
- Download original FIT files
- Reuses existing FIT parsing pipeline (same as OneDrive)

### Garmin Prerequisites

- Garmin Connect account with activities
- Azure Function deployed with Garmin sync endpoints
- Garmin credentials configured in Function App settings (`GARMIN_EMAIL`, `GARMIN_PASSWORD`)

### Garmin Setup & Configuration

#### 1. Configure Garmin Environment Variables

Set these in your Function App configuration:

```bash
GARMIN_EMAIL=<garmin-account-email>
GARMIN_PASSWORD=<garmin-account-password>
GARMIN_SYNC_LOOKBACK_DAYS=30  # Optional, defaults to 30 days
```

In Azure deployments, store `GARMIN_EMAIL` and `GARMIN_PASSWORD` in Key Vault and use Key Vault references in app settings.

#### 2. Run Sync

Manual sync (HTTP):

```bash
curl -X POST "https://<FUNCTION_APP>.azurewebsites.net/api/garmin/sync?code=<FUNCTION_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"lookback_days": 30, "athlete_id": "rob", "async": true}'
```

By default the endpoint runs asynchronously and returns a 202 response. Set `async=false` to block and wait for results.

Automatic sync (Timer):

- Runs daily at 3 AM UTC
- Uses `GARMIN_SYNC_LOOKBACK_DAYS` by default (30 days)
- Downloads and parses FIT files for new activities

### Garmin API Endpoints

#### POST /api/garmin/sync

Runs a sync of recent activities. Accepts JSON body:

```json
{
  "lookback_days": 30,
  "athlete_id": "rob",
  "async": true
}
```

**Response (async=true):**

```json
{
  "status": "queued",
  "athlete_id": "rob",
  "lookback_days": 30
}
```

**Response (async=false):**

```json
{
  "status": "success",
  "lookback_days": 30,
  "found": 15,
  "ingested": 12,
  "skipped": 3,
  "failed": 0,
  "errors": [],
  "items": [...]
}
```

#### POST /api/garmin/physiometrics/sync

Runs a daily Garmin physiometrics sync using Garmin summary and training-status endpoints.

```json
{
  "lookback_days": 7,
  "athlete_id": "rob"
}
```

Successful responses include `count`, `records_fetched`, `records_processed`, and `records_failed`. Partial day-level failures return HTTP `207` with accumulated `errors`. Each fetched Garmin daily payload is also archived to the `external-sources` container and tracked in `SourceIngestionState` for replayability.

### Garmin Implementation Files

| File | Purpose |
| --- | --- |
| [garmin_client.py](../../TrainingAnalyticsPlatform/integrations/garmin_client.py) | garminconnect library wrapper |
| [garmin_sync_handler.py](../../TrainingAnalyticsPlatform/handlers/garmin_sync_handler.py) | Sync orchestration + ingestion handler |
| [garmin_physiometrics_sync_handler.py](../../TrainingAnalyticsPlatform/handlers/garmin_physiometrics_sync_handler.py) | Garmin physiometrics sync + raw payload archival |
| [function_app.py](../../function_app.py) | HTTP sync endpoint + daily timer trigger |
| [table_storage.py](../../TrainingAnalyticsPlatform/storage/table_storage.py) | Ingestion state tracking |

### Garmin Credential Management

- Credentials are read from `GARMIN_EMAIL` and `GARMIN_PASSWORD`.
- In Azure, these should be Key Vault references resolved by the Function App managed identity.
- No `GarminTokens` table is used by the current runtime Garmin integration.

### Activity Sync Workflow

1. **Fetch Activity List:** Query Garmin Connect for activities within lookback window
2. **Deduplicate:** Check `IngestionState` table to avoid reprocessing
3. **Download FIT Files:** Get original FIT file for each new activity
4. **Parse & Store:** Use standard FIT parser → canonical schema → Workouts table
5. **Track State:** Record ingestion status in `IngestionState` with source metadata

### Deduplication Strategy

Activities are identified by:

- `source_item_id`: Garmin activity ID (stored in IngestionState for idempotency)
- `source_system`: "Garmin" (stored in IngestionState table only, not queryable in Workouts)
- `file_sha256`: Hash of FIT file content (stored in IngestionState for dedup verification)

The ingestion handler checks `IngestionState` before processing each activity:

- Skip if `source_item_id` + `file_sha256` match existing state
- Reuse existing `workout_id` when reprocessing

### Troubleshooting

**"Authentication failed - check credentials"**:

- Verify `GARMIN_EMAIL` and `GARMIN_PASSWORD` are set correctly
- Test credentials by logging into Garmin Connect web UI
- Check Application Insights for detailed error logs
- Ensure Key Vault reference is working (if using Azure Key Vault)

**"Failed to list Garmin activities"**:

- Verify credentials are valid
- Check Application Insights for detailed error logs
- Test manual login locally with `garminconnect` library

**"FIT file download failed"**:

- Activity may not have exportable FIT file (e.g., manually entered)
- Check Garmin Connect web UI to verify activity has downloadable file
- Logs will show specific activity ID that failed

**"Activities not syncing"**:

- Check timer trigger is running (Application Insights)
- Verify `GARMIN_SYNC_LOOKBACK_DAYS` covers target date range
- Test manual sync: `POST /api/garmin/sync`
- Check `IngestionState` table for skipped activities

### Development Tips

**Local Testing with garminconnect:**

```python
from garminconnect import Garmin
import os

# Initialize client
client = Garmin(
    os.getenv("GARMIN_EMAIL"),
    os.getenv("GARMIN_PASSWORD"),
    tokenstore="~/.garminconnect"
)

# Login and authenticate
try:
    client.login()
    print("Authenticated successfully")
    
    # List recent activities
    activities = client.get_activities(start=0, limit=10)
    for activity in activities:
        print(f"{activity['activityId']}: {activity['activityName']}")
        
    # Download FIT file
    fit_data = client.download_activity(
        activities[0]['activityId'],
        dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL
    )
    print(f"Downloaded {len(fit_data)} bytes")
    
except Exception as exc:
    print(f"Garmin API error: {exc}")
```

**Testing Sync Locally:**

1. Set environment variables: `GARMIN_EMAIL`, `GARMIN_PASSWORD`
2. Run Azure Functions locally: `func start`
3. Trigger sync: `curl -X POST http://localhost:7071/api/garmin/sync -d '{"athlete_id":"rob"}'`
4. Check Function logs for progress

---

## Garmin vs. OneDrive Comparison

| Feature | Garmin Connect | HealthFit (OneDrive) |
| --- | --- | --- |
| **Trigger** | Daily timer (3 AM) | 10-min timer |
| **Authentication** | Email/Password | OAuth (Microsoft Graph) |
| **Library** | garminconnect (v0.2.38) | microsoft-graph |
| **File Format** | FIT (direct API) | FIT/FIT.gz (files) |
| **Deduplication** | Activity ID + hash | Item ID + hash |
| **Lookback** | 30 days default | 30 days default |
| **Manual Sync** | `/api/garmin/sync` | `/api/onedrive/sync` |
| **Credential Storage** | App settings/Key Vault (`GARMIN_EMAIL`, `GARMIN_PASSWORD`) | `OneDriveTokens` table |

---

## Workout Ingestion Architecture

### Three Parallel Sources (No Cross-Source Deduplication)

The system ingests workouts from **three independent pathways** with **no fallback or cross-source deduplication**:

| Source | Device Class | Ingestion Path | Filtration Rule |
| --- | --- | --- | --- |
| **Apple Watch** | Wearable | HealthFit → OneDrive → OneDrive handler | Accept only Apple Watch (`device_name` OR `device_model` contains `"watch"`) |
| **Garmin/Zwift** | Cycling computer / Platform | Garmin Connect API → Garmin handler | Accept only `manufacturer ∈ {1=Garmin, 263=Zwift}` |
| **Manual Upload** | Any | HTTP payload → Payload handler | No filtration |

**Key Principle**: Each pathway processes **only actual device recordings**. No complex cross-source deduplication logic exists.

---

### Why Parallel Sources (Not Hierarchical)?

#### The Problem: Workout Double-Counting

Without active deduplication, the same workout could appear through multiple pathways:

#### Example: Zwift Indoor Cycling Session

```text
❌ Path A (REJECTED): 
Zwift app → RunGap sync → HealthKit → HealthFit export → OneDrive
                                                         ↓
                                            device_name="iPhone" (sentinel)
                                            FILTERED OUT by OneDrive handler

✅ Path B (ACCEPTED):
Zwift app → Garmin Connect sync → Garmin API
                                  ↓
                     manufacturer_code=263 (Zwift)
                     ACCEPTED by Garmin handler
```

#### Why Not Deduplicate?

Cross-source deduplication would require:

- Fuzzy timestamp matching (workouts have time drift across systems)
- Sport/duration/distance comparison (ambiguous for similar sessions)
- Complex heuristics or LLM reasoning (expensive, fragile)

#### Our Approach: Prevent duplicates via strict device filtration at ingestion

---

### HealthFit Intelligence & Signal Encoding

**HealthFit is not a passive export app** - it encodes classification signals into FIT files that enable deterministic filtration.

#### **HealthKit-Synced Pattern (Secondary Export - REJECT)**

When a workout is synced INTO HealthKit by another app:

| Signal | Example | Interpretation |
| --- | --- | --- |
| **Filename** | `2026-01-07-030813-Indoor Cycling-RunGap.fit` | Date + Activity + **App Name** |
| **device_name** | `"iPhone"` | **Sentinel value** (not an actual device) |
| **manufacturer** | `"development"` (raw FIT) / `"Apple"` (canonical metadata + Workouts identity) | Apple exports raw `development`; ingestion normalizes canonical semantics |

**Combined meaning:**

- Filename source token = **app that synced to HealthKit** (RunGap, Zwift, Strava, Intervals.icu)
- `device_name="iPhone"` (or iPhone model identifier) = **not recorded by an Apple Watch source**
- This is a **secondary export** - workout exists elsewhere in primary form
- **Action**: REJECT during OneDrive ingestion (OneDrive allowlist is Apple Watch only)

#### **Actual Device Pattern (Primary Recording - ACCEPT)**

When Apple Watch records a workout directly:

| Signal | Example | Interpretation |
| --- | --- | --- |
| **Filename** | `2026-01-15-193027-Indoor Cycling-AppleWatch.fit` | Date + Activity + **Device Type** |
| **device_name** | `"Apple Watch Ultra"` or `"Watch 7,12"` | Actual recording device |
| **manufacturer** | `"development"` (raw FIT) / `"Apple"` (canonical metadata + Workouts identity) | Apple exports raw `development`; canonical fields normalize to `Apple` |

**Combined meaning:**

- Filename source token = **actual device type** (AppleWatch, Garmin)
- `device_name` OR `device_model` contains "Watch" = **native Apple Watch recording**
- This is a **primary recording** from the workout's origin device
- **Action**: ACCEPT during OneDrive ingestion

---

### The iPhone Sentinel

#### `device_name="iPhone"` is HealthFit's deterministic classification signal

When you see this pattern:

```python
device_name="iPhone"
manufacturer(raw)="development" / manufacturer(canonical)="Apple"
filename="2026-01-07-030813-Indoor Cycling-RunGap.fit"
                                           ^^^^^^
                                        App that synced to HealthKit
```

#### It means

1. The workout was synced **INTO** HealthKit by RunGap (or another app)
2. RunGap is the **syncing app**, not a recording device
3. The actual device could be Zwift, Garmin, Wahoo, etc. (unknown from this export)
4. This is a **secondary export** - the primary version exists elsewhere
5. **We reject it** to avoid double-counting

#### Why "iPhone" as sentinel?

- HealthFit uses the literal string `"iPhone"` as a sentinel value for HealthKit-synced workouts (not actual iPhone recordings)
- Real Apple devices have model identifiers: `"iPhone17,1"` (iPhone), `"Watch7,12"` (Apple Watch), etc.
- Actual Apple Watch recordings always have `device_name` containing "Watch" with a model ID
- This simple string check (`"iphone" in device_name.lower()`) detects the sentinel and enables fast, deterministic classification
- No complex heuristics or fuzzy matching needed

---

### RunGap as HealthKit Intermediary (Not a Source)

#### RunGap's role: sync intermediary

RunGap is a **workout sync app**, not a workout source:

1. **Fetches** workouts from Zwift, Intervals.icu, Rouvy, Garmin Connect, Strava
2. **Writes** them INTO Apple HealthKit via the HealthKit API
3. HealthFit exports these with `device_name="iPhone"` and filename source token `"RunGap"`

**Important clarifications:**

- RunGap CAN export directly to OneDrive (we do NOT use this pathway)
- We ONLY process HealthFit exports (single, predictable export mechanism)
- OneDrive = HealthFit exclusively (simplifies ingestion model)

**Similar sync apps:**

- **Intervals.icu** → writes to HealthKit → same pattern
- **Strava imports** → writes to HealthKit → same pattern  
- **Any app syncing to HealthKit** → triggers `device_name="iPhone"` pattern

---

### manufacturer="development" is NORMAL for Apple

**Common confusion:** `manufacturer="development"` looks like a placeholder or debug value

**Reality:**

- Apple is **not** an official FIT manufacturer code
- HealthFit uses `manufacturer="development"` for **ALL Apple exports**
- This includes legitimate Apple Watch recordings
- It is **NOT** a filtration signal

**Filtration Logic:**

```text
✅ manufacturer="development" + device_name="Apple Watch"   → ACCEPT (actual device)
✅ manufacturer="development" + device_name="Watch 7,12"    → ACCEPT (actual device)
❌ manufacturer="development" + device_name="iPhone"        → REJECT (HealthKit-synced)
```

**Do NOT filter on manufacturer="development" alone**  
**DO enforce Apple Watch allowlist (`watch` in device_name/device_model)**

---

### Garmin API: Manufacturer Allowlist

**Garmin handler filtration rule:**

```python
ALLOWED_MANUFACTURERS = {1, 263}  # Garmin=1, Zwift=263
```

**Rationale:**

- Garmin Connect can sync workouts FROM other platforms (via apps like RunGap)
- We want **ONLY** native Garmin/Zwift device recordings
- Manufacturer code filtering ensures data quality

**Examples:**

```text
✅ ACCEPTED:
- Garmin Edge 1050 → Garmin API (manufacturer_code=1)
- Zwift indoor session → Garmin API (manufacturer_code=263)

❌ REJECTED:
- Wahoo ELEMNT → RunGap → Garmin Connect (manufacturer_code=32)
- Polar watch → synced to Garmin (manufacturer_code=varies)
- Strava manual entry → imported to Garmin (manufacturer_code=varies)
```

**Code location:**

- Allowlist constant: `TrainingAnalyticsPlatform/handlers/ingestion_base_handler.py`
- Enforcement: `GarminSyncIngestionHandler._apply_device_source_filtration()`

---

### Filtration Summary

**What We Accept:**

- ✅ Apple Watch native recordings (via HealthFit → OneDrive)
- ✅ Garmin device recordings (via Garmin Connect API)
- ✅ Zwift sessions (via Garmin Connect API)
- ✅ Manual uploads (HTTP payload, any source, user responsibility)

**What We Reject:**

- ❌ Non-Apple-Watch workouts from OneDrive (including HealthKit-synced iPhone/app exports and Garmin/unknown devices)
- ❌ Non-Garmin/Zwift manufacturers from Garmin Connect API
- ❌ Secondary exports where primary source is available elsewhere

**Benefits:**

- **Data quality**: Primary device recordings only
- **No double-counting**: Each workout appears exactly once
- **Simple architecture**: No complex deduplication logic needed
- **Clear boundaries**: Each ingestion pathway has explicit responsibility

---

### Operational Monitoring

**Recommended Alerts:**

- Token refresh failures (Garmin/OneDrive)
- Sync job failures (Garmin/OneDrive scheduled tasks)
- High filtration rate (>50% of files rejected - may indicate configuration issue)
- Missing data for >7 days (any backend)

**Dashboard Tiles:**

- Last successful sync timestamp (OneDrive, Garmin)
- Workout count by source (last 30 days): Apple Watch, Garmin, Zwift, Manual
- Filtration rate by handler (filtered / total processed)
- Failed ingestion count by source (last 24 hours)
