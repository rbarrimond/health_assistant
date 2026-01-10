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
├── DEPLOYMENT.md              # Azure deployment instructions
├── POWER_AUTOMATE_SETUP.md    # Power Automate integration
├── README.md                  # Architecture and setup
├── SCHEMA_IMPLEMENTATION.md   # Advanced metrics details
├── TESTING.md                 # Test strategy
├── WORKOUT_SCHEMA.md          # Data schema specification
├── host.json                  # Function runtime config
├── local.settings.json        # Local dev settings
├── pyproject.toml             # Dependencies and config
├── requirements.txt           # Runtime dependencies
├── test_payload_example.json  # Example function payload
└── test_setup.py              # Setup verification script
```

## Build & Test Commands

All tests are in `tests/` directory. Temporary/demo scripts at root level are for development reference only.

## Implemented Capabilities

### FIT Parsing

- Heart rate metrics (avg, max, samples, missing %, resting)
- Power metrics (avg, max, normalized, variability index, FTP extraction)
- Cadence metrics (avg, max, samples)
- Distance, elevation, speed
- Sport classification, device info
- Temporal data (start, end, duration, moving time)

### Zone Computation

- Heart rate zones (HRmax, LTHR, HRR methods; 5-zone model with boundaries)
- Power zones (7-zone Coggan model with FTP, zone boundaries stored)
- Time-in-zone metrics (seconds + derived minutes)
- HR zone boundaries: 10 fields (hr_z1-5_low/high_bpm)
- Power zone boundaries: 14 fields (pwr_z1-7_low/high_w)
- Convenience fields (Z2 minutes, intensity minutes)

### Training Load Metrics

- TSS (Training Stress Score): `(duration_hours × NP × IF × 100) / FTP`
- Intensity Factor (IF): `normalized_power / FTP`
- FTP extraction from FIT user_profile (250W default if not present)

### Aerobic Efficiency Metrics

- EF (Efficiency Factor): Power ÷ Heart Rate for first half, second half, overall
- HR drift: Heart rate increase from first to second half
- Aerobic decoupling: `((EF_second / EF_first) - 1) × 100`
- Resting HR extraction from FIT user_profile

### Azure Integration

- HTTP-triggered function for OneDrive file processing
- Idempotent processing (avoids duplicate ingestion)
- Automatic table creation and schema management
- Ingestion state tracking (IngestionState table)
- Error recording for debugging and monitoring

### Data Persistence

- Workouts table: All parsed metrics per file (athlete_id partition)
- WeeklyRollups table: Aggregated trend data per week
- IngestionState table: Processing status for idempotency
- Partitioned by athlete_id + date for query optimization

## Supported Metrics

### Per-Workout

| Category | Fields |
|----------|--------|
| **Identity** | sport, sub_sport, workout_name, device_name, source_system |
| **Temporal** | start_time, end_time, duration, moving_time, timezone |
| **Distance/Elevation** | distance_m, elevation_gain_m, elevation_loss_m |
| **Speed** | avg_speed_mps, max_speed_mps |
| **Heart Rate** | avg_bpm, max_bpm, samples_count, missing_pct, resting_bpm, zones + boundaries |
| **Power (cycling)** | avg_watts, max_watts, normalized, VI, FTP, zones + boundaries |
| **Cadence** | avg_rpm, max_rpm, samples_count |
| **Training Load** | TSS, intensity_factor |
| **Aerobic Efficiency** | ef_first_half, ef_second_half, ef_overall, hr_drift_bpm, decoupling_pct |
| **Zone Boundaries** | hr_z1-5_low/high_bpm (10), pwr_z1-7_low/high_w (14) |

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

## Test Coverage

```bash
# Run all tests
pytest tests/ -v

# Run specific test class
pytest tests/test_fit_parser.py::TestFitParserFullParse -v

# Run with coverage
pytest tests/ --cov=FitParser --cov-report=html
```

Test suites:
- **test_fit_parser.py** - 42 tests covering parsing, zones, metrics, entities
- **test_schema_fields.py** - 5 tests verifying new schema fields (boundaries, TSS, EF, decoupling)

## Documentation

- **README.md** - Main documentation and architecture
- **WORKOUT_SCHEMA.md** - Data schema specification
- **POWER_AUTOMATE_SETUP.md** - Power Automate flow integration
- **DEPLOYMENT.md** - Azure deployment & scaling guide
- **TESTING.md** - Test strategy and coverage

## Future Enhancements

- [ ] Microsoft Graph API for direct OneDrive monitoring (timer trigger)
- [ ] Weekly rollup computation (triggered nightly)
- [ ] Export to Strava/Garmin APIs
- [ ] REST API layer for Power BI actions
- [ ] Batch processing for historical imports

## Known Limitations

- HR zones configurable (HRmax/LTHR/HRR) but single default per deployment
- No GPS track data stored (could use Blob Storage)
- Zone boundaries stored per-workout (enables Power BI interpretation)

## Version

- **Python**: 3.12.12
- **Runtime**: Azure Functions v4
- **Schema**: v1.0

---

**Created**: January 8, 2026
**Status**: Ready for Azure deployment
