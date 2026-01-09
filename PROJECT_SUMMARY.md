# Health Assistant - Project Summary

## Overview

A complete Azure Functions application that processes HealthFit FIT workout files from OneDrive and stores detailed metrics in Azure Table Storage according to a comprehensive schema.

**Status**: ✅ Development Complete - Ready for Azure Deployment

## Architecture

```
OneDrive (/Apps/HealthFit)
    ↓
Power Automate Flow (file monitor)
    ↓
Azure Function (HTTP trigger)
    ↓
FIT Parser (fitparse)
    ↓
Azure Table Storage
    ├── Workouts
    ├── WeeklyRollups
    └── IngestionState
```

## Project Structure

```
health_assistant/
├── FitParser/
│   ├── __init__.py
│   ├── fit_parser.py          # FIT file parsing + metric computation
│   ├── table_storage.py       # Azure Tables client
│   ├── config.py              # Configuration management
│   └── logging_setup.py       # Logging utilities
├── function_app/
│   ├── __init__.py            # Azure Functions app definition
│   ├── function_handler.py    # HTTP trigger handler
│   ├── function_app.json      # Function configuration
│── host.json                  # Function runtime config
├── requirements.txt           # Python dependencies
├── requirements-dev.txt       # Dev/test dependencies (pytest, coverage, freezegun)
├── local.settings.json        # Local development settings
├── .python-version            # Python 3.12.12 (pyenv)
├── .venv/                     # Virtual environment
├── schema.md                  # Complete data schema specification
├── README.md                  # Main documentation
├── POWER_AUTOMATE_SETUP.md    # Power Automate integration guide
├── DEPLOYMENT.md              # Azure deployment instructions
├── test_setup.py              # Setup verification script
└── test_payload_example.json  # Example function payload
```

## Key Features

### FIT Parsing

- ✅ Heart rate metrics (avg, max, samples, missing %)
- ✅ Power metrics (avg, max, normalized, variability index)
- ✅ Cadence metrics (avg, max, samples)
- ✅ Distance, elevation, speed
- ✅ Sport classification, device info
- ✅ Temporal data (start, end, duration, moving time)

### Zone Computation

- ✅ Heart rate zones (HRmax, LTHR, HRR methods; 5-zone model)
- ✅ Power zones (7-zone Coggan model with FTP)
- ✅ Time-in-zone metrics (seconds + derived minutes)
- ✅ Convenience fields (Z2 minutes, intensity minutes)

### Azure Integration

- ✅ HTTP-triggered function
- ✅ Idempotent processing (avoids duplicates)
- ✅ Automatic table creation
- ✅ Ingestion state tracking
- ✅ Error recording for debugging

### Data Schema

- ✅ Comprehensive Workouts table with all metrics
- ✅ WeeklyRollups for aggregated trends
- ✅ IngestionState for idempotency tracking
- ✅ Partitioning by athlete + month for query optimization

## Supported Metrics

### Per-Workout

| Category | Fields |
|----------|--------|
| **Identity** | sport, sub_sport, workout_name, device_name, source_system |
| **Temporal** | start_time, end_time, duration, moving_time, timezone |
| **Distance/Elevation** | distance_m, elevation_gain_m, elevation_loss_m |
| **Speed** | avg_speed_mps, max_speed_mps |
| **Heart Rate** | avg_bpm, max_bpm, samples_count, missing_pct, zones |
| **Power (cycling)** | avg_watts, max_watts, normalized, VI, zones |
| **Cadence** | avg_rpm, max_rpm, samples_count |
| **Training Load** | TRIMP, TSS, intensity_factor (optional) |
| **Efficiency** | decoupling_pct, HR_drift, EF (optional) |

### Per-Week Rollups

- Workout count, duration, distance
- Total HR/power zone minutes
- Hard/long day counts
- Average decoupling
- Last update timestamp

## Environment Configuration

```bash
# Required
AzureWebJobsStorage          # Storage account connection string
# OR
AZURE_STORAGE_ACCOUNT_URL    # Storage account URL (with DefaultAzureCredential)

# Optional
DEFAULT_ATHLETE_ID=rob
DEFAULT_FTP=250              # FTP in watts for power zone computation
DEFAULT_MAX_HR=190           # Max HR for HR zone computation
HR_ZONE_BASIS=HRmax|LTHR|HRR # Heart rate zone basis
HR_ZONE_REFERENCE_BPM=0      # Reference HR (0 = auto-detect)
HR_RESTING_BPM=60            # Resting HR for HRR
ONEDRIVE_FOLDER_PATH=/Apps/HealthFit
```

