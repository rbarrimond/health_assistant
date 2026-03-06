# Configuration Files

This directory contains configuration templates and examples for local development and production deployment.

**Important**: Only example/template files are committed to version control. Generated or user-specific configs remain local and are excluded via `.gitignore`.

## Application-Level Constants and Mappings

### `constants.py` - HTTP & Plugin Configuration

Contains global configuration for the HTTP API and plugin system:

- Content type definitions (`JSON_CONTENT_TYPE`, `HTML_CONTENT_TYPE`, etc.)
- Error messages for API responses
- Environment variable names for plugin metadata
- API documentation paths

**Scope**: Health Assistant platform layer and HTTP endpoints  
**Used by**: `function_app.py`, `utils.py`, HTTP utilities

---

### Rationale for Multiple `constants.py` Files

The codebase has two separate constants files in different modules:

1. **`config/constants.py`** - Platform configuration
   - HTTP API and plugin metadata
   - Shared across function app and utilities
   - Low-level infrastructure concerns

2. **`TrainingAnalyticsPlatform/models/constants.py`** - Analytics configuration
   - Workout analysis thresholds and algorithms
   - Time series computation parameters
   - Specific to the analytics engine

**Why separate?**

- **Modularity**: Each module encapsulates its own configuration dependencies
- **Independent scaling**: Analytics constants can be tuned independently without affecting HTTP layer
- **Reduced coupling**: The analytics platform can be used standalone without loading HTTP config
- **Clarity**: Constants are located near their usage context

## Configuration Template Files

- **`physiometrics.json.example`** - Template for athlete physiological configuration
- **`onedrive_power_automate_legacy.json.example`** - Legacy Power Automate configuration (deprecated)
- **`README.md`** - This file (configuration documentation)

**Local-only files** (created by you, never committed):

- **`physiometrics.json`** - Your actual athlete configuration
- **`onedrive_power_automate_legacy.json`** - Legacy config (if needed)

## physiometrics.json

The `physiometrics.json` file contains current athlete-specific configuration for heart rate and power metrics. This represents your *current physiological truth* and is snapshotted into each workout record during ingestion.

### Example Structure

See `physiometrics.json.example` for a complete example.
Create your local file from the example and do not commit it.

### Heart Rate Configuration

- **basis**: Zone calculation method
  - `HRmax` - Percentage of maximum heart rate (default)
  - `LTHR` - Lactate Threshold Heart Rate method
  - `HRR` - Heart Rate Reserve (Karvonen) method
- **lthr_bpm**: Lactate Threshold Heart Rate value (used with LTHR basis)
- **hr_max_bpm**: Maximum Heart Rate value (used with HRmax or HRR basis)
- **resting_hr_bpm**: Resting Heart Rate (used with HRR basis; default 60)
- **zones**: Zone definitions with percentage boundaries (relative to reference value)

### Power Configuration

- **ftp_watts**: Functional Threshold Power in watts
- **zones**: Zone definitions with percentage boundaries (relative to FTP)

## Configuration Precedence

The Health Assistant Config system loads configuration values in this order (highest to lowest priority):

1. **Azure Table Storage** (highest priority - recommended for production and runtime updates)
   - Stored in `Physiometrics` table via `table_storage` module
   - Frequently updated with current athlete metrics (LTHR, FTP, etc.)
   - Allows runtime updates without redeployment via `/api/config/update` endpoint
   - Requires `AzureWebJobsStorage` or `AZURE_STORAGE_ACCOUNT_URL` configured

2. **Environment Variables** (fallback - deployment-level overrides)
   - Only used if corresponding value is **missing** from Table Storage
   - `ATHLETE_TIMEZONE` - IANA timezone name for athlete's home location (e.g., `America/New_York`) used to disambiguate UTC offsets and resolve Zwift/virtual workout timezones
   - `HR_ZONE_BASIS` - Heart rate zone calculation method (`HRmax`, `LTHR`, or `HRR`)
   - `HR_ZONE_REFERENCE_BPM` - Maximum HR or LTHR value (only used if Table Storage missing)
   - `HR_RESTING_BPM` - Resting heart rate for HRR method
   - `DEFAULT_FTP` - Functional Threshold Power in watts
   - `PHYSIOMETRICS_PATH` - Custom path to physiometrics.json file
   - Set via Azure Function App Settings or `local.settings.json`

