# Backend Integrations

This document describes the external data source integrations for the Health Assistant system.

## Overview

The Health Assistant supports multiple backend integrations to automatically collect training and physiological data:

| Backend                  | Status     | Data Types                   | Protocol                       |
| ------------------------ | ---------- | ---------------------------- | ------------------------------ |
| **HealthFit (OneDrive)** | Production | FIT workout files            | OAuth (delegated) + Timer/HTTP |
| **Withings**             | Production | Body composition, weight     | OAuth 2.0 + Webhooks           |
| **Garmin**               | Planned    | Workout files, physiometrics | OAuth (via garth)              |

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

| File                                               | Purpose                           |
| -------------------------------------------------- | --------------------------------- |
| [onedrive_client.py](FitParser/onedrive_client.py) | Microsoft Graph OAuth + API calls |
| [onedrive_sync.py](FitParser/onedrive_sync.py)     | OAuth + sync service              |
| [function_app.py](function_app.py)                 | HTTP endpoints + timer trigger    |
| [table_storage.py](FitParser/table_storage.py)     | Token storage + ingestion state   |

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
  "Timestamp": "2026-01-25T08:30:00Z"
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

## Garmin Integration (Planned)

### Garmin Overview

**Status:** 🔜 Planned for future implementation

The Garmin backend will provide access to workout data and physiological metrics directly from Garmin Connect using the [garth](https://github.com/matin/garth) Python library.

### Planned Capabilities

**Data Sources:**

- Activities (FIT files, TCX exports)
- Daily physiological metrics (HRV, resting HR, stress, VO2max)
- Training status and load
- Body composition (if tracked via Garmin Index scale)

**Integration Approach:**

```text
Garmin Connect API (via garth)
    ↓
OAuth 2.0 Authentication
    ↓
Azure Function Endpoints
    ↓
Activity Sync (scheduled)
    ↓
Parse FIT/TCX files
    ↓
Store in Workouts/Physiometrics tables
```

### Technical Considerations

**garth Library:**

- Python library for Garmin Connect API access
- Handles OAuth flow and token management
- Provides activity download and stats retrieval

**Potential Architecture:**

1. **OAuth Flow:** Similar to Withings (authorize → callback → token storage)
2. **Scheduled Sync:** Timer-triggered function (daily/weekly)
3. **Activity Download:** Bulk fetch recent activities
4. **FIT Parsing:** Reuse existing `fit_parser.py` logic
5. **Deduplication:** Check `IngestionState` table to avoid duplicate processing

**Environment Variables (Draft):**

```bash
GARMIN_CLIENT_ID=your_client_id
GARMIN_CLIENT_SECRET=your_client_secret
GARMIN_REDIRECT_URI=https://<function-app>.azurewebsites.net/api/garmin/callback
```

### Implementation Roadmap

1. **Phase 1: Authentication**
   - OAuth endpoints (authorize, callback)
   - Token storage in dedicated table
   - Test with manual auth flow

2. **Phase 2: Activity Sync**
   - Scheduled function to fetch recent activities
   - Download FIT files
   - Parse and store using existing pipeline

3. **Phase 3: Physiometrics**
   - Fetch daily stats (HRV, resting HR, stress)
   - Store in `Physiometrics` table
   - Merge with Withings data

4. **Phase 4: Advanced Features**
   - Training status/load integration
   - Workout recommendations sync
   - Sleep data integration

### Resources

- **garth GitHub:** [https://github.com/matin/garth](https://github.com/matin/garth)
- **Garmin Connect API:** Unofficial (requires reverse engineering)
- **Documentation:** Limited - relies on garth library abstractions

---

## Multi-Backend Strategy

### Data Source Priority

When multiple backends provide overlapping data:

1. **Workouts:**
   - Primary: HealthFit FIT files (most detailed)
   - Secondary: Garmin activities (if HealthFit unavailable)

2. **Body Composition:**
   - Primary: Withings (automatic, real-time)
   - Secondary: Garmin Index scale (if available)
   - Tertiary: Manual entry via API

3. **Daily Metrics:**
   - HRV/Stress: Garmin (primary source)
   - Weight: Withings (primary source)
   - Resting HR: Extracted from FIT files or Garmin daily stats

### Deduplication Strategy

**Workout Files:**

- Use `file_identifier` (creation timestamp + serial number) as unique key
- Store in `IngestionState` table with `data_source` field
- Skip processing if already ingested from any source

**Physiometrics:**

- Use `effective_date` as deduplication key per athlete
- Last write wins for same-day measurements
- Preserve `data_source` for audit trail

**Example Deduplication Logic:**

```python
def should_process_workout(file_id: str, data_source: str) -> bool:
    """Check if workout already processed from any source."""
    existing = storage.get_ingestion_state(file_id)
    if existing:
        logger.info("Workout %s already ingested from %s", 
                   file_id, existing['data_source'])
        return False
    return True
```

### Backend Health Monitoring

**Recommended Alerts:**

- Withings webhook failures (consecutive)
- Token refresh failures (Withings/Garmin)
- Sync job failures (Garmin scheduled tasks)
- Missing data for >7 days (any backend)

**Dashboard Tiles:**

- Last successful sync timestamp per backend
- Measurement count by data source (last 30 days)
- Authorization status per athlete per backend
