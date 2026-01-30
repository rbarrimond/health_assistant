# Health Assistant - FIT File Processor

Azure Function for parsing HealthFit FIT files from iCloud Drive and storing metrics in Azure Table Storage according to a comprehensive training analytics schema.

**Status**: ✅ Development Complete - Ready for Azure Deployment

## Quick Navigation

| Role | Start Here |
| --- | --- |
| **⚡ First time?** | [Architecture Overview](#architecture) below |
| **🚀 Deploying?** | [DEPLOYMENT.md](./DEPLOYMENT.md) (30 min) |
| **📊 Setting up dashboards?** | [MONITORING.md](./MONITORING.md) → Power BI section |
| **🔌 Building integrations?** | [SEMANTIC_LAYER_API.md](./SEMANTIC_LAYER_API.md) |
| **� Configuring backends?** | [BACKENDS.md](./BACKENDS.md) → Withings, Garmin |
| **�📐 Understanding the data model?** | [WORKOUT_SCHEMA.md](./WORKOUT_SCHEMA.md) |
| **🎯 Design philosophy?** | [WORKOUT_INTELLIGENCE_AGENT_VISION.md](./WORKOUT_INTELLIGENCE_AGENT_VISION.md) |
| **⚙️ iCloud sync setup?** | [POWER_AUTOMATE_SETUP.md](./POWER_AUTOMATE_SETUP.md) |

## Architecture

```text
Apple iCloud Drive (/HealthFit)
    ↓
Azure Function (Timer + HTTP sync)
    ↓
FIT Parser (fitparse library)
    ↓
Zone Computation & Metrics
    ↓
Azure Table Storage
    ├── Workouts (100+ fields per session)
    ├── WeeklyRollups (aggregated data)
    └── IngestionState (idempotency tracking)
    ↓
Semantic Layer API (14 endpoints for ChatGPT)
    ↓
Read Interfaces
├── Power BI Dashboards (training analytics)
├── Application Insights (Function health)
└── ChatGPT UI (real-time planning context)
```

### Data Flow

- **Trigger**: Timer + HTTP sync against iCloud Drive (WebDAV)
- **Input**: Base64-encoded FIT file + metadata in JSON payload
- **Processing**: FIT parsing → metric extraction → zone computation
- **Output**: Azure Tables (Workouts, WeeklyRollups, IngestionState)
- **Read Layer**: Semantic API endpoints for planning, workout queries, analysis

## Configuration

Environment variables required:

- AzureWebJobsStorage: Connection string to Azure Storage account
- Or AZURE_STORAGE_ACCOUNT_URL: Direct storage account URL (with DefaultAzureCredential)

Optional:

- DEFAULT_ATHLETE_ID: Default athlete identifier (default: 'rob')
- DEFAULT_FTP: Default FTP for power zones (default: 250W)
- DEFAULT_MAX_HR: Default max HR for heart rate zones (default: 190bpm)
- HR_ZONE_BASIS: Heart rate zone calculation method - 'HRmax', 'LTHR' (Lactate Threshold), or 'HRR' (Heart Rate Reserve/Karvonen) (default: 'HRmax')
- HR_ZONE_REFERENCE_BPM: Reference HR for zone calculation (0 = auto-detect from workout) (default: 0)
- HR_RESTING_BPM: Resting heart rate for HRR method (default: 60bpm)
- ICLOUD_WEBDAV_URL: iCloud WebDAV base URL
- ICLOUD_USERNAME: Apple ID for WebDAV access
- ICLOUD_APP_PASSWORD: App-specific password
- ICLOUD_FOLDER_PATH: iCloud folder path (default: '/HealthFit')
- ICLOUD_SYNC_LOOKBACK_DAYS: Default lookback window (days, default: 30)

See `POWER_AUTOMATE_SETUP.md` for how to discover your iCloud WebDAV URL.

## Project Structure

```text
health_assistant/
├── FitParser/
│   ├── fit_parser.py          # FIT file parsing + metric computation
│   ├── models.py              # Pydantic entities
│   ├── adapter.py             # fitparse → pydantic mapping
│   ├── table_storage.py       # Azure Tables client
│   ├── config.py              # Configuration management
│   ├── semantic_layer.py      # Read API implementation
│   ├── withings_client.py     # Withings integration
│   ├── icloud_client.py       # iCloud WebDAV client
│   └── logging_setup.py       # Logging utilities
├── function_app.py            # Azure Functions HTTP endpoints
├── pyproject.toml             # Dependencies
├── requirements.txt           # Runtime dependencies
├── tests/                     # 158 automated tests
│   ├── test_fit_parser.py
│   ├── test_config.py
│   ├── test_semantic_layer.py
│   ├── test_function_endpoints.py
│   ├── test_physiometrics_timeseries.py
│   └── data/                  # Real FIT workout files
├── DEPLOYMENT.md              # Azure deployment
├── MONITORING.md              # Power BI + Application Insights
├── POWER_AUTOMATE_SETUP.md    # iCloud sync guide (legacy OneDrive notes)
├── SEMANTIC_LAYER_API.md      # API reference (14 endpoints)
├── WORKOUT_SCHEMA.md          # Complete data schema
└── WORKOUT_INTELLIGENCE_AGENT_VISION.md  # Design principles
```

## Implemented Capabilities

### FIT Parsing & Metric Extraction

- Heart rate metrics (avg, max, samples, missing %, resting HR)
- Power metrics (avg, max, normalized, variability index, FTP)
- Cadence, distance, elevation, speed
- Sport classification and device info
- Temporal data (start, end, duration, moving time)

### Zone Computation

- **Heart Rate Zones**: HRmax, LTHR, or HRR (Heart Rate Reserve/Karvonen) methods
- **Power Zones**: 7-zone Coggan model with FTP
- **Time-in-Zone**: Seconds and derived minutes for each zone
- **Zone Boundaries**: Stored separately (10 HR zone fields, 14 power zone fields)

### Training Load Metrics

- **TSS** (Training Stress Score): `(duration_hours × NP × IF × 100) / FTP`
- **Intensity Factor**: `normalized_power / FTP`
- **FTP Extraction**: From FIT user_profile (250W default)

### Aerobic Efficiency Metrics

- **EF** (Efficiency Factor): Power ÷ Heart Rate for first/second half/overall
- **HR Drift**: Heart rate increase from first to second half
- **Aerobic Decoupling**: `((EF_second / EF_first) - 1) × 100`
- **Resting HR**: Extracted from FIT user_profile

### Semantic Layer (Read API)

- **Planning Context**: What should I do tomorrow based on recent history?
- **Workout Queries**: Filter by date range, sport type, intensity
- **Weekly Rollups**: Aggregated training summaries
- **Analysis Queries**: Zone distribution, efficiency trends, decoupling
- **Physiometrics**: Weight, FTP, LTHR, body composition trends
- **Withings Integration**: OAuth webhooks for automatic body metrics

## Local Development

1. Set up Python environment:

   ```bash
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Create local.settings.json with storage account details:

   ```json
   {
     "IsEncrypted": false,
     "Values": {
       "AzureWebJobsStorage": "DefaultEndpointsProtocol=https;AccountName=xxx;AccountKey=xxx;EndpointSuffix=core.windows.net",
       "FUNCTIONS_WORKER_RUNTIME": "python"
     }
   }
   ```

3. Run locally:

   ```bash
   func start
   ```

4. Test the function:

   ```bash
   curl -X POST http://localhost:7071/api/process_fit \\
     -H "Content-Type: application/json" \\
     -d @tests/data/test_payload_example.json
   ```

## Deployment

Deploy to Azure:

```bash
func azure functionapp publish <FUNCTION_APP_NAME>
```

## Integration with iCloud Drive

Use the built-in iCloud sync functions:

1. Set iCloud WebDAV environment variables
2. Use the hourly timer trigger for automatic sync
3. Optionally trigger manually via `POST /api/icloud/sync` with `{ "days": 30 }`
