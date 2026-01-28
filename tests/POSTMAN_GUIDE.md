# Postman Testing Guide for Health Assistant Function App

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

- `source_item_id` - OneDrive item ID
- `source_file_path` - File path in OneDrive
- `source_drive_id` - OneDrive drive ID
- `source_etag` - OneDrive ETag for versioning
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

- **Connection Refused**: Make sure the function app is running
- **500 Errors**: Check function logs for parsing or storage errors
- **Timeout**: Large FIT files may take longer to process
- **Storage Errors**: Verify Azure Storage connection string in local.settings.json