3. **Filesystem Configuration** (development/legacy fallback)
   - Loaded from `config/physiometrics.json` only if Table Storage unavailable
   - Location can be overridden with `PHYSIOMETRICS_PATH` env var
   - Intended for local development and testing
   - Not recommended for production (lacks audit trail)

4. **Hard Defaults** (lowest priority - only if all above missing)
   - HR basis: `HRmax`
   - Resting HR: `60 bpm`
   - Maximum HR: `190 bpm`
   - FTP: `250 watts`
   - Used only when no other configuration source is available

**Configuration Loading**:

- Config is loaded once at Function App startup (singleton pattern)
- Update configuration: `POST /api/config/update` (admin endpoint) - updates athlete metrics in Table Storage
- View configuration history: `GET /api/config/history` (admin endpoint) - audit trail of configuration changes

## Local Development Setup

### Athlete Metrics Configuration (physiometrics.json)

For **local development only**. In production, use `/api/config/update` endpoint to store metrics in Table Storage.

**Step 1**: Copy the example file:

```bash
cp config/physiometrics.json.example config/physiometrics.json
```

**Step 2**: Edit `config/physiometrics.json` with your athlete-specific metrics (local fallback):

```json
{
  "athlete_id": "rob",
  "heart_rate": {
    "basis": "HRmax",
    "lthr_bpm": 165,
    "hr_max_bpm": 190,
    "resting_hr_bpm": 60,
    "zones": {
      "z1": {"min": 0.0, "max": 0.68},
      "z2": {"min": 0.68, "max": 0.83},
      "z3": {"min": 0.83, "max": 0.94},
      "z4": {"min": 0.94, "max": 1.06},
      "z5": {"min": 1.06, "max": 1.20}
    }
  },
  "power": {
    "ftp_watts": 250,
    "zones": {
      "z1": {"min": 0.0, "max": 0.55},
      "z2": {"min": 0.55, "max": 0.75},
      "z3": {"min": 0.75, "max": 0.90},
      "z4": {"min": 0.90, "max": 1.05},
      "z5": {"min": 1.05, "max": 1.20},
      "z6": {"min": 1.20, "max": 1.50},
      "z7": {"min": 1.50, "max": 10.0}
    }
  }
}
```

**Step 3**: The Config class will automatically load it at runtime when the Function App starts.

**Verification**:

```bash
# Start the Functions host
func start

# Check current configuration
curl "http://localhost:7071/api/physiometrics/current?athlete_id=rob"
```

### Environment Variable Configuration (Alternative)

For deployment environments, set these in Azure Function App Settings or `local.settings.json`:

```json
{
  "Values": {
    "HR_ZONE_BASIS": "HRmax",
    "HR_ZONE_REFERENCE_BPM": "190",
    "HR_RESTING_BPM": "60",
    "DEFAULT_FTP": "250"
  }
}
```

### Production Configuration (Azure Table Storage)

**Recommended approach for production**:

Update configuration via API endpoint:

```bash
curl -X POST "https://<your-function-app>.azurewebsites.net/api/config/update?code=<function_key>" \
  -H "Content-Type: application/json" \
  -d '{
    "athlete_id": "rob",
    "heart_rate": {
      "basis": "LTHR",
      "lthr_bpm": 165,
      "hr_max_bpm": 190,
      "resting_hr_bpm": 60
    },
    "power": {
      "ftp_watts": 260
    }
  }'
```

**Benefits**:

- No redeployment needed for configuration changes
- Configuration changes take effect immediately after reload
- Audit trail via `/api/config/history`
- Supports multiple athletes (future)

## Backend Integration Setup

### OneDrive Personal OAuth

For automatic FIT file sync from OneDrive Personal (`/Apps/HealthFit` folder):

**Prerequisites**:

1. Azure App Registration (consumer/personal accounts)
2. Configured redirect URI pointing to `/api/onedrive/callback`
3. Granted permissions: `Files.ReadWrite`, `offline_access`

