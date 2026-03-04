# Postman Testing Guide for Health Assistant Function App

**Quick Reference**: Ready-to-use API testing collection with 31 requests covering all endpoints.

**Latest Update** (March 4, 2026): Ingestion handlers refactored for improved maintainability and structured logging. All 33 endpoints verified; 57/57 integration tests passing. Added lap detail endpoint and Intervals.icu sync. No breaking API changes.

## Quick Links

- [API Alignment Report](./API_ALIGNMENT.md) - Verification that collection, openapi.yaml, and function_app.py are aligned
- [postman_collection.json](./postman_collection.json) - Ready-to-use test collection (import this!)
- [Complete API Reference](../../docs/gpt/SEMANTIC_LAYER_API.md) - Full API documentation

## What's Included

The Postman collection provides organized testing for:

- ✅ **Agent Memory System** (6 requests) - Preferences, observations, context
- ✅ **Planning & Analysis** (8 requests) - Planning context, workouts, rollups, zones
- ✅ **Real Data Tests** (3 requests) - Actual FIT files (small, medium, large)  
- ✅ **Physiometrics** (3 requests) - Body metrics CRUD operations
- ✅ **Configuration** (4 requests) - Config management and asset endpoints
- ✅ **Backend Integration** (9 requests) - OneDrive sync, Garmin sync, Intervals.icu sync, Withings OAuth flows
- ✅ **System Health** (1 request) - Health check endpoint

**Total**: 34 pre-configured requests ready to run

## Import Collection

1. Open Postman
2. Click **Import** button
3. Select `postman_collection.json` from this directory
4. The collection "Health Assistant - FIT File Processing" will be imported

## Setup

### Local Development

- Ensure your Azure Function is running locally (default: `http://localhost:7071`)
- Run the function using: `func host start`

### Health Check

The `/health` endpoint is **anonymous** (no authentication required) and returns:

```json
{
  "status": "healthy",
  "timestamp": "2026-01-28T10:30:00.000000+00:00",
  "storage": "ok"
}
```

Returns HTTP 503 with `"status": "degraded"` if storage connectivity fails.

### Azure Deployment

- Set the Postman variable `azure_function_name` to your deployed function app name
- Go to: Collection → Variables → Set `azure_function_name`

## Agent Memory Endpoints (Priority 0)

The collection includes a dedicated **Agent Memory** folder with 6 endpoints for managing user preferences and training observations:

### Core Endpoints

1. **GET /api/agent/context** - Priority 0 endpoint that returns combined context (preferences + active observations). Call this at conversation start.
2. **GET /api/agent/preferences** - Get user training preferences (goal, phase, sports, FTP test cadence)
3. **POST /api/agent/preferences** - Update preferences (requires function key)
4. **GET /api/agent/observations** - List training observations filtered by status (active/resolved/archived)
5. **POST /api/agent/observations** - Add new observation (fatigue, injury, performance, etc.)
6. **PATCH /api/agent/observations/{id}** - Update observation status (requires function key)

### Usage

- **GET endpoints** are public (no auth required)
- **POST/PATCH endpoints** require function key authentication
- See [AGENT_MEMORY.md](../../docs/gpt/AGENT_MEMORY.md) for detailed documentation

## Test Requests

### Real Data Tests (Recommended)

The collection includes three real FIT files from the `data/` folder with actual workout data:

#### 1. Strength Training - Apple Watch

- **File**: `test_payload_2026-01-04-163358-Functional Strength Training-Robert's Apple Watch Ultra 3.json`
- **Size**: 11 KB
- **Tests**: Functional strength training metrics, HR tracking without power data

#### 2. Indoor Cycling - RunGap (Short)

- **File**: `test_payload_2026-01-10-211457-Indoor Cycling-RunGap.json`
- **Size**: 52 KB  
- **Tests**: Power, cadence, HR zones, shorter workout metrics

#### 3. Indoor Cycling - RunGap (Long)

- **File**: `test_payload_2026-01-12-183000-Indoor Cycling-RunGap.json`
- **Size**: 121 KB
- **Tests**: Full metrics including TSS, Intensity Factor, Normalized Power, aerobic efficiency, larger file parsing

**To use these:**

1. Import the collection
2. Navigate to "Real Data Tests" folder
3. Run any of the three requests
4. These files are loaded directly from the `data/` folder (no copy/paste needed!)

### 1. Process FIT File - Local Development

**Endpoint:** `POST http://localhost:7071/api/process_fit`

**Required Payload Fields:**

- `athlete_id` - Athlete identifier (e.g., "rob")
- `source_file_name` - Original file name (e.g., "2026-01-13-workout.fit")
- `file_content_b64` - Base64-encoded FIT file content

**Optional Fields:**

