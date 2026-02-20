# Backend Integrations

This document describes the external data source integrations for the Health Assistant system.

## Overview

The Health Assistant supports multiple backend integrations to automatically collect training and physiological data:

| Backend                  | Status       | Data Types                   | Protocol                       |
| ------------------------ | ------------ | ---------------------------- | ------------------------------ |
| **HealthFit (OneDrive)** | Production   | FIT workout files            | OAuth (delegated) + Timer/HTTP |
| **Withings**             | Production   | Body composition, weight     | OAuth 2.0 + Webhooks           |
| **Garmin**               | Implemented  | Workout files, physiometrics | OAuth (via garth)              |

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

- Runs hourly
- Uses `ONEDRIVE_SYNC_LOOKBACK_DAYS` by default

Lookback filtering uses the workout date parsed from the filename (YYYY-MM-DD) when available. If no date is found, it falls back to OneDrive `lastModifiedDateTime`.

### OneDrive API Endpoints

#### GET /api/onedrive/authorize

Generates an OAuth authorization URL for a specific athlete.

#### GET /api/onedrive/callback

OAuth callback endpoint that exchanges the auth code and stores tokens.

#### POST /api/onedrive/sync

Runs a one-time sync of recent files. Accepts JSON body:

```json
{"days": 30, "athlete_id": "rob"}
```

### OneDrive Implementation Files

| File                                                                        | Purpose                           |
| --------------------------------------------------------------------------- | --------------------------------- |
| [onedrive_client.py](FitParser/onedrive_client.py)                          | Microsoft Graph OAuth + API calls |
| [onedrive_sync_handler.py](FitParser/handlers/onedrive_sync_handler.py)     | OAuth + sync service              |
| [function_app.py](function_app.py)                                          | HTTP endpoints + timer trigger    |
| [table_storage.py](FitParser/table_storage.py)                              | Token storage + ingestion state   |

### OneDrive Troubleshooting

| Issue                | Likely Cause                          | Fix                                             |
| -------------------- | ------------------------------------- | ----------------------------------------------- |
| Authorization failed | Invalid client ID/secret/redirect URI | Verify app registration values                  |
| No tokens stored     | Callback not completed                | Complete authorize → callback flow              |
| No files found       | Wrong folder path                     | Verify `ONEDRIVE_FOLDER_PATH` and file location |

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
  "RowKey": "2026-01-25",                   # effective_date (YYYY-MM-DD)
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

- **Idempotency**: Same-day measurements overwrite previous values
- **Multi-source support**: `data_source` field distinguishes between backends
- **Time series queries**: Easily retrieve trends over date ranges

### Withings Implementation Files

| File                                                                     | Purpose                                        |
| ------------------------------------------------------------------------ | ---------------------------------------------- |
| [withings_client.py](FitParser/withings_client.py)                       | OAuth client, API methods, measurement parsing |
| [withings_webhook_processor.py](FitParser/withings_webhook_processor.py) | Async webhook processing logic                 |
| [function_app.py](function_app.py)                                       | HTTP endpoints (authorize, callback, webhook)  |
| [table_storage.py](FitParser/table_storage.py)                           | Token and measurement storage                  |

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
storage = WorkoutTableStorage()
tokens = storage.get_withings_tokens(athlete_id="rob")
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

**Status:** ✅ Implemented

