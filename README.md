# Health Assistant - Workout Intelligence System

Azure Function App that parses FIT workout files from multiple sources (OneDrive Personal, Garmin Connect, direct upload), integrates body metrics from Withings, and provides a comprehensive Semantic API for training intelligence powered by ChatGPT.

**Status**: ✅ Production Ready - Deployed with 37 Endpoints, 330 Tests, Agent Memory System

## Quick Navigation

| Role | Start Here |
| --- | --- |
| **First time?** | [Architecture Overview](#architecture) below |
| **Deploying?** | [DEPLOYMENT.md](./docs/devops/DEPLOYMENT.md) (30 min) |
| **Setting up dashboards?** | [MONITORING.md](./docs/devops/MONITORING.md) → Power BI section |
| **Building integrations?** | [SEMANTIC_LAYER_API.md](./docs/gpt/SEMANTIC_LAYER_API.md) |
| **Agent memory system?** | [AGENT_MEMORY.md](./docs/gpt/AGENT_MEMORY.md) |
| **Configuring backends?** | [BACKENDS.md](./docs/devops/BACKENDS.md) → OneDrive, Withings, Garmin |
| **Understanding the data model?** | [WORKOUT_SCHEMA.md](./docs/gpt/WORKOUT_SCHEMA.md) |
| **Chaos testing?** | [CHAOS.md](./docs/devops/CHAOS.md) |
| **Design philosophy?** | [WORKOUT_INTELLIGENCE_AGENT_VISION.md](./docs/gpt/WORKOUT_INTELLIGENCE_AGENT_VISION.md) |

## Architecture

```text
Data Sources
├── OneDrive Personal (/Apps/HealthFit) - FIT files via OAuth + Microsoft Graph
├── Withings - Body metrics via OAuth webhook
└── Direct Upload - Manual FIT file ingestion
    ↓
Azure Functions App (31 HTTP/Timer Endpoints)
    ├── FIT Ingestion Layer
   │   ├── FIT Parser (fitdecode library)
    │   ├── Metric Computation (TSS, IF, NP, EF)
    │   └── Zone Calculation (HR/Power zones)
    ├── Backend Integration Layer
    │   ├── OneDrive OAuth + Hourly Sync
    │   ├── Withings OAuth + Webhook
    │   └── Idempotency Tracking
    └── Handler Architecture
        ├── OneDriveSyncHandler
        ├── QueryHandler
        ├── PhysiometricsHandler
        ├── WithingsHandler
        ├── ConfigHandler
        ├── HealthHandler
        └── AgentMemoryHandler
    ↓
Azure Table Storage (6 Tables)
    ├── Workouts (100+ fields per session)
    ├── WeeklyRollups (aggregated training summaries)
    ├── IngestionState (idempotency + deduplication)
    ├── Physiometrics (body composition from Withings)
    ├── AgentPreferences (user training goals & preferences)
    └── AgentObservations (training patterns & insights)
    ↓
Semantic Layer API (14 Core + 15 Supporting Endpoints)
    ├── Agent Memory System
    │   ├── /api/agent/context (primary context loader)
    │   ├── /api/agent/preferences (training goals)
    │   └── /api/agent/observations (training insights)
    ├── Planning & Analysis (WorkoutProjection v3.2.0+)
    │   ├── /api/planning/context (lightweight projections; 30 fields ~40-50% payload reduction)
    │   ├── /api/workouts (lightweight projections with optional filters)
    │   ├── /api/workouts/{workout_id} (full detail: zones, efficiency, metrics)
    │   ├── /api/rollups/weekly (aggregated summaries)
    │   └── /api/analysis/* (zones, efficiency)
    └── Configuration & Health
        ├── /api/physiometrics/* (body metrics)
        ├── /api/config/* (system configuration)
        └── /api/health (health check)
    ↓
Read Interfaces
├── ChatGPT Workout Intelligence Agent (primary interface)
├── Power BI Dashboards (training analytics visualization)
└── Application Insights (system monitoring & telemetry)
```

### Data Flow

- **Ingestion Triggers**:
  - Hourly timer trigger for OneDrive sync (Microsoft Graph API)
  - Withings webhook for real-time body metrics
  - HTTP endpoint for manual FIT file uploads
  - Daily backup export to Azure Blob Storage
  
- **Input**:
  - Base64-encoded FIT files + metadata (from OneDrive or direct upload)
  - Withings physiometric payloads (weight, composition, vitals)
  
- **Processing**:
  - FIT parsing with fitdecode library
  - Metric extraction (100+ fields)
  - Zone computation (HR: HRmax/LTHR/HRR; Power: 7-zone Coggan)
  - Training load calculation (TSS, IF, NP)
  - Aerobic efficiency metrics (EF, HR drift, decoupling)
  - Weekly rollup aggregation
  
- **Storage**:
  - Azure Tables with composite keys for efficient querying
  - Immutable workout records with embedded zone definitions
  - Time-series body metrics with Withings integration
  - Agent memory (preferences + observations)
  
- **Read Layer**:
  - Semantic API endpoints optimized for LLM consumption
  - Summary-first approach (full time-series on demand)
  - Built-in query protections (max results, date ranges)
  - Agent context loader for GPT conversation initialization

## Configuration

### Required Environment Variables

**Azure Storage** (one of the following):

- `AzureWebJobsStorage`: Full connection string to Azure Storage account (standard approach)
- `AZURE_STORAGE_ACCOUNT_URL`: Direct storage account URL (alternative, uses DefaultAzureCredential)

**Azure Functions Runtime**:

- `FUNCTIONS_WORKER_RUNTIME`: Set to `python`

### Optional Configuration

**Athlete Settings**:

- `DEFAULT_ATHLETE_ID`: Default athlete identifier (default: `'rob'`)
- `DEFAULT_FTP`: Default Functional Threshold Power for power zones (default: `250` watts)
- `DEFAULT_MAX_HR`: Default maximum heart rate for HR zones (default: `190` bpm)

**Heart Rate Zone Configuration**:

- `HR_ZONE_BASIS`: Zone calculation method (default: `'HRmax'`)
  - `'HRmax'` - Percentage of maximum heart rate
  - `'LTHR'` - Lactate Threshold Heart Rate
  - `'HRR'` - Heart Rate Reserve (Karvonen method)
- `HR_ZONE_REFERENCE_BPM`: Reference HR for zone calculation (default: `0` = auto-detect from workout)
- `HR_RESTING_BPM`: Resting heart rate for HRR method (default: `60` bpm)

**OneDrive Personal Integration** (see [BACKENDS.md](./docs/devops/BACKENDS.md) for setup):

- `ONEDRIVE_CLIENT_ID`: Azure app registration client ID (consumer/personal accounts)
- `ONEDRIVE_CLIENT_SECRET`: Azure app registration client secret
- `ONEDRIVE_REDIRECT_URI`: OAuth redirect URI (points to `/api/onedrive/callback`)
- `ONEDRIVE_SCOPES`: Space-delimited OAuth scopes (default: `'Files.ReadWrite offline_access'`)
- `ONEDRIVE_FOLDER_PATH`: Target folder path (default: `'/Apps/HealthFit'`)
- `ONEDRIVE_SYNC_LOOKBACK_DAYS`: Sync window in days (default: `30`)

**Withings Integration** (see [BACKENDS.md](./docs/devops/BACKENDS.md) for setup):

- `WITHINGS_CLIENT_ID`: Withings app client ID
- `WITHINGS_CLIENT_SECRET`: Withings app client secret
- `WITHINGS_REDIRECT_URI`: OAuth redirect URI (points to `/api/withings/callback`)

**Garmin Connect Integration** (see [BACKENDS.md](./docs/devops/BACKENDS.md) for setup):

- `GARMIN_CLIENT_ID`: Garmin developer app client ID
- `GARMIN_CLIENT_SECRET`: Garmin developer app client secret
- `GARMIN_REDIRECT_URI`: OAuth redirect URI (points to `/api/garmin/callback`)
- `GARMIN_SYNC_LOOKBACK_DAYS`: Activity sync window in days (default: `30`)

**API Documentation** (for ChatGPT plugin):

- `PUBLIC_BASE_URL`: Externally reachable base URL (auto-detected if not set)
- `API_DOCS_DIR`: API documentation directory path (default: `./api_docs`)
- `PLUGIN_LOGO_URL`: Logo URL for ChatGPT plugin
- `PLUGIN_CONTACT_EMAIL`: Contact email for plugin manifest
- `PLUGIN_LEGAL_URL`: Legal/terms URL for plugin manifest

**Advanced Configuration**:

- `PHYSIOMETRICS_PATH`: Custom path to physiometrics.json configuration file

### Configuration Precedence

The system loads configuration in this order (highest priority first):

1. **Azure Table Storage** - Physiometrics table (runtime updates, no redeployment needed)
2. **Environment Variables** - Function App settings or local.settings.json
3. **Filesystem** - `config/physiometrics.json` (local development)
4. **Hard Defaults** - Built-in fallback values

See [config/README.md](./config/README.md) for detailed physiometrics configuration.

## Project Structure

```text
health_assistant/
├── function_app.py               # Azure Functions HTTP adapter (37 endpoints)
├── pyproject.toml                # Build configuration & dependencies
├── requirements.txt              # Runtime dependencies for Azure
├── local.settings.json           # Local development secrets (not committed)
├── host.json                     # Azure Functions host configuration
│
├── TrainingAnalyticsPlatform/                    # Core parsing & business logic
│   ├── fit_parser.py             # FIT file parsing + metric computation
│   ├── models/                   # Pydantic data models (see models/README.md for architecture)
│   │   ├── README.md             # Model design patterns, composition, usage examples
│   │   ├── core.py               # WorkoutMetricsModel, CanonicalAnalyticsEngine
│   │   ├── substrate.py          # CanonicalRecord, CanonicalLap
│   │   ├── legacy.py             # Workout, WorkoutSession, DeviceInfo, RecordSample
│   │   ├── agent.py              # AgentPreferences, AgentObservation
│   │   ├── constants.py          # Shared constants, utilities, decorators
│   │   └── metrics/              # Metric submodels (8 files)
│   ├── adapter.py                # fitdecode → pydantic mapping
│   ├── table_storage.py          # Azure Tables client (6 tables)
│   ├── config.py                 # Configuration management (multi-source)
│   ├── semantic_layer.py         # Read API implementation (14 endpoints)
│   ├── exceptions.py             # Custom exception hierarchy
│   ├── types.py                  # Type definitions & enums
│   ├── logging_setup.py          # Centralized logging configuration
│   ├── onedrive_client.py        # Microsoft Graph OAuth client
│   ├── withings_client.py        # Withings OAuth + webhook client
│   ├── withings_webhook_processor.py  # Withings payload processing
│   ├── backup_exporter.py        # Daily backup to Blob Storage
│   ├── apple_workout_types.py    # Apple Watch workouts mapping
│   └── handlers/                 # HTTP business logic handlers
│       ├── fit_payload_handler.py      # FIT ingestion workflow
│       ├── onedrive_sync_handler.py    # OneDrive sync ingestion + endpoint
│       ├── query_handler.py            # Workout query orchestration
│       ├── physiometrics_handler.py    # Body metrics CRUD
│       ├── withings_handler.py         # Withings integration
│       ├── config_handler.py           # Configuration management
│       ├── health_handler.py           # System health checks
│       └── agent_memory_handler.py     # GPT memory management
│
├── config/                       # Configuration templates
│   ├── README.md                 # Configuration documentation
│   ├── physiometrics.json.example      # Athlete metrics template
│   └── onedrive_power_automate_legacy.json.example  # Legacy Power Automate config
│
├── docs/                         # Comprehensive documentation
│   ├── AGENT_MEMORY.md           # GPT memory system architecture
│   ├── BACKENDS.md               # OneDrive/Withings/Garmin integration
│   ├── DEPLOYMENT.md             # Azure deployment procedures
│   ├── MONITORING.md             # Power BI dashboards & monitoring
│   ├── SEMANTIC_LAYER_API.md     # Complete API reference (37 endpoints)
│   ├── WORKOUT_SCHEMA.md         # Data model specification (100+ fields)
│   ├── WORKOUT_INTELLIGENCE_AGENT_VISION.md  # System design philosophy
│   ├── GPT_ACTIONS_GUIDE.md      # ChatGPT integration guide
│   ├── INSTRUCTIONS.md           # GPT agent instructions
│   ├── CYCLING_CONTEXT.md        # Cycling-specific training context
│   ├── MOVESMETHOD_CONTEXT.md    # Training methodology context
│   └── ROB_CONTEXT.md            # Personal athlete context
│
├── api_docs/                     # ChatGPT plugin specification
│   ├── ai-plugin.json            # Plugin manifest
│   ├── openapi.yaml              # OpenAPI 3.0 spec (semantic/read endpoints)
│   ├── openapi.operations.yaml   # OpenAPI 3.0 spec (full operations)
│   └── README.md                 # API specification documentation
│
├── tests/                        # Comprehensive test suite (330 tests)
│   ├── test_config.py            # Configuration tests (24)
│   ├── test_config_handler.py    # Config handler tests (13)
│   ├── test_fit_parser.py        # Core parser tests (44)
│   ├── test_fit_parser_integration.py  # Integration tests (2)
│   ├── test_function_app_extras.py     # Function helpers (30)
│   ├── test_function_endpoints.py      # HTTP endpoint tests (14)
│   ├── test_handlers_example.py  # Handler patterns (17)
│   ├── test_health_handler.py    # Health check tests (14)
│   ├── test_is_indoor_inference.py     # Indoor detection (7)
│   ├── test_onedrive_sync.py     # OneDrive sync logic (7)
│   ├── test_onedrive_sync_handler.py   # Sync handler tests (24)
│   ├── test_physiometrics_handler.py   # Physiometrics CRUD (16)
│   ├── test_physiometrics_timeseries.py  # Time-series tests (11)
│   ├── test_query_handler.py     # Query handler tests (18)
│   ├── test_schema_fields.py     # Schema validation (5)
│   ├── test_semantic_layer.py    # Semantic API tests (27)
│   ├── test_semantic_layer_endpoints.py  # Endpoint integration (17)
│   ├── test_smoke.py             # Smoke tests (12)
│   ├── test_table_storage_physiometrics.py  # Storage tests (12)
│   ├── test_withings_handler.py  # Withings tests (16)
│   ├── conftest.py               # Pytest fixtures
│   ├── data/                     # Real FIT workout files
│   │   ├── README.md             # Test data documentation
│   │   ├── *.fit                 # Real workout files (8 files)
│   │   └── test_payload_*.json   # Pre-generated test payloads (3)
│   └── postman/                  # API testing
│       ├── README.md             # Postman testing guide
│       ├── postman_collection.json     # Ready-to-use collection
│       └── API_ALIGNMENT.md      # API consistency verification
│
├── scripts/                      # Utility scripts
└── htmlcov/                      # Code coverage reports
```

## Implemented Capabilities

### 🏋️ FIT Parsing & Metric Extraction

**Core Workout Metrics** (100+ fields per workout):

- **Temporal**: Start time, end time, duration, moving time, elapsed time
- **Heart Rate**: Average, max, samples, missing %, resting HR, time in zones (7 zones)
- **Power**: Average, max, normalized power (NP), variability index, FTP, time in zones (7 zones)
- **Cadence**: Average, max (cycling RPM or running cadence)
- **Distance & Elevation**: Total distance, elevation gain, ascent/descent
- **Speed**: Average, max speed
- **Sport Classification**: Activity type, sub-type, device manufacturer
- **Indoor Detection**: Automatic inference (GPS, power, location)

**Supported File Sources**:

- HealthFit exports (.fit)
- Apple Watch workouts (.fit)
- RunGap exports (.fit)
- Garmin devices (.fit)
- Direct FIT file uploads

### 📊 Zone Computation & Training Load

**Heart Rate Zones** (3 calculation methods):

- **HRmax Method**: Percentage of maximum heart rate (default)
- **LTHR Method**: Lactate Threshold Heart Rate zones
- **HRR/Karvonen Method**: Heart Rate Reserve calculation
- **Time-in-Zone**: Seconds and derived minutes for each of 7 zones
- **Zone Boundaries**: Embedded in each workout record (10 fields)

**Power Zones** (7-zone Coggan model):

- **FTP-Based**: Zones calculated from Functional Threshold Power
- **Time-in-Zone**: Granular tracking across all intensity levels
- **Zone Boundaries**: Watts per zone embedded in workout (14 fields)

**Training Stress Metrics**:

- **TSS** (Training Stress Score): `(duration_hours × NP × IF × 100) / FTP`
- **Intensity Factor (IF)**: `normalized_power / FTP`
- **Normalized Power (NP)**: 30-second rolling average power
- **Variability Index (VI)**: `NP / average_power`
- **Work (kJ)**: Total kilojoules expended

### 💪 Aerobic Efficiency & Decoupling

**Efficiency Factor (EF)**: Power ÷ Heart Rate ratio

- First half EF
- Second half EF
- Overall workout EF

**Heart Rate Drift & Decoupling**:

- HR drift percentage (first half → second half)
- Aerobic decoupling: `((EF_first / EF_second) - 1) × 100`
  - **Positive sign** = efficiency decline (aerobic fatigue/stress during workout)
  - **Negative sign** = efficiency improvement (aerobic warming up or economy gain)
- Decoupling threshold detection (>5% = significant aerobic stress)

**Physiological Extraction**:

- Resting HR from FIT user_profile
- FTP extraction from device data
- Auto-detection of zone reference values

### 🔄 Backend Integrations

**OneDrive Personal** (OAuth + Microsoft Graph):

- Delegated authentication (consumer/personal accounts)
- Automatic hourly sync via timer trigger
- Configurable lookback window (default: 30 days)
- HTTP endpoint for manual sync: `POST /api/onedrive/sync`
- Idempotent ingestion (hash-based deduplication)
- Filename-based date filtering when available
- Refresh token persistence in Table Storage

**Withings Health Platform**:

- OAuth 2.0 integration with refresh token management
- Webhook-based real-time body metric ingestion
- Metrics: Weight, body fat %, muscle mass, bone mass, hydration
- Time-series tracking with Azure Table Storage
- CRUD endpoints for physiometrics data

**Garmin Connect** (OAuth + garth library):

- OAuth 1.0/2.0 hybrid authentication via garth
- Automatic daily sync via timer trigger (3 AM UTC)
- Configurable lookback window (default: 30 days)
- HTTP endpoint for manual sync: `POST /api/garmin/sync`
- FIT file download and parsing
- Token persistence in Table Storage

**Backup & Export**:

- Daily backup export to Azure Blob Storage (2 AM UTC)
- JSON export of all workout data
- Disaster recovery support

### 🤖 Agent Memory System

**Persistent Context** (stored in Azure Tables):

- **User Preferences** (`AgentPreferences` table):
  - Current training goals
  - Training phase (base, build, peak, recovery)
  - Preferred sports (priority-ordered)
  - FTP test frequency tracking
  - Last FTP test date
  
- **Training Observations** (`AgentObservations` table):
  - Pattern recognition (e.g., "consistent Z2 quality improvement")
  - Performance flags (e.g., "high decoupling on recent rides")
  - Insights with workout references
  - Priority levels (low, normal, high)
  - Status tracking (active, resolved, archived)
  - Optional expiration dates

**GPT Integration**:

- Primary context endpoint: `GET /api/agent/context`
- Loads preferences + active observations at conversation start
- Enables GPT to maintain long-term training awareness
- Separates ephemeral conversation from persistent facts

### 📈 Semantic Layer API (31 HTTP Endpoints + 2 Timers)

**Agent Memory** (6 endpoints):

- `GET /api/agent/context` - Combined context (preferences + observations)
- `GET /api/agent/preferences` - User training preferences
- `POST /api/agent/preferences` - Update preferences
- `GET /api/agent/observations` - List observations (filterable by status)
- `POST /api/agent/observations` - Add new observation
- `PATCH /api/agent/observations/{id}` - Update observation status

**Planning & Analysis** (9 endpoints):

- `GET /api/planning/context` - **Primary planning endpoint** (recent workouts, rollups, flags)
- `GET /api/workouts` - Query workouts (filters: date, sport, limit)
- `GET /api/workouts/{id}` - Full workout detail
- `GET /api/workouts/{id}/laps/{lap_index}` - Lap detail with records
- `GET /api/workouts/{id}/recalculated` - Recalculate with current config
- `GET /api/rollups/weekly` - Weekly aggregated summaries
- `GET /api/analysis/zones` - Time-in-zone distribution
- `GET /api/analysis/efficiency` - Efficiency trends & decoupling
- `GET /api/health` - System health check

**Physiometrics** (3 endpoints):

- `GET /api/physiometrics/current` - Current body metrics
- `GET /api/physiometrics/history` - Time-series body metrics
- `POST /api/physiometrics/update` - Manual metric updates

**Configuration** (3 endpoints):

- `POST /api/config/update` - Update athlete metrics (stored in Table Storage)
- `GET /api/config/history` - Configuration audit trail

**Backend Integration** (10 endpoints):

- `POST /api/process_fit` - Direct FIT file upload (admin)
- `GET /api/onedrive/authorize` - OneDrive OAuth flow (admin)
- `GET /api/onedrive/callback` - OAuth callback handler
- `POST /api/onedrive/sync` - Manual sync trigger (admin)
- `GET /api/withings/authorize` - Withings OAuth flow (admin)
- `GET /api/withings/callback` - Withings OAuth callback
- `POST /api/withings/webhook` - Withings webhook receiver
- `GET /api/garmin/authorize` - Garmin OAuth flow (admin)
- `GET /api/garmin/callback` - Garmin OAuth callback handler
- `POST /api/garmin/sync` - Manual sync trigger (admin)

**ChatGPT Plugin** (3 endpoints):

- `GET /api/.well-known/ai-plugin.json` - Plugin manifest
- `GET /api/openapi.yaml` - OpenAPI specification
- `GET /api/logo.svg` - Plugin logo

**Timer Triggers** (3 background jobs):

- Hourly OneDrive sync (Microsoft Graph delta query)
- Daily Garmin sync (3 AM UTC)
- Daily backup export to Blob Storage (2 AM UTC)

### 🎯 API Design Principles

**Summary-First Approach**:

- Endpoints return aggregated summaries by default
- Full time-series data available on demand
- Optimized for LLM token consumption

**Built-in Protections**:

- Max workout results: 200 per query
- Max date lookback: 365 days
- Max weekly rollups: 52 weeks
- Athlete ID required for all queries (Phase 1: defaults to "rob")

**Query Optimization**:

- Efficient Azure Table Storage queries
- Composite partition/row keys for performance
- Minimal cross-partition queries

### 🧪 Testing & Quality

**Comprehensive Test Suite** (330 tests across 20 files):

- **Unit Tests**: 290+ tests covering core logic
- **Integration Tests**: Real FIT file parsing with actual workout data
- **Handler Tests**: Complete coverage of HTTP handler logic
- **Endpoint Tests**: Azure Functions integration tests
- **Test Execution**: ~1-2 seconds total runtime
- **Code Coverage**: High coverage across all core modules

**Test Data**:

- 8 real FIT workout files (strength training, cycling, walking)
- 3 pre-generated JSON payloads for Postman testing
- Files from HealthFit, Apple Watch, and RunGap

**Continuous Testing**:

- Pytest framework with fixtures
- Mock-based testing for external dependencies
- Frozen time testing for temporal logic
- Parametrized tests for edge cases

### 📊 Data Storage

**Azure Table Storage** (6 tables):

1. **Workouts**: Immutable workout records (100+ fields)
2. **WeeklyRollups**: Aggregated training summaries
3. **IngestionState**: Idempotency tracking + file hashes
4. **Physiometrics**: Time-series body composition data
5. **AgentPreferences**: User training preferences
6. **AgentObservations**: Training insights & patterns

**Key Design Features**:

- Composite partition/row keys for efficient queries
- Embedded zone definitions (immutability for historical accuracy)
- Hash-based deduplication
- Audit trails for configuration changes

### 🔒 Security & Authentication

**Azure Functions Auth Levels**:

- `FUNCTION`: Requires function key (admin endpoints)
- `ANONYMOUS`: Public read endpoints (health, agent context, workouts)

**OAuth 2.0 Integrations**:

- OneDrive: Delegated auth with refresh tokens
- Withings: OAuth 2.0 with webhook signature validation

**Managed Identity Support**:

- Azure Storage access via DefaultAzureCredential
- Key Vault integration (optional)

### 📱 ChatGPT Integration

**Workout Intelligence Agent**:

- Custom GPT with Actions integration
- Primary context loader at conversation start
- Summary-first responses with data citations
- Tradeoff analysis and uncertainty communication
- Long-term memory via Agent Memory System

**GPT Actions Configuration**:

- OpenAPI 3.0 specification
- Function key authentication
- Plugin manifest with metadata
- Logo and branding support

## Local Development

### Prerequisites

- Python 3.8+ (3.10+ recommended)
- Azure Functions Core Tools v4
- Azure Storage Account (local development)
- Azure Storage Explorer (optional, for debugging)

### Setup Steps

1. **Clone the repository**:

   ```bash
   git clone https://github.com/rbarrimond/health_assistant.git
   cd health_assistant
   ```

2. **Create Python virtual environment**:

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**:

   ```bash
   pip install -r requirements.txt
   pip install -e ".[dev]"  # Install with dev dependencies for testing
   ```

4. **Create local configuration**:

   Create `local.settings.json` in the project root:

   ```json
   {
     "IsEncrypted": false,
     "Values": {
       "AzureWebJobsStorage": "DefaultEndpointsProtocol=https;AccountName=<your_account>;AccountKey=<your_key>;EndpointSuffix=core.windows.net",
       "FUNCTIONS_WORKER_RUNTIME": "python",
       "DEFAULT_ATHLETE_ID": "rob",
       "DEFAULT_FTP": "250",
       "DEFAULT_MAX_HR": "190",
       "HR_ZONE_BASIS": "HRmax"
     }
   }
   ```

   **Note**: `local.settings.json` is in `.gitignore` and should never be committed.

5. **Configure physiometrics** (optional, for custom zones):

   ```bash
   cp config/physiometrics.json.example config/physiometrics.json
   # Edit config/physiometrics.json with your athlete metrics
   ```

6. **Start the Functions host**:

   ```bash
   func start
   ```

   Or use VS Code task: **Terminal → Run Task → func: host start**

7. **Verify health endpoint**:

   ```bash
   curl http://localhost:7071/api/health
   ```

   Should return:

   ```json
   {
     "status": "healthy",
     "timestamp": "2026-02-05T10:30:00.000000+00:00",
     "storage": "ok"
   }
   ```

### Testing the Function

**Using curl with a real FIT file**:

```bash
# Test with pre-generated payload
curl -X POST http://localhost:7071/api/process_fit \
  -H "Content-Type: application/json" \
  -d @tests/data/test_payload_2026-01-12-183000-Indoor\ Cycling-RunGap.json
```

**Using Postman**:

1. Import collection from `tests/postman/postman_collection.json`
2. Run requests in the "Real Data Tests" folder
3. See [tests/postman/README.md](./tests/postman/README.md) for detailed guide

**Query workouts**:

```bash
# Get planning context
curl "http://localhost:7071/api/planning/context?athlete_id=rob&days=30"

# List recent workouts
curl "http://localhost:7071/api/workouts?athlete_id=rob&limit=10"

# Get weekly rollups
curl "http://localhost:7071/api/rollups/weekly?athlete_id=rob&weeks=8"
```

### Running Tests

**Full test suite** (330 tests):

```bash
pytest
```

**With coverage report**:

```bash
pytest --cov=TrainingAnalyticsPlatform --cov=function_app --cov-report=html
# Open htmlcov/index.html for detailed coverage report
```

**Run specific test file**:

```bash
pytest tests/test_fit_parser.py -v
```

**Run specific test class**:

```bash
pytest tests/test_semantic_layer.py::TestPlanningContext -v
```

**Run with verbose output**:

```bash
pytest -vv
```

### Development Workflow

1. **Make code changes** in `TrainingAnalyticsPlatform/` or `function_app.py`
2. **Run tests** to verify: `pytest tests/test_<module>.py`
3. **Test locally** with `func start`
4. **Check coverage**: `pytest --cov`
5. **Commit with tests**: Ensure all tests pass before pushing

### Debugging

**VS Code Launch Configuration**:

The project includes launch configurations for:

- Attaching to Python Functions
- Running pytest with debugging
- Debugging specific test files

Press **F5** to start debugging with Functions host.

**Enable verbose logging**:

Set environment variable:

```bash
export AZURE_FUNCTIONS_LOGGING_LEVEL=DEBUG
```

**View Application Insights locally**:

Application Insights telemetry is automatically sent when the connection string is configured.

### Local Development Issues

**Storage connection fails**:

- Check Azure Storage Account is accessible
- Try using Storage Emulator for local development

**OneDrive sync not working**:

- Ensure OAuth credentials are configured
- Complete authorization flow: `GET /api/onedrive/authorize`
- Check refresh token is persisted in Table Storage

**Tests failing**:

- Ensure all dev dependencies are installed: `pip install -e ".[dev]"`
- Clear pytest cache: `pytest --cache-clear`
- Check Python version: `python --version` (requires 3.8+)

## Deployment

### Azure Deployment

**Quick deployment** (requires Azure CLI and Functions Core Tools):

```bash
# Login to Azure
az login

# Deploy to existing Function App
func azure functionapp publish <FUNCTION_APP_NAME>
```

**Complete deployment guide**: See [docs/DEPLOYMENT.md](./docs/devops/DEPLOYMENT.md) for:

- Azure resource provisioning
- Function App configuration
- Application settings
- OneDrive OAuth setup
- Withings integration
- Custom domain configuration
- CI/CD with GitHub Actions

### Infrastructure as Code

Terraform modules are available in the companion repository:

**Repository**: [rbarrimond/azure-infra](https://github.com/rbarrimond/azure-infra)

**Modules**:

- `modules/health-assistant/` - Function App, Storage Account, Application Insights
- `modules/core/` - Shared infrastructure (Key Vault, Log Analytics)

See [azure-infra/HEALTH_ASSISTANT_DEPLOYMENT.md](../azure-infra/HEALTH_ASSISTANT_DEPLOYMENT.md) for infrastructure deployment.

### Environment-Specific Configuration

**Development**:

```bash
func azure functionapp publish health-assistant-dev
```

**Production**:

```bash
func azure functionapp publish health-assistant-prod
```

Use Azure Function App Settings or Terraform variables for environment-specific configuration.

### Post-Deployment Verification

1. **Health check**:

   ```bash
   curl https://<your-function-app>.azurewebsites.net/api/health
   ```

2. **Test FIT upload**:

   ```bash
   curl -X POST https://<your-function-app>.azurewebsites.net/api/process_fit?code=<function_key> \
     -H "Content-Type: application/json" \
     -d @tests/data/test_payload_example.json
   ```

3. **Verify OneDrive sync**:

- Navigate to: `https://<your-function-app>.azurewebsites.net/api/onedrive/authorize?code=<function_key>`
- Complete OAuth flow
- Check Application Insights for sync logs

1. **Monitor with Application Insights**:

- Check Function execution logs
- View telemetry in Azure Portal
- Set up alerts for failures

## Integration with OneDrive Personal

**Complete setup guide**: See [docs/BACKENDS.md](./docs/devops/BACKENDS.md#onedrive-personal-integration)

### OAuth Flow

1. **Authorize OneDrive access**:

   ```bash
   curl https://<your-function-app>.azurewebsites.net/api/onedrive/authorize?code=<function_key>&athlete_id=rob
   ```

2. **Complete browser sign-in**:

- You'll be redirected to Microsoft login
- Grant permissions to access OneDrive files
- Redirect back to callback endpoint
- Refresh token persisted in Table Storage

1. **Automatic sync**:

- Timer trigger runs hourly
- Syncs `/Apps/HealthFit` folder by default
- Processes new .fit files automatically

1. **Manual sync** (optional):

   ```bash
   curl -X POST https://<your-function-app>.azurewebsites.net/api/onedrive/sync?code=<function_key> \
     -H "Content-Type: application/json" \
     -d '{"athlete_id": "rob", "async": false}'
   ```

### Sync Behavior

- **Lookback window**: Default 30 days (configurable via `ONEDRIVE_SYNC_LOOKBACK_DAYS`)
- **Date filtering**: Uses workout date from filename when available (format: `YYYY-MM-DD`)
- **Fallback**: Uses OneDrive `lastModifiedDateTime` if filename parsing fails
- **Idempotency**: Hash-based deduplication prevents duplicate ingestion
- **Error handling**: Continues processing on individual file failures

## Integration with Withings

**Complete setup guide**: See [docs/BACKENDS.md](./docs/devops/BACKENDS.md#withings-integration)

### Authorization & Webhook Setup

1. **Authorize Withings access**:

   ```bash
   curl https://<your-function-app>.azurewebsites.net/api/withings/authorize?code=<function_key>&athlete_id=rob
   ```

2. **Complete browser authorization**:

- Sign in to Withings account
- Grant permissions for body metrics
- Redirect back to callback endpoint
- Refresh token persisted in Table Storage

1. **Configure webhook**:

- Withings sends real-time updates to: `/api/withings/webhook`
- Automatic body metric ingestion (weight, body fat %, muscle mass, etc.)
- Time-series storage in `Physiometrics` table

### Supported Metrics

- Weight (kg)
- Body fat percentage
- Muscle mass (kg)
- Bone mass (kg)
- Hydration percentage
- Timestamps and device info

## Integration with ChatGPT

**Complete guide**: See [docs/GPT_ACTIONS_GUIDE.md](./docs/gpt/GPT_ACTIONS_GUIDE.md)

### Plugin Configuration

1. **Create Custom GPT** in ChatGPT:

- Go to: <https://chat.openai.com/gpts/editor>
- Configure name: "Workout Intelligence Agent"
- Add instructions (see [docs/INSTRUCTIONS.md](./docs/gpt/INSTRUCTIONS.md))

1. **Configure Actions**:

- Import OpenAPI spec from: `https://<your-function-app>.azurewebsites.net/api/openapi.yaml`
- Add function key authentication: `?code=<function_key>`
- Configure plugin manifest: `https://<your-function-app>.azurewebsites.net/api/.well-known/ai-plugin.json`

1. **Primary Conversation Flow**:

   ```text
   1. Agent loads context: GET /api/agent/context?athlete_id=rob
   2. Agent retrieves planning data: GET /api/planning/context?days=45
   3. Agent analyzes and provides recommendations
   4. User asks follow-up questions
   5. Agent queries specific workouts/metrics as needed
   ```

### Agent Memory System

The GPT maintains long-term awareness through:

- **Preferences**: Training goals, phase, sport preferences, FTP test cadence
- **Observations**: Active patterns, flags, insights with workout references
- **Context Loading**: Automatic at conversation start via `/api/agent/context`

See [docs/AGENT_MEMORY.md](./docs/gpt/AGENT_MEMORY.md) for detailed architecture.

## Monitoring & Analytics

**Complete guide**: See [docs/MONITORING.md](./docs/devops/MONITORING.md)

### Application Insights

**Automatic telemetry collection**:

- Function execution logs
- Request/response tracking
- Exception logging
- Custom metrics and events
- Performance counters

**Query examples**:

```kusto
// Failed function executions
requests
| where success == false
| project timestamp, name, resultCode, duration
| order by timestamp desc

// OneDrive sync performance
traces
| where message contains "OneDrive sync"
| summarize count() by bin(timestamp, 1h)
```

### Power BI Dashboards

**Connect to Azure Table Storage**:

1. Open Power BI Desktop
2. Get Data → Azure → Azure Table Storage
3. Enter storage account connection string
4. Load `Workouts`, `WeeklyRollups`, and `Physiometrics` tables

**Pre-built visualizations** (see [docs/MONITORING.md](./docs/devops/MONITORING.md)):

- Training volume trends (weekly TSS, duration)
- Time-in-zone distribution (HR and power)
- Aerobic decoupling analysis
- Body weight and composition trends
- FTP progression tracking
- Sport distribution (cycling, running, strength)

### Health Checks

**Endpoint**: `GET /api/health`

**Response**:

```json
{
  "status": "healthy",
  "timestamp": "2026-02-05T10:30:00.000000+00:00",
  "storage": "ok"
}
```

Returns HTTP 503 with `"status": "degraded"` if storage connectivity fails.

**Automated Monitoring**:

- Set up Azure Monitor alerts on health endpoint
- Configure Application Insights availability tests
- Alert on function execution failures

## Performance & Scaling

**Current Performance**:

- FIT file parsing: <1 second per file (typical indoor cycling workout)
- Test suite execution: ~1-2 seconds (330 tests)
- API response times: <200ms (planning context endpoint)

**Azure Functions Scaling**:

- Consumption Plan: Automatic scaling based on load
- Timer triggers: Run independently on schedule
- HTTP triggers: Scale based on concurrent requests

**Storage Optimization**:

- Composite partition/row keys for efficient queries
- Minimal cross-partition queries
- Table Storage pagination for large result sets

See [docs/DEPLOYMENT.md](./docs/devops/DEPLOYMENT.md#scaling-and-performance) for scaling recommendations.

## Documentation

### Core Documentation

|Document|Purpose|Audience|
|-|-|-|
|[DEPLOYMENT.md](./docs/devops/DEPLOYMENT.md)|Azure deployment procedures|DevOps, Infrastructure|
|[BACKENDS.md](./docs/devops/BACKENDS.md)|OneDrive, Withings, Garmin integration|Developers, Users|
|[SEMANTIC_LAYER_API.md](./docs/gpt/SEMANTIC_LAYER_API.md)|Complete API reference (37 endpoints)|Developers, GPT Config|
|[WORKOUT_SCHEMA.md](./docs/gpt/WORKOUT_SCHEMA.md)|Data model (100+ fields)|Developers, Data Analysts|
|[AGENT_MEMORY.md](./docs/gpt/AGENT_MEMORY.md)|GPT memory system architecture|GPT Developers|
|[MONITORING.md](./docs/devops/MONITORING.md)|Power BI dashboards & monitoring|Athletes, Analysts|

### Design & Context

|Document|Purpose|Audience|
|-|-|-|
|[WORKOUT_INTELLIGENCE_AGENT_VISION.md](./docs/gpt/WORKOUT_INTELLIGENCE_AGENT_VISION.md)|System design philosophy|Architects, Contributors|
|[GPT_ACTIONS_GUIDE.md](./docs/gpt/GPT_ACTIONS_GUIDE.md)|ChatGPT integration guide|GPT Developers|
|[INSTRUCTIONS.md](./docs/gpt/INSTRUCTIONS.md)|GPT agent instructions|GPT Configuration|
|[CYCLING_CONTEXT.md](./docs/gpt/context/CYCLING_CONTEXT.md)|Cycling training context|Athletes, GPT|
|[MOVESMETHOD_CONTEXT.md](./docs/gpt/context/MOVESMETHOD_CONTEXT.md)|Training methodology|Athletes, Coaches|
|[ROB_CONTEXT.md](./docs/gpt/context/ROB_CONTEXT.md)|Personal athlete context|Athletes|

### Testing Documentation

|Document|Purpose|Audience|
|-|-|-|
|[tests/README.md](./tests/README.md)|Comprehensive test documentation|Developers|
|[tests/data/README.md](./tests/data/README.md)|Test data files guide|Developers|
|[tests/postman/README.md](./tests/postman/README.md)|Postman testing guide|Testers, Developers|
|[config/README.md](./config/README.md)|Configuration management|Users, Developers|

## Use Cases

### 1. Daily Training Planning

**User**: "What should I do tomorrow?"

**GPT Agent Flow**:

1. Load context: `GET /api/agent/context?athlete_id=rob`
2. Get training history: `GET /api/planning/context?days=45`
3. Analyze recent workouts, identify patterns
4. Provide recommendation based on load, recovery, goals

### 2. Performance Analysis

**User**: "How's my aerobic decoupling looking?"

**GPT Agent Flow**:

1. Query efficiency trends: `GET /api/analysis/efficiency?days=90`
2. Identify decoupling patterns
3. Reference specific workouts with high decoupling
4. Provide insights and training recommendations

### 3. Body Composition Tracking

**User**: "Show my weight trends this month"

**GPT Agent Flow**:

1. Get physiometrics history: `GET /api/physiometrics/history?days=30`
2. Analyze weight, body fat %, muscle mass trends
3. Correlate with training volume
4. Provide insights on composition changes

### 4. Training Load Management

**User**: "What's my TSS load this week?"

**GPT Agent Flow**:

1. Get weekly rollups: `GET /api/rollups/weekly?weeks=8`
2. Compare current week vs. recent averages
3. Identify load spikes or drops
4. Recommend adjustments based on training phase

### 5. FTP Testing Reminders

**GPT Agent** (proactive):

- Checks `last_ftp_test_date` from preferences
- Compares to `ftp_test_frequency_weeks` setting
- Reminds athlete when test is due
- Tracks after test completion

## Contributing

**Development Setup**:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make changes with tests
4. Run test suite: `pytest`
5. Commit with descriptive messages
6. Push and create Pull Request

**Code Standards**:

- Python 3.8+ compatible
- Type hints for all function signatures
- Pydantic models for data validation
- Comprehensive docstrings
- 100% test coverage for new features

**Testing Requirements**:

- Add tests for all new features
- Maintain test execution time <3 seconds
- Use pytest fixtures for common setup
- Mock external dependencies

## Troubleshooting

### Common Issues

**"Unable to connect to storage"**:

- Verify `AzureWebJobsStorage` connection string
- Check storage account firewall rules
- Ensure Function App has network access to storage

**"OneDrive authorization failed"**:

- Verify `ONEDRIVE_CLIENT_ID` and `ONEDRIVE_CLIENT_SECRET`
- Check redirect URI matches Azure app registration
- Ensure OAuth consent granted for required scopes

**"FIT file parsing error"**:

- Verify FIT file is not corrupted
- Check file size is reasonable (<10 MB)
- Review Application Insights logs for detailed error
- Try with known-good test files from `tests/data/`

**"Workouts not syncing from OneDrive"**:

- Check OneDrive refresh token in Table Storage (`IngestionState` table)
- Verify timer trigger is running (check Application Insights)
- Test manual sync: `POST /api/onedrive/sync`
- Check lookback window configuration

**"Withings metrics not appearing"**:

- Verify webhook is configured correctly in Withings developer portal
- Check Withings refresh token in Table Storage
- Test webhook endpoint: `POST /api/withings/webhook` (requires signature)
- Review logs for webhook processing errors

**"High aerobic decoupling values"**:

- This is a training metric, not a bug!
- >5% decoupling indicates aerobic stress from workout
- Review efficiency trends: `GET /api/analysis/efficiency`
- Consider if Z2 workouts are truly low intensity

### Debug Mode

**Enable verbose logging**:

```bash
# Local development
export AZURE_FUNCTIONS_LOGGING_LEVEL=DEBUG

# Azure Function App Settings
az functionapp config appsettings set \
  --name <app-name> \
  --resource-group <resource-group> \
  --settings "AZURE_FUNCTIONS_LOGGING_LEVEL=DEBUG"
```

**View detailed logs**:

- Local: Console output from `func start`
- Azure: Application Insights → Logs → traces table

## License

This project is personal software for training analytics. Not licensed for commercial use.

## Support & Contact

**Issues**: Create an issue in the GitHub repository
**Email**: <rbarrimond+health-assistant@users.noreply.github.com>
**Documentation**: See [docs/](./docs/) directory for comprehensive guides

---

**Built with**: Python, Azure Functions, Azure Table Storage, Microsoft Graph API, Withings API, fitdecode, Pydantic, pytest