**Environment Variables**:

```json
{
  "Values": {
    "ONEDRIVE_CLIENT_ID": "your-client-id",
    "ONEDRIVE_CLIENT_SECRET": "your-client-secret",
    "ONEDRIVE_REDIRECT_URI": "https://<your-function-app>.azurewebsites.net/api/onedrive/callback",
    "ONEDRIVE_FOLDER_PATH": "/Apps/HealthFit",
    "ONEDRIVE_SYNC_LOOKBACK_DAYS": "30"
  }
}
```

**Authorization Flow**:

1. Navigate to: `https://<your-function-app>.azurewebsites.net/api/onedrive/authorize?code=<function_key>&athlete_id=rob`
2. Sign in with Microsoft account
3. Grant permissions
4. Refresh token stored automatically

**See**: [../docs/devops/BACKENDS.md](../docs/devops/BACKENDS.md#onedrive-personal-integration) for complete setup guide.

### Withings Integration

For automatic body metrics (weight, body fat, muscle mass) via webhook:

**Prerequisites**:

1. Withings Developer Account
2. Registered application with webhook URL
3. Configured redirect URI pointing to `/api/withings/callback`

**Environment Variables**:

```json
{
  "Values": {
    "WITHINGS_CLIENT_ID": "your-client-id",
    "WITHINGS_CLIENT_SECRET": "your-client-secret",
    "WITHINGS_REDIRECT_URI": "https://<your-function-app>.azurewebsites.net/api/withings/callback"
  }
}
```

**Authorization Flow**:

1. Navigate to: `https://<your-function-app>.azurewebsites.net/api/withings/authorize?code=<function_key>&athlete_id=rob`
2. Sign in to Withings
3. Grant permissions
4. Configure webhook to: `https://<your-function-app>.azurewebsites.net/api/withings/webhook`

**See**: [../docs/devops/BACKENDS.md](../docs/devops/BACKENDS.md#withings-integration) for complete setup guide.

## Troubleshooting

### Configuration Not Loading

**Check configuration source**:

```bash
# View current config
curl "http://localhost:7071/api/physiometrics/current?athlete_id=rob"

# Check configuration history
curl "http://localhost:7071/api/config/history?limit=10"
```

**Common issues**:

- `physiometrics.json` not in `config/` directory
- JSON syntax errors in configuration file
- Environment variables not set correctly
- Azure Storage connection not configured

### Zones Not Calculated Correctly

**Verify zone definitions**:

- Check `basis` matches your intended calculation method
- Ensure zone percentages are correct (e.g., Z2 for HRmax is typically 0.68-0.83)
- Verify reference values (HR max, LTHR, FTP) are accurate
- Check resting HR is set correctly for HRR method

**Recalculate a workout with current config**:

```bash
curl "http://localhost:7071/api/workouts/{workout_id}/recalculated?athlete_id=rob"
```

### FTP or HR Values Outdated

**Update via API** (recommended):

```bash
curl -X POST "http://localhost:7071/api/config/update?code=<function_key>" \
  -H "Content-Type: application/json" \
  -d '{"athlete_id": "rob", "power": {"ftp_watts": 270}}'

# Reload configuration
curl -X POST "http://localhost:7071/api/config/reload"
```

**Update via environment variables**:

- Set `DEFAULT_FTP` in Function App Settings
- Restart Function App

**Update via filesystem** (local only):

- Edit `config/physiometrics.json`
- Restart Functions host: `func start`

## Related Documentation

- [Main README](../README.md) - Project overview and quick start
- [BACKENDS.md](../docs/devops/BACKENDS.md) - OneDrive, Withings, Garmin integration
- [DEPLOYMENT.md](../docs/devops/DEPLOYMENT.md) - Azure deployment procedures
- [WORKOUT_SCHEMA.md](../docs/gpt/WORKOUT_SCHEMA.md) - Data model and fields
- [SEMANTIC_LAYER_API.md](../docs/gpt/SEMANTIC_LAYER_API.md) - API reference

---

**Note**: Never commit `physiometrics.json` or any file containing actual authentication credentials. Always use `.example` files for templates.