The Garmin backend provides access to workout data directly from Garmin Connect using the [garminconnect](https://github.com/cyberjunky/python-garminconnect) Python library. It syncs activities as FIT files and reuses the existing FIT parsing pipeline.

**Data Flow:**

```text
Garmin Connect API (via garminconnect)
    ↓
Email/Password Authentication  
    ↓
Azure Function (Daily Timer + HTTP sync)
    ↓
Activity List → FIT Download
    ↓
FIT Parser → Metrics → Azure Table Storage
```

**Key Features:**

- Simple email/password authentication (no OAuth complexity)
- Automatic token management via `garminconnect` library
- Daily sync at 3 AM UTC
- Configurable lookback window
- Download original FIT files

### Garmin Prerequisites

- Garmin Connect account with activities
- Azure Function deployed with Garmin sync endpoint
- garminconnect Python library (>=0.2.38)

### Garmin Setup & Configuration

#### 1. Configure Garmin Environment Variables

Set these in your Function App configuration:

```bash
GARMIN_EMAIL=your_email@example.com
GARMIN_PASSWORD=your_password_here
GARMIN_SYNC_LOOKBACK_DAYS=30  # Optional, defaults to 30 days
GARMIN_TOKEN_DIR=~/.garminconnect  # Optional, defaults to ~/.garminconnect
```

⚠️ **Security Note:** Store credentials in Azure Key Vault and reference them via `@Microsoft.KeyVault(SecretUri=...)` syntax.

**Example with Key Vault:**

```bash
GARMIN_EMAIL=your_email@example.com
GARMIN_PASSWORD=@Microsoft.KeyVault(SecretUri=https://your-vault.vault.azure.net/secrets/garmin-password/)
```

#### 2. Run Sync

Manual sync (HTTP):

```bash
curl -X POST "https://<FUNCTION_APP>.azurewebsites.net/api/garmin/sync?code=<FUNCTION_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"days": 30, "athlete_id": "rob", "async": true}'
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
  "lookback_days": 30,
  "found": 15,
  "ingested": 12,
  "skipped": 3,
  "failed": 0,
  "errors": [],
  "items": [...]
}
```

### Garmin Implementation Files

| File | Purpose |
| --- | --- |
| [garmin_client.py](../../TrainingAnalyticsPlatform/integrations/garmin_client.py) | garminconnect library wrapper |
| [garmin_sync_handler.py](../../TrainingAnalyticsPlatform/handlers/garmin_sync_handler.py) | Sync orchestration + ingestion handler |
| [function_app.py](../../function_app.py) | HTTP sync endpoint + daily timer trigger |
| [table_storage.py](../../TrainingAnalyticsPlatform/storage/table_storage.py) | Ingestion state tracking |

### Garmin OAuth Token Management

**Token Storage:**

- Stored in `GarminTokens` table
- PartitionKey: `athlete_id`
- RowKey: `garmin`
- Contains: `oauth1_token`, `oauth2_token` (JSON strings from garth)

**Token Refresh:**

- garth library handles token refresh automatically
- Tokens loaded at sync time using `load_stored_tokens()`
- Updated tokens persisted back to storage

**Token Retrieval:**

```python
storage = WorkoutTableStorage()
tokens = storage.get_garmin_tokens(athlete_id="rob")
# Returns: {oauth1_token, oauth2_token, updated_at_utc}
```

### Activity Sync Workflow

1. **Fetch Activity List:** Query Garmin Connect for activities within lookback window
2. **Deduplicate:** Check `IngestionState` table to avoid reprocessing
3. **Download FIT Files:** Get original FIT file for each new activity
4. **Parse & Store:** Use standard FIT parser → canonical schema → Workouts table
5. **Track State:** Record ingestion status in `IngestionState` with `source_system=Garmin`

### Deduplication Strategy

Activities are identified by:

- `source_item_id`: Garmin activity ID
- `source_system`: "Garmin"
- `file_sha256`: Hash of FIT file content

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
| **Token Storage** | Managed by library | `OneDriveTokens` table |

---

## Multi-Backend Strategy (Updated)

### Data Source Priority

When multiple backends provide overlapping data:

1. **Workouts:**
   - Primary: HealthFit FIT files (most detailed)
   - Secondary: Garmin activities (native source, complete data)
   - Tertiary: Manual upload

2. **Body Composition:**
   - Primary: Withings (automatic, real-time)
   - Secondary: Garmin Index scale (if available)
   - Tertiary: Manual entry via API

3. **Daily Metrics:**
   - HRV/Stress: Garmin (primary source)
   - Weight: Withings (primary source)
   - Resting HR: Extracted from FIT files or Garmin daily stats

### Backend Health Monitoring

**Recommended Alerts:**

- Withings webhook failures (consecutive)
- Token refresh failures (Withings/Garmin/OneDrive)
- Sync job failures (Garmin/OneDrive scheduled tasks)
- Missing data for >7 days (any backend)

**Dashboard Tiles:**

- Last successful sync timestamp per backend (OneDrive, Garmin, Withings)
- Measurement count by data source (last 30 days)
- Authorization status per athlete per backend
- Failed ingestion count per backend (last 24 hours)