- `source_item_id` - Source item ID (if available)
- `source_file_path` - Source file path (e.g., `/Apps/HealthFit/...`)
- `source_drive_id` - Source drive ID (if available)
- `source_etag` - Source ETag for versioning (if available)
- `file_size_bytes` - Original file size

**Expected Success Response (200):**

```json
{
  "status": "success",
  "workout_id": "rob_2026-01-13T14:30:00_uuid",
  "athlete_id": "rob",
  "sport": "running",
  "duration_sec": 3600,
  "metrics": {
    "distance_m": 10000,
    "avg_power_watts": 250,
    "avg_hr_bpm": 145
  }
}
```

**Expected Duplicate Response (200):**

```json
{
  "status": "skipped",
  "reason": "File already processed",
  "workout_id": "existing_workout_id"
}
```

### 2. Test Invalid Payload

Tests validation by omitting required fields.

**Expected Error Response (400):**

```json
{
  "error": "Missing required fields: ['source_file_name', 'file_content_b64']"
}
```

### 3. Test Invalid Base64

Tests base64 decoding error handling.

**Expected Error Response (400):**

```json
{
  "error": "Invalid base64 encoding"
}
```

## How to Get Base64 Content for Testing

### Option 1: Use Pre-Generated Test Files (Recommended)

The `data/` folder contains 8 real FIT files with pre-generated JSON payloads:

**Available Test Files:**

- `2026-01-04` - Functional Strength Training (Apple Watch)
- `2026-01-06` - Indoor Cycling (HealthFit)
- `2026-01-07` - Outdoor Walking (Apple Watch)
- `2026-01-07` - Functional Strength Training (Apple Watch)
- `2026-01-08` - Indoor Cycling (HealthFit)
- `2026-01-10` - Functional Strength Training (Apple Watch)
- `2026-01-10` - Indoor Cycling (RunGap) ✓ Pre-converted
- `2026-01-12` - Indoor Cycling (RunGap) ✓ Pre-converted

Three are already converted to JSON payloads and included in the Postman collection. To convert additional files:

```bash
cd tests/data
python3 << 'EOF'
import base64, json
from pathlib import Path

fit_file = "2026-01-06-220813-Indoor Cycling-HealthFit.fit"
with open(fit_file, 'rb') as f:
    b64 = base64.b64encode(f.read()).decode('utf-8')

payload = {
    "athlete_id": "rob",
    "source_file_name": fit_file,
    "file_content_b64": b64
}

with open(f"test_payload_{fit_file.replace('.fit', '.json')}", 'w') as out:
    json.dump(payload, out, indent=2)
EOF
```

### Option 2: Convert Your Own Files

### Using Python

```python
import base64

with open('your_workout.fit', 'rb') as f:
    content = f.read()
    b64_content = base64.b64encode(content).decode('utf-8')
    print(b64_content)
```

### Using Command Line (macOS/Linux)

```bash
base64 -i your_workout.fit
```

### Using PowerShell (Windows)

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("your_workout.fit"))
```

## Tips

1. **Start with Real Data**: Use the "Real Data Tests" folder in the collection - these are actual workouts with complete metrics
2. **File Size Testing**:
   - Small file (11 KB): Strength Training test - fastest to process
   - Medium file (52 KB): Short cycling workout - tests basic metrics
   - Large file (121 KB): Long cycling workout - tests TSS, aerobic efficiency, full metrics
3. **Idempotency Test**: Send the same payload twice to verify duplicate detection
4. **Storage**: Ensure Azure Table Storage is configured (local emulator or Azure)
5. **Logs**: Check function logs for detailed processing information
6. **Different Sports**: Test files include cycling, strength training, and walking for comprehensive coverage

## Troubleshooting

### Connection Issues

- **Connection Refused**: Make sure the function app is running (`func start`)
- **Timeout**: Large FIT files may take longer to process (expect <1 second for 121 KB file)
- **Port conflicts**: Try different port if 7071 is in use

### Request Errors

- **500 Errors**: Check function logs for parsing or storage errors
- **400 Bad Request**: Verify JSON payload structure and required fields
- **401 Unauthorized**: Add function key for admin endpoints
- **404 Not Found**: Check endpoint URL and workout_id

### Data Issues

- **Storage Errors**: Verify Azure Storage connection string in local.settings.json
- **Duplicate detection**: Sending same payload twice should return "skipped" status
- **Missing metrics**: Some workouts naturally lack certain data (e.g., power on non-power devices)

## Additional Resources

- [Complete API Reference](../../docs/gpt/SEMANTIC_LAYER_API.md) - All 31 endpoints documented
- [Test Data Files](../data/README.md) - FIT file details and conversion scripts
- [Main Testing Guide](../README.md) - Complete test suite (330 tests)
- [API Alignment Report](./API_ALIGNMENT.md) - Collection consistency verification

---

**Collection Status**: ✅ Aligned with Function App (31 requests covering all endpoints)

**Last Updated**: February 2026
