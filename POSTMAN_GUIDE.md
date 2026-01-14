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

### Azure Deployment
- Set the Postman variable `azure_function_name` to your deployed function app name
- Go to: Collection → Variables → Set `azure_function_name`

## Test Requests

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

### Using Python:
```python
import base64

with open('your_workout.fit', 'rb') as f:
    content = f.read()
    b64_content = base64.b64encode(content).decode('utf-8')
    print(b64_content)
```

### Using Command Line (macOS/Linux):
```bash
base64 -i your_workout.fit
```

### Using PowerShell (Windows):
```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("your_workout.fit"))
```

## Tips

1. **First Test**: Use a small FIT file to verify the function works
2. **Idempotency Test**: Send the same payload twice to verify duplicate detection
3. **Storage**: Ensure Azure Table Storage is configured (local emulator or Azure)
4. **Logs**: Check function logs for detailed processing information
5. **Large Files**: FIT files can be large; ensure your Postman timeout is sufficient

## Troubleshooting

- **Connection Refused**: Make sure the function app is running
- **500 Errors**: Check function logs for parsing or storage errors
- **Timeout**: Large FIT files may take longer to process
- **Storage Errors**: Verify Azure Storage connection string in local.settings.json