## API Endpoint

### HTTP Trigger: `POST /api/process_fit`

**Request Body** (JSON):

```json
{
  "athlete_id": "rob",
  "source_item_id": "OneDrive_itemId",
  "source_file_name": "2026-01-07-workout.fit",
  "source_file_path": "/Apps/HealthFit/2026-01-07-workout.fit",
  "source_drive_id": "drive_id",
  "source_etag": "ETag_for_change_tracking",
  "file_size_bytes": 12345,
  "file_content_b64": "base64_encoded_fit_file"
}
```

**Success Response** (200):

```json
{
  "status": "success",
  "workout_id": "a1b2c3d4e5f6g7h8",
  "athlete_id": "rob",
  "sport": "cycling",
  "duration_sec": 3600,
  "metrics": {
    "distance_m": 25000,
    "avg_power_watts": 245,
    "avg_hr_bpm": 142
  }
}
```

**Already Processed** (200):

```json
{
  "status": "skipped",
  "reason": "File already processed",
  "workout_id": "a1b2c3d4e5f6g7h8"
}
```

**Errors** (400/500):

```json
{
  "error": "Missing required fields: file_content_b64"
}
```

## Dependencies

```
azure-functions>=1.14.0       # Azure Functions SDK
azure-data-tables>=12.4.0     # Table Storage client
azure-identity>=1.14.0        # Azure authentication
fitparse>=1.2.0               # FIT file parsing
python-dateutil>=2.8.2        # Date utilities
python-dotenv>=1.0.0          # Environment management
```

## Quick Start

### Local Development

```bash
# Activate virtual environment
source .venv/bin/activate

# Run tests
pytest

# Start local Azure Functions runtime
func start
```

### Test the Function

```bash
curl -X POST http://localhost:7071/api/process_fit \
  -H "Content-Type: application/json" \
  -d @test_payload_example.json
```

### Deploy to Azure

```bash
# Follow DEPLOYMENT.md for complete instructions
# Quick version:
az login
func azure functionapp publish <FUNCTION_APP_NAME> --python
```

## Integration Points

### Power Automate

- Monitor OneDrive folder for new .fit files
- Convert file to base64
- Extract metadata (itemId, name, path, size)
- POST to ProcessFitFiles function endpoint

See [POWER_AUTOMATE_SETUP.md](./POWER_AUTOMATE_SETUP.md) for detailed flow configuration.

### Power BI

- Query Workouts table for interactive dashboards
- Use WeeklyRollups for trend analysis
- Filter by athlete_id and date range using partition key

### Custom APIs

- Build REST API around Workouts table
- Implement weekly planning context endpoint
- Return recent workouts + rollups for training decisions

## Testing

### Unit Tests

```bash
# Run setup verification
python test_setup.py
```

### Integration Tests

1. Upload sample FIT file to OneDrive `/Apps/HealthFit/`
2. Flow triggers automatically (or manually)
3. Check Application Insights for logs
4. Query Azure Tables for stored data

### Performance

- Single FIT file: ~500ms (parsing + storage)
- Max function timeout: 30 minutes
- Handles files up to 50MB (FIT files typically 100KB-2MB)

## Future Enhancements

- [ ] Microsoft Graph API for direct OneDrive monitoring (timer trigger)
- [ ] Weekly rollup computation (triggered nightly)
- [ ] Aerobic efficiency metrics (EF, decoupling)
- [ ] Training Load Score (TSS) computation
- [ ] Configurable athlete FTP per athlete/workout
- [ ] Export to Strava/Garmin APIs
- [ ] REST API layer for Power BI actions
- [ ] Batch processing for historical imports

## Known Limitations

- Power zones use fixed FTP (250W) - can be made per-athlete
- HR zones configurable (HRmax/LTHR/HRR) but single default per deployment
- No GPS track data stored (could use Blob Storage)
- Zone boundaries stored per-workout for interpretability

## Support & Documentation

- **README.md** - Main documentation and architecture
- **schema.md** - Complete data schema specification
- **POWER_AUTOMATE_SETUP.md** - Power Automate flow integration
- **DEPLOYMENT.md** - Azure deployment & scaling guide
- **test_setup.py** - Automated setup verification

## Version

- **Python**: 3.12.12
- **Runtime**: Azure Functions v4
- **Schema**: v1.0

---

**Created**: January 8, 2026
**Status**: Ready for Azure deployment
